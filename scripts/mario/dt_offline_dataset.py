#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用于 Decision Transformer 的马里奥离线数据集加载器（生产级实现）。

核心设计目标：
1. 初始化阶段不把所有 pkl 全量数据常驻内存；
2. 建立“按轨迹长度加权”的全局索引映射；
3. __getitem__ 时按需加载文件，并通过 LRU 缓存复用；
4. 固定 K 上下文窗口，自动截断 + 补零 + attention_mask。
"""

import argparse
import bisect
import os
import pickle
from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset


class MarioDTOfflineDataset(Dataset):
    """
    Decision Transformer 离线数据集。

    返回格式：
        (states, actions, returns_to_go, timesteps, attention_mask)

    其中：
        states:         [K, 4, 84, 84], float32, 已归一化到 [0, 1]
        actions:        [K], long
        returns_to_go:  [K], float32
        timesteps:      [K], long
        attention_mask: [K], long (真实数据=1, pad=0)
    """

    def __init__(
        self,
        data_root: str,
        context_len: int,
        cache_size: int = 8,
        strict: bool = True,
    ):
        """
        参数：
            data_root: pkl 文件目录，或单个 pkl 文件路径
            context_len: DT 固定上下文窗口 K
            cache_size: LRU 缓存的文件数量上限
            strict: 是否对缺失字段/异常结构抛错（True 推荐）
        """
        super().__init__()
        if context_len <= 0:
            raise ValueError(f"context_len 必须 > 0，当前为 {context_len}")
        if cache_size <= 0:
            raise ValueError(f"cache_size 必须 > 0，当前为 {cache_size}")

        self.data_root = os.path.abspath(data_root)
        self.context_len = int(context_len)
        self.cache_size = int(cache_size)
        self.strict = bool(strict)

        self.pkl_files = self._discover_pkl_files(self.data_root)
        if len(self.pkl_files) == 0:
            raise FileNotFoundError(f"未在路径中找到任何 .pkl 文件: {self.data_root}")

        # 全局索引映射（按轨迹长度加权）：
        # index_map[i] = (file_path, episode_idx, episode_len)
        self.index_map: List[Tuple[str, int, int]] = []
        # cumulative_steps[i] 表示 [0..i] 这些轨迹累计的“步数权重”
        self.cumulative_steps: List[int] = []
        self.total_steps = 0
        # 动作空间统计：用于构建 DT act_dim（全局最大动作ID + 1）
        self.max_action_id = -1
        self.action_vocab_size = 0

        self._build_global_index()
        if self.total_steps <= 0:
            raise RuntimeError("所有轨迹长度均为 0，无法构建可训练数据集。")

        # 仅缓存“文件级加载结果”，避免每个样本都反复 pickle.load。
        # 注意：缓存的是单文件内容，不是全量数据。
        self._load_file_cached = lru_cache(maxsize=self.cache_size)(self._load_file_raw)

    @staticmethod
    def _discover_pkl_files(path: str) -> List[str]:
        """发现数据文件：支持目录递归扫描与单文件输入。"""
        if os.path.isfile(path):
            if not path.lower().endswith(".pkl"):
                raise ValueError(f"输入是文件但不是 .pkl: {path}")
            return [path]

        if not os.path.isdir(path):
            raise FileNotFoundError(f"路径不存在: {path}")

        files: List[str] = []
        for root, _, names in os.walk(path):
            for name in names:
                if name.lower().endswith(".pkl"):
                    files.append(os.path.join(root, name))
        files.sort()
        return files

    @staticmethod
    def _extract_episodes(container) -> Sequence[Dict]:
        """
        支持两种 pkl 顶层格式：
        1) {"metadata":..., "episodes":[...]}
        2) 直接为 episodes 列表
        """
        if isinstance(container, dict):
            if "episodes" not in container:
                raise ValueError("pkl 顶层是 dict，但缺少 'episodes' 字段。")
            episodes = container["episodes"]
        elif isinstance(container, list):
            episodes = container
        else:
            raise ValueError(f"不支持的 pkl 顶层类型: {type(container)}")

        if not isinstance(episodes, (list, tuple)):
            raise ValueError(f"'episodes' 必须是 list/tuple，当前类型: {type(episodes)}")
        return episodes

    def _build_global_index(self):
        """
        仅扫描并建立索引映射，不保留所有轨迹数据。
        索引权重按轨迹长度 T 累计，实现“每个时间步近似等概率被采样”。
        """
        running = 0
        for file_path in self.pkl_files:
            with open(file_path, "rb") as f:
                obj = pickle.load(f)
            episodes = self._extract_episodes(obj)

            for ep_idx, ep in enumerate(episodes):
                if not isinstance(ep, dict):
                    if self.strict:
                        raise ValueError(f"{file_path} 的 episode[{ep_idx}] 不是 dict。")
                    continue

                if "actions" not in ep:
                    if self.strict:
                        raise ValueError(f"{file_path} 的 episode[{ep_idx}] 缺少 'actions'。")
                    continue

                ep_len = int(len(ep["actions"]))
                if ep_len <= 0:
                    continue

                ep_actions = np.asarray(ep["actions"])
                if ep_actions.size > 0:
                    ep_max = int(np.max(ep_actions))
                    if ep_max > self.max_action_id:
                        self.max_action_id = ep_max

                self.index_map.append((file_path, ep_idx, ep_len))
                running += ep_len
                self.cumulative_steps.append(running)

        self.total_steps = running
        self.action_vocab_size = self.max_action_id + 1 if self.max_action_id >= 0 else 0

    def _load_file_raw(self, file_path: str) -> Sequence[Dict]:
        """按需加载单个 pkl 文件（由 LRU 包装调用）。"""
        with open(file_path, "rb") as f:
            obj = pickle.load(f)
        return self._extract_episodes(obj)

    def __len__(self) -> int:
        """长度定义为“全局加权后的步数总和”。"""
        return self.total_steps

    def _locate_episode_by_global_index(self, idx: int) -> Tuple[str, int]:
        """
        将全局 idx 映射到具体 (file_path, episode_idx)。
        由于累计权重按步数构建，因此轨迹越长，被命中的概率越高。
        """
        if idx < 0:
            idx += self.total_steps
        if idx < 0 or idx >= self.total_steps:
            raise IndexError(f"索引越界: idx={idx}, len={self.total_steps}")

        pos = bisect.bisect_right(self.cumulative_steps, idx)
        file_path, ep_idx, _ = self.index_map[pos]
        return file_path, ep_idx

    def __getitem__(self, idx: int):
        file_path, ep_idx = self._locate_episode_by_global_index(idx)
        episodes = self._load_file_cached(file_path)
        if ep_idx >= len(episodes):
            raise RuntimeError(f"索引映射失效: {file_path} 中不存在 episode[{ep_idx}]")

        ep = episodes[ep_idx]
        required = ["observations", "actions", "returns_to_go", "timesteps"]
        for key in required:
            if key not in ep:
                raise ValueError(f"{file_path} 的 episode[{ep_idx}] 缺少字段 '{key}'")

        obs = ep["observations"]         # uint8, [T,4,84,84]
        actions = ep["actions"]          # int64, [T]
        rtg = ep["returns_to_go"]        # float32, [T]
        timesteps = ep["timesteps"]      # int32/int64, [T]

        T = int(len(actions))
        if T <= 0:
            raise RuntimeError(f"{file_path} 的 episode[{ep_idx}] 长度为 0")

        # 随机起点 si ∈ [0, T-1]
        si = int(np.random.randint(0, max(1, T)))
        end = min(si + self.context_len, T)
        L = end - si
        if L <= 0:
            raise RuntimeError(f"非法切片长度: si={si}, end={end}, T={T}")

        # 截取子序列
        obs_slice = np.asarray(obs[si:end], dtype=np.float32) / 255.0
        act_slice = np.asarray(actions[si:end], dtype=np.int64)
        rtg_slice = np.asarray(rtg[si:end], dtype=np.float32)
        ts_slice = np.asarray(timesteps[si:end], dtype=np.int64)

        # 统一补零到 K
        K = self.context_len
        state_shape = tuple(obs_slice.shape[1:])  # (4,84,84)
        states_pad = np.zeros((K, *state_shape), dtype=np.float32)
        actions_pad = np.zeros((K,), dtype=np.int64)
        rtg_pad = np.zeros((K,), dtype=np.float32)
        ts_pad = np.zeros((K,), dtype=np.int64)
        attention_mask = np.zeros((K,), dtype=np.int64)

        states_pad[:L] = obs_slice
        actions_pad[:L] = act_slice
        rtg_pad[:L] = rtg_slice
        ts_pad[:L] = ts_slice
        attention_mask[:L] = 1

        # 转 torch tensor，并保证 dtype
        states_t = torch.from_numpy(states_pad).to(dtype=torch.float32)
        actions_t = torch.from_numpy(actions_pad).to(dtype=torch.long)
        rtg_t = torch.from_numpy(rtg_pad).to(dtype=torch.float32)
        ts_t = torch.from_numpy(ts_pad).to(dtype=torch.long)
        mask_t = torch.from_numpy(attention_mask).to(dtype=torch.long)

        return states_t, actions_t, rtg_t, ts_t, mask_t


def build_dataloader(
    data_root: str,
    context_len: int,
    batch_size: int = 8,
    num_workers: int = 0,
    cache_size: int = 8,
    shuffle: bool = True,
) -> DataLoader:
    """简单工厂：快速构建 DataLoader。"""
    dataset = MarioDTOfflineDataset(
        data_root=data_root,
        context_len=context_len,
        cache_size=cache_size,
        strict=True,
    )
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
        drop_last=False,
    )
    return loader


def _main():
    """
    简单自检入口：
    1) 构建 Dataset / DataLoader
    2) 拉取一个 batch 并打印 shape 与 dtype
    """
    parser = argparse.ArgumentParser(description="Mario DT Offline Dataset quick test")
    parser.add_argument("--data_root", type=str, required=True, help="pkl 文件目录或单个 pkl 文件路径")
    parser.add_argument("--context_len", type=int, default=64)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--cache_size", type=int, default=8)
    parser.add_argument("--max_batches", type=int, default=1)
    args = parser.parse_args()

    loader = build_dataloader(
        data_root=args.data_root,
        context_len=args.context_len,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        cache_size=args.cache_size,
        shuffle=True,
    )

    print(f"[Dataset] total_weighted_steps={len(loader.dataset)}")
    print(f"[Dataset] num_pkl_files={len(loader.dataset.pkl_files)}")
    print(f"[Dataset] num_episodes={len(loader.dataset.index_map)}")

    for bi, batch in enumerate(loader):
        states, actions, returns_to_go, timesteps, attention_mask = batch
        print(f"[Batch {bi}] states.shape={tuple(states.shape)}, dtype={states.dtype}")
        print(f"[Batch {bi}] actions.shape={tuple(actions.shape)}, dtype={actions.dtype}")
        print(f"[Batch {bi}] rtg.shape={tuple(returns_to_go.shape)}, dtype={returns_to_go.dtype}")
        print(f"[Batch {bi}] timesteps.shape={tuple(timesteps.shape)}, dtype={timesteps.dtype}")
        print(f"[Batch {bi}] mask.shape={tuple(attention_mask.shape)}, dtype={attention_mask.dtype}")
        if bi + 1 >= args.max_batches:
            break


if __name__ == "__main__":
    _main()
