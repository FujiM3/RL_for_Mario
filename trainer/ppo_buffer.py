"""
trainer/ppo_buffer.py

PPO Rollout Buffer，实现 Generalized Advantage Estimation (GAE)。

流程：
  1. collect()  — 存入单步 transition
  2. compute_returns_and_advantages()  — 计算 GAE advantage 和 return
  3. get_minibatches()  — 生成 shuffled minibatch 用于 PPO update
  4. reset()  — 清空 buffer，准备下一轮 rollout

参数对照（以 16 env × 512 steps 为例）：
  总 transition 数 = 16 × 512 = 8192
  minibatch_size   = 512 → 16 个 minibatch / update epoch

数学：
  δ_t  = r_t + γ·V(s_{t+1})·(1-done_t) - V(s_t)
  Â_t  = Σ_{l=0}^{T-t} (γλ)^l · δ_{t+l}
  R_t  = Â_t + V(s_t)
"""

import numpy as np
import torch
from typing import Generator, NamedTuple


# ── 数据结构 ──────────────────────────────────────────────────────────────────

class RolloutBatch(NamedTuple):
    """一个 PPO minibatch，所有张量已在 device 上。"""
    obs:        torch.Tensor    # (B, 4, 84, 84)  uint8
    actions:    torch.Tensor    # (B,)             int64
    log_probs:  torch.Tensor    # (B,)             float32  旧策略 log π(a|s)
    returns:    torch.Tensor    # (B,)             float32  GAE return R_t
    advantages: torch.Tensor    # (B,)             float32  标准化 advantage
    values:     torch.Tensor    # (B,)             float32  旧 critic 的 V(s_t)


# ── Rollout Buffer ─────────────────────────────────────────────────────────────

class RolloutBuffer:
    """
    PPO Rollout Buffer。

    Args:
        rollout_steps:  每轮 rollout 收集多少步（per env）
        num_envs:       并行环境数
        obs_shape:      单帧 obs 形状，默认 (4, 84, 84)
        gamma:          折扣因子 γ
        gae_lambda:     GAE λ
        device:         张量设备（cuda/cpu）
    """

    def __init__(
        self,
        rollout_steps: int = 512,
        num_envs: int = 16,
        obs_shape: tuple = (4, 84, 84),
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        device: str = "cuda",
    ):
        self.rollout_steps = rollout_steps
        self.num_envs = num_envs
        self.obs_shape = obs_shape
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.device = device
        self.total_size = rollout_steps * num_envs

        # 预分配 numpy 数组（避免 Python list append 开销）
        T, N = rollout_steps, num_envs
        self.obs       = np.zeros((T, N, *obs_shape), dtype=np.uint8)
        self.actions   = np.zeros((T, N),              dtype=np.int64)
        self.rewards   = np.zeros((T, N),              dtype=np.float32)
        self.dones     = np.zeros((T, N),              dtype=np.float32)
        self.values    = np.zeros((T, N),              dtype=np.float32)
        self.log_probs = np.zeros((T, N),              dtype=np.float32)

        # 计算后填充
        self._returns    : Optional[np.ndarray] = None
        self._advantages : Optional[np.ndarray] = None

        self._ptr = 0
        self._ready = False

    # ── 数据写入 ──────────────────────────────────────────────────────────────

    def add(
        self,
        obs:       np.ndarray,   # (N, 4, 84, 84)
        actions:   np.ndarray,   # (N,)
        rewards:   np.ndarray,   # (N,)
        dones:     np.ndarray,   # (N,)
        values:    np.ndarray,   # (N,)  detach 后的 CPU numpy
        log_probs: np.ndarray,   # (N,)  detach 后的 CPU numpy
    ) -> None:
        assert self._ptr < self.rollout_steps, (
            "Buffer is full. Call compute_returns_and_advantages() then reset()."
        )
        t = self._ptr
        self.obs[t]       = obs
        self.actions[t]   = actions
        self.rewards[t]   = rewards
        self.dones[t]     = dones.astype(np.float32)
        self.values[t]    = values
        self.log_probs[t] = log_probs
        self._ptr += 1

        if self._ptr == self.rollout_steps:
            self._ready = False   # 需要调用 compute_returns 才能 ready

    @property
    def is_full(self) -> bool:
        return self._ptr == self.rollout_steps

    # ── GAE 计算 ──────────────────────────────────────────────────────────────

    def compute_returns_and_advantages(
        self,
        last_values: np.ndarray,  # (N,)  V(s_T)，用于 bootstrapping
    ) -> None:
        """
        计算 GAE advantage 和 lambda-return。

        必须在 buffer 填满后、调用 get_minibatches() 前执行。

        Args:
            last_values: critic 对最后一个 obs 的估值，用于处理截断 episode。
                         来自 model.get_value(last_obs).detach().cpu().numpy()
        """
        assert self.is_full, "Buffer not full yet, cannot compute returns."

        advantages = np.zeros((self.rollout_steps, self.num_envs), dtype=np.float32)
        last_gae = np.zeros(self.num_envs, dtype=np.float32)

        for t in reversed(range(self.rollout_steps)):
            if t == self.rollout_steps - 1:
                next_non_terminal = 1.0 - self.dones[t]
                next_values = last_values
            else:
                next_non_terminal = 1.0 - self.dones[t]
                next_values = self.values[t + 1]

            # TD error
            delta = (
                self.rewards[t]
                + self.gamma * next_values * next_non_terminal
                - self.values[t]
            )

            # GAE 递推
            last_gae = (
                delta
                + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            )
            advantages[t] = last_gae

        self._advantages = advantages
        self._returns = advantages + self.values
        self._ready = True

    # ── Minibatch 生成 ────────────────────────────────────────────────────────

    def get_minibatches(
        self,
        minibatch_size: int,
        normalize_advantages: bool = True,
    ) -> Generator[RolloutBatch, None, None]:
        """
        生成 shuffled minibatch，供 PPO update 循环使用。

        Args:
            minibatch_size:        每个 minibatch 的样本数
            normalize_advantages:  是否对 advantage 做 batch 级标准化

        Yields:
            RolloutBatch（所有张量在 self.device 上）
        """
        assert self._ready, (
            "Must call compute_returns_and_advantages() before get_minibatches()."
        )

        T, N = self.rollout_steps, self.num_envs

        # (T, N, ...) → (T*N, ...)
        flat_obs       = self.obs.reshape(T * N, *self.obs_shape)
        flat_actions   = self.actions.reshape(T * N)
        flat_log_probs = self.log_probs.reshape(T * N)
        flat_returns   = self._returns.reshape(T * N)
        flat_advantages = self._advantages.reshape(T * N)
        flat_values    = self.values.reshape(T * N)

        # Advantage 标准化（整个 rollout 的 batch 级）
        if normalize_advantages:
            flat_advantages = (
                (flat_advantages - flat_advantages.mean())
                / (flat_advantages.std() + 1e-8)
            )

        # Shuffle & yield
        indices = np.random.permutation(T * N)
        for start in range(0, T * N, minibatch_size):
            idx = indices[start : start + minibatch_size]
            yield RolloutBatch(
                obs        = torch.from_numpy(flat_obs[idx]).to(self.device),
                actions    = torch.from_numpy(flat_actions[idx]).long().to(self.device),
                log_probs  = torch.from_numpy(flat_log_probs[idx]).to(self.device),
                returns    = torch.from_numpy(flat_returns[idx]).to(self.device),
                advantages = torch.from_numpy(flat_advantages[idx]).to(self.device),
                values     = torch.from_numpy(flat_values[idx]).to(self.device),
            )

    # ── 重置 ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """清空 buffer，准备下一轮 rollout。"""
        self._ptr = 0
        self._ready = False
        self._returns = None
        self._advantages = None

    # ── 统计 ──────────────────────────────────────────────────────────────────

    def reward_stats(self) -> dict:
        """返回当前 buffer 内奖励的统计信息（调试用）。"""
        r = self.rewards[:self._ptr]
        return {
            "mean": float(r.mean()),
            "std":  float(r.std()),
            "max":  float(r.max()),
            "min":  float(r.min()),
        }

    def advantage_stats(self) -> dict:
        """返回 advantage 统计（compute_returns 后可用）。"""
        assert self._ready, "Call compute_returns_and_advantages() first."
        a = self._advantages
        return {
            "mean": float(a.mean()),
            "std":  float(a.std()),
            "max":  float(a.max()),
            "min":  float(a.min()),
        }

    def __repr__(self) -> str:
        return (
            f"RolloutBuffer("
            f"steps={self.rollout_steps}, "
            f"envs={self.num_envs}, "
            f"total={self.total_size}, "
            f"ptr={self._ptr}, "
            f"ready={self._ready})"
        )


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    T, N = 8, 4   # 小值方便测试
    buf = RolloutBuffer(rollout_steps=T, num_envs=N, device="cpu")

    print(buf)

    # 填充随机数据
    for t in range(T):
        buf.add(
            obs       = np.random.randint(0, 255, (N, 4, 84, 84), dtype=np.uint8),
            actions   = np.random.randint(0, 7, (N,)),
            rewards   = np.random.randn(N).astype(np.float32),
            dones     = (np.random.rand(N) > 0.9),
            values    = np.random.randn(N).astype(np.float32),
            log_probs = np.random.randn(N).astype(np.float32),
        )

    print(f"Is full: {buf.is_full}")
    print(f"Reward stats: {buf.reward_stats()}")

    last_v = np.random.randn(N).astype(np.float32)
    buf.compute_returns_and_advantages(last_values=last_v)
    print(f"Advantage stats: {buf.advantage_stats()}")

    minibatches = list(buf.get_minibatches(minibatch_size=16))
    print(f"Number of minibatches: {len(minibatches)}")

    mb = minibatches[0]
    print(f"Minibatch obs: {mb.obs.shape} dtype={mb.obs.dtype}")
    print(f"Minibatch actions: {mb.actions.shape}")
    print(f"Minibatch advantages: {mb.advantages[:4]}")