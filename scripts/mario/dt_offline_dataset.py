import pickle
import os
import gc
import torch
import numpy as np
import bisect
from torch.utils.data import Dataset


class MarioDTOfflineDataset(Dataset):
    """
    全量内存加载版（In-Memory Dataset）
    启动时把所有 episode 一次性读进内存，之后 __getitem__ 零磁盘 IO。
    适用场景：数据集 < 可用内存（本项目 38GB 数据，容器 90GB，完全够用）

    相比懒加载版的优势：
    - 训练速度从 IO 瓶颈（166 min/epoch）提升到 GPU 瓶颈（预计 5-15 min/epoch）
    - 无需 shard cache，内存占用可预测，不会 OOM
    - DataLoader worker 之间共享内存（fork），不会多份复制
    """

    def __init__(
        self,
        data_root,
        context_len=64,
        episode_indices=None,   # 供 build_train_val_split 使用
        _prebuilt=None,         # 供 build_train_val_split 复用已加载数据
    ):
        self.context_len = context_len

        if _prebuilt is not None:
            # 复用已加载的数据，不重复读盘
            all_episodes = _prebuilt["episodes"]
            self.state_key = _prebuilt["state_key"]
            self.state_shape = _prebuilt["state_shape"]
            self.needs_squeeze = _prebuilt["needs_squeeze"]
            self.action_vocab_size = _prebuilt["action_vocab_size"]
            self._rtg_cache = _prebuilt["rtg_cache"]
        else:
            all_episodes, meta = self._load_all(data_root)
            self.state_key = meta["state_key"]
            self.state_shape = meta["state_shape"]
            self.needs_squeeze = meta["needs_squeeze"]
            self.action_vocab_size = meta["action_vocab_size"]
            # 预计算所有 episode 的 RTG
            print("⚡ [RTG] 预计算所有 episode 的 returns-to-go...")
            self._rtg_cache = [self._compute_rtg(ep) for ep in all_episodes]
            print("✅ [RTG] 完成")

        # 按 episode_indices 筛选子集
        if episode_indices is None:
            self.episodes = all_episodes
            self.rtgs = self._rtg_cache
        else:
            self.episodes = [all_episodes[i] for i in episode_indices]
            self.rtgs = [self._rtg_cache[i] for i in episode_indices]

        # 前缀和，用于 idx -> (ep_idx, step_idx)
        self.episode_lengths = [len(ep["actions"]) for ep in self.episodes]
        self.cumulative_steps = np.cumsum(self.episode_lengths).tolist()
        self.total_steps = self.cumulative_steps[-1] if self.cumulative_steps else 0

        print(
            f"✅ [Ready] 总步数={self.total_steps}, "
            f"episodes={len(self.episodes)}, "
            f"state_shape={self.state_shape}"
        )

    # ------------------------------------------------------------------
    # 一次性加载所有数据
    # ------------------------------------------------------------------

    @staticmethod
    def _load_all(data_root):
        print(f"📂 [Load] 开始加载所有数据到内存: {data_root}")
        with open(data_root, "rb") as f:
            index_data = pickle.load(f)

        shard_list = index_data.get("shard_files", [])
        if not shard_list:
            raise RuntimeError("❌ 索引文件里没有分片路径")

        # 路径纠偏
        fixed = []
        for p in shard_list:
            if not os.path.exists(p):
                alt = os.path.join(os.path.dirname(data_root), os.path.basename(p))
                p = alt if os.path.exists(alt) else p
            fixed.append(p)
        shard_list = fixed

        all_episodes = []
        meta = None
        n = len(shard_list)

        for i, shard_path in enumerate(shard_list):
            with open(shard_path, "rb") as f:
                shard = pickle.load(f)
            episodes = shard.get("episodes", [])
            all_episodes.extend(episodes)

            if meta is None and episodes:
                meta = MarioDTOfflineDataset._probe_state(episodes[0])

            del shard
            if (i + 1) % 500 == 0:
                gc.collect()
                print(f"  已加载 {i+1}/{n} 个分片，episodes={len(all_episodes)}")

        gc.collect()
        print(f"📦 [Load] 完成，共 {len(all_episodes)} 个 episodes")
        return all_episodes, meta

    @staticmethod
    def _probe_state(first_ep):
        state_key = next(
            (k for k in ["observations", "states", "obs"] if k in first_ep),
            "observations",
        )
        raw_shape = first_ep[state_key][0].shape
        if len(raw_shape) == 4 and raw_shape[0] == 1:
            state_shape = tuple(raw_shape[1:])
            needs_squeeze = True
        else:
            state_shape = tuple(raw_shape)
            needs_squeeze = False
        return {
            "state_key": state_key,
            "state_shape": state_shape,
            "needs_squeeze": needs_squeeze,
            "action_vocab_size": 7,
        }

    @staticmethod
    def _compute_rtg(episode):
        rewards_raw = episode['rewards']
        per_step = np.array(
            [
                float(sum(r)) if isinstance(r, (list, tuple, np.ndarray)) else float(r)
                for r in rewards_raw
            ],
            dtype=np.float32,
        )
        return np.flip(np.cumsum(np.flip(per_step))).copy()

    # ------------------------------------------------------------------
    # Train / Val 划分（只加载一次，两个 dataset 共享内存）
    # ------------------------------------------------------------------

    @classmethod
    def build_train_val_split(
        cls,
        data_root,
        context_len=64,
        val_ratio=0.05,
        seed=42,
    ):
        # 只加载一次
        all_episodes, meta = cls._load_all(data_root)
        print("⚡ [RTG] 预计算所有 episode 的 returns-to-go...")
        rtg_cache = [cls._compute_rtg(ep) for ep in all_episodes]
        print("✅ [RTG] 完成")

        total = len(all_episodes)
        rng = np.random.RandomState(seed)
        idx = np.arange(total)
        rng.shuffle(idx)
        n_val = max(1, int(total * val_ratio))
        val_indices = sorted(idx[:n_val].tolist())
        train_indices = sorted(idx[n_val:].tolist())

        print(
            f"📊 [Split] 总 episodes={total}, "
            f"train={len(train_indices)}, val={len(val_indices)} "
            f"(val_ratio={val_ratio}, seed={seed})"
        )

        prebuilt = {
            "episodes": all_episodes,
            "state_key": meta["state_key"],
            "state_shape": meta["state_shape"],
            "needs_squeeze": meta["needs_squeeze"],
            "action_vocab_size": meta["action_vocab_size"],
            "rtg_cache": rtg_cache,
        }

        train_ds = cls(
            data_root=data_root,
            context_len=context_len,
            episode_indices=train_indices,
            _prebuilt=prebuilt,
        )
        val_ds = cls(
            data_root=data_root,
            context_len=context_len,
            episode_indices=val_indices,
            _prebuilt=prebuilt,
        )
        return train_ds, val_ds

    # ------------------------------------------------------------------
    # Dataset 接口
    # ------------------------------------------------------------------

    def __len__(self):
        return self.total_steps

    def __getitem__(self, idx):
        # 定位 episode 和 step
        ep_idx = bisect.bisect_right(self.cumulative_steps, idx)
        step_idx = idx if ep_idx == 0 else idx - self.cumulative_steps[ep_idx - 1]

        episode = self.episodes[ep_idx]
        rtg_full = self.rtgs[ep_idx]

        start_idx = max(0, step_idx - self.context_len + 1)
        end_idx = step_idx + 1

        s = np.asarray(episode[self.state_key][start_idx:end_idx])
        if self.needs_squeeze and s.ndim == 5:
            s = s.squeeze(1)

        a = np.asarray(episode["actions"][start_idx:end_idx])
        rtw = rtg_full[start_idx:end_idx].astype(np.float32)
        ts = np.arange(start_idx, end_idx)
        mask = np.ones(s.shape[0], dtype=np.float32)

        # 前向 padding
        if s.shape[0] < self.context_len:
            p = self.context_len - s.shape[0]
            s    = np.concatenate([np.zeros((p, *self.state_shape), dtype=s.dtype),   s],    axis=0)
            a    = np.concatenate([np.zeros(p, dtype=a.dtype),                         a],    axis=0)
            rtw  = np.concatenate([np.zeros(p, dtype=np.float32),                      rtw],  axis=0)
            ts   = np.concatenate([np.zeros(p, dtype=ts.dtype),                        ts],   axis=0)
            mask = np.concatenate([np.zeros(p, dtype=np.float32),                      mask], axis=0)

        # uint8 → float32 + 归一化
        s_tensor = torch.from_numpy(s)  # 保持 uint8，不 div 255

        return (
            s_tensor,  # uint8，节省 4 倍传输量
            torch.from_numpy(a).long(),
            torch.from_numpy(rtw).float(),
            torch.from_numpy(ts).long(),
            torch.from_numpy(mask).float(),
        )