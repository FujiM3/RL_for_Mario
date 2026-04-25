"""
scripts/mario/async_vec_env.py

异步并行环境，IMPALA 风格。

架构：
  N 个 Worker 进程  →  各自独立运行 env，持续采集 rollout
  1 个 Learner 进程  →  从 Queue 取 rollout，持续做 PPO update

相比同步版本的优势：
  - Worker 采集和 Learner 更新完全重叠，没有互相等待
  - 单个 env 慢不会阻塞其他 env
  - CPU 利用率从约 50% 提升到接近 100%

注意：
  异步架构会引入 "stale policy" 问题（Worker 用旧 policy 采集）
  PPO 对此有一定容忍度（clip 机制），但需要控制 staleness：
    - rollout_steps 不宜过大（默认 128）
    - 每个 Worker 每次只采集短 rollout 就上传

使用方法：
  collector = AsyncRolloutCollector(
      num_workers=32,
      rollout_steps=128,
      scheduler=curriculum,
  )
  collector.start(policy)           # 启动所有 Worker
  rollout = collector.get_rollout() # 阻塞直到有新 rollout
  collector.update_policy(policy)   # 更新 Worker 里的 policy 权重
  collector.close()
"""

import numpy as np
import torch
import torch.multiprocessing as mp
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

# 确保项目根目录在 path 里
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.mario.mario_vec_env import make_mario_env
from scripts.mario.curriculum import CurriculumScheduler


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class Rollout:
    """单个 Worker 采集的一段 rollout。"""
    obs:       np.ndarray   # (T, 4, 84, 84) uint8
    actions:   np.ndarray   # (T,)
    rewards:   np.ndarray   # (T,)
    dones:     np.ndarray   # (T,)
    log_probs: np.ndarray   # (T,)
    values:    np.ndarray   # (T,)
    last_obs:  np.ndarray   # (4, 84, 84) 用于 bootstrap
    worker_id: int
    episode_stats: List[Dict]  # 本段内完成的 episode 统计


# ── Worker 进程 ───────────────────────────────────────────────────────────────

def _async_worker(
    worker_id: int,
    rollout_queue: mp.Queue,
    policy_queue:  mp.Queue,
    level_queue:   mp.Queue,
    error_queue:   mp.Queue,
    rollout_steps: int,
    initial_world: int,
    initial_stage: int,
    stuck_patience: int,
    stuck_penalty:  float,
    hidden_size: int,
    head_hidden: int,
    act_dim: int,
    device: str = "cpu",
):
    try:
        _async_worker_inner(
            worker_id, rollout_queue, policy_queue, level_queue,
            rollout_steps, initial_world, initial_stage,
            stuck_patience, stuck_penalty,
            hidden_size, head_hidden, act_dim, device,
        )
    except Exception as e:
        import traceback
        error_queue.put((worker_id, traceback.format_exc()))


def _async_worker_inner(
    worker_id: int,
    rollout_queue: mp.Queue,
    policy_queue:  mp.Queue,
    level_queue:   mp.Queue,
    rollout_steps: int,
    initial_world: int,
    initial_stage: int,
    stuck_patience: int,
    stuck_penalty:  float,
    hidden_size: int,
    head_hidden: int,
    act_dim: int,
    device: str = "cpu",
):
    """
    Worker 进程主函数。

    流程：
      1. 建立本地 policy（CPU 推理）
      2. 等待 Learner 下发初始权重
      3. 持续采集 rollout → 放入 rollout_queue
      4. 每次上传完 rollout 后，检查 policy_queue 是否有新权重
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    from model.model_ppo_actor_critic import ActorCriticPPO

    # 建立本地 policy（CPU）
    local_policy = ActorCriticPPO(
        act_dim=act_dim,
        hidden_size=hidden_size,
        head_hidden=head_hidden,
    ).to(device)
    local_policy.eval()

    # 等待初始权重
    state_dict = policy_queue.get()
    local_policy.load_state_dict(state_dict)

    # 建立环境
    world, stage = initial_world, initial_stage
    env = make_mario_env(world, stage, stuck_patience=stuck_patience, stuck_penalty=stuck_penalty)
    obs, _ = env.reset()

    while True:
        # ── 采集一段 rollout ──────────────────────────────────────────────
        obs_buf       = np.zeros((rollout_steps, 4, 84, 84), dtype=np.uint8)
        action_buf    = np.zeros(rollout_steps, dtype=np.int64)
        reward_buf    = np.zeros(rollout_steps, dtype=np.float32)
        done_buf      = np.zeros(rollout_steps, dtype=np.float32)
        log_prob_buf  = np.zeros(rollout_steps, dtype=np.float32)
        value_buf     = np.zeros(rollout_steps, dtype=np.float32)
        episode_stats = []

        for t in range(rollout_steps):
            obs_tensor = torch.from_numpy(obs[None]).float() / 255.0
            with torch.no_grad():
                action, log_prob, _, value = local_policy.get_action_and_value(
                    torch.from_numpy(obs[None])
                )

            a = action.item()
            lp = log_prob.item()
            v = value.item()

            next_obs, reward, terminated, truncated, info = env.step(a)
            done = terminated or truncated

            obs_buf[t]      = obs
            action_buf[t]   = a
            reward_buf[t]   = reward / 200.0   # reward scaling
            done_buf[t]     = float(done)
            log_prob_buf[t] = lp
            value_buf[t]    = v

            obs = next_obs

            if done:
                ep = info.get("episode", {})
                if ep:
                    episode_stats.append({
                        "r":        ep.get("r", 0),
                        "l":        ep.get("l", 0),
                        "flag_get": ep.get("flag_get", False),
                    })

                # 检查是否有新关卡指令
                if not level_queue.empty():
                    try:
                        world, stage = level_queue.get_nowait()
                    except Exception:
                        pass

                env.close()
                env = make_mario_env(
                    world, stage,
                    stuck_patience=stuck_patience,
                    stuck_penalty=stuck_penalty,
                )
                obs, _ = env.reset()

        # ── 上传 rollout ──────────────────────────────────────────────────
        rollout = Rollout(
            obs=obs_buf,
            actions=action_buf,
            rewards=reward_buf,
            dones=done_buf,
            log_probs=log_prob_buf,
            values=value_buf,
            last_obs=obs.copy(),
            worker_id=worker_id,
            episode_stats=episode_stats,
        )
        rollout_queue.put(rollout)

        # ── 检查新权重（非阻塞）──────────────────────────────────────────
        while not policy_queue.empty():
            try:
                state_dict = policy_queue.get_nowait()
                local_policy.load_state_dict(state_dict)
            except Exception:
                break


# ── Async Rollout Collector ───────────────────────────────────────────────────

class AsyncRolloutCollector:
    """
    异步 Rollout 采集器。

    管理 N 个 Worker 进程，负责：
      - 启动/关闭 Worker
      - 分发 policy 权重更新
      - 分发课程关卡
      - 从队列中取 rollout 供 Learner 使用

    Args:
        num_workers:    Worker 进程数，建议 = CPU 核心数 - 4
        rollout_steps:  每个 Worker 每次采集的步数（短一些减少 staleness）
        scheduler:      课程调度器，由 Learner 侧维护
        hidden_size:    与主模型一致
        head_hidden:    与主模型一致
        act_dim:        与主模型一致
        queue_maxsize:  rollout 队列最大容量（防止 Worker 生产过快）
    """

    def __init__(
        self,
        num_workers: int = 32,
        rollout_steps: int = 128,
        scheduler: Optional[CurriculumScheduler] = None,
        hidden_size: int = 512,
        head_hidden: int = 256,
        act_dim: int = 7,
        stuck_patience: int = 60,
        stuck_penalty: float = -0.3,
        queue_maxsize: int = 8,
    ):
        self.num_workers = num_workers
        self.rollout_steps = rollout_steps
        self.scheduler = scheduler or CurriculumScheduler()
        self.hidden_size = hidden_size
        self.head_hidden = head_hidden
        self.act_dim = act_dim
        self._stuck_patience = stuck_patience
        self._stuck_penalty = stuck_penalty

        # 队列
        ctx = mp.get_context("spawn")
        self._rollout_queue: mp.Queue = ctx.Queue(maxsize=queue_maxsize)
        self._policy_queues: List[mp.Queue] = [
            ctx.Queue(maxsize=2) for _ in range(num_workers)
        ]
        self._level_queues: List[mp.Queue] = [
            ctx.Queue(maxsize=4) for _ in range(num_workers)
        ]
        self._error_queue: mp.Queue = ctx.Queue()

        self._procs: List[mp.Process] = []
        self._started = False

        # episode 统计
        self.total_episodes = 0
        self.recent_rewards: List[float] = []
        self.recent_clears: List[bool] = []

    def start(self, policy: torch.nn.Module) -> None:
        """启动所有 Worker 进程，分发初始权重。"""
        if self._started:
            return

        ctx = mp.get_context("spawn")
        state_dict = {k: v.cpu() for k, v in policy.state_dict().items()}

        for i in range(self.num_workers):
            w, s = self.scheduler.sample_level()
            proc = ctx.Process(
                target=_async_worker,
                args=(
                    i,
                    self._rollout_queue,
                    self._policy_queues[i],
                    self._level_queues[i],
                    self._error_queue,
                    self.rollout_steps,
                    w, s,
                    self._stuck_patience,
                    self._stuck_penalty,
                    self.hidden_size,
                    self.head_hidden,
                    self.act_dim,
                    "cpu",
                ),
                daemon=True,
            )
            proc.start()
            self._procs.append(proc)
            # 发送初始权重
            self._policy_queues[i].put(state_dict)

        self._started = True
        print(
            f"[AsyncCollector] Started {self.num_workers} workers | "
            f"rollout_steps={self.rollout_steps} | "
            f"total_steps/update≈{self.num_workers * self.rollout_steps}"
        )

    def get_rollout(self, timeout: float = 60.0) -> Rollout:
        """阻塞获取一个 rollout，同时检查 Worker 是否有报错。"""
        # 先检查是否有 worker 崩溃
        if not self._error_queue.empty():
            worker_id, tb = self._error_queue.get()
            raise RuntimeError(f"Worker {worker_id} crashed:\n{tb}")

        try:
            rollout = self._rollout_queue.get(timeout=timeout)
        except Exception:
            # timeout，再检查一次错误队列
            if not self._error_queue.empty():
                worker_id, tb = self._error_queue.get()
                raise RuntimeError(f"Worker {worker_id} crashed:\n{tb}")
            raise RuntimeError(
                f"No rollout received in {timeout}s. "
                f"Check worker logs. Queue size: {self._rollout_queue.qsize()}"
            )

        # 处理 episode 统计
        for ep in rollout.episode_stats:
            self.scheduler.record_episode(flag_get=ep["flag_get"])
            self.recent_rewards.append(ep["r"])
            self.recent_clears.append(ep["flag_get"])
            self.total_episodes += 1

            # 课程升阶：通知对应 worker 换关卡
            if self.scheduler.try_advance():
                self._broadcast_level_update()

        # 保持滑动窗口大小
        if len(self.recent_rewards) > 200:
            self.recent_rewards = self.recent_rewards[-200:]
            self.recent_clears = self.recent_clears[-200:]

        return rollout

    def update_policy(self, policy: torch.nn.Module) -> None:
        """
        向所有 Worker 广播最新 policy 权重。

        非阻塞：如果 Worker 的队列满了就跳过（Worker 会在下次检查时收到）。
        """
        state_dict = {k: v.cpu() for k, v in policy.state_dict().items()}
        for q in self._policy_queues:
            # 清空旧权重，只保留最新的
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
            try:
                q.put_nowait(state_dict)
            except Exception:
                pass

    def _broadcast_level_update(self) -> None:
        """向所有 Worker 广播新关卡（课程升阶后调用）。"""
        for q in self._level_queues:
            w, s = self.scheduler.sample_level()
            try:
                q.put_nowait((w, s))
            except Exception:
                pass

    def stats(self) -> Dict[str, float]:
        """返回最近 episode 的统计。"""
        if not self.recent_rewards:
            return {"ep_ret": 0.0, "clear_rate": 0.0, "total_episodes": 0}
        return {
            "ep_ret":         float(np.mean(self.recent_rewards[-100:])),
            "clear_rate":     float(np.mean(self.recent_clears[-100:])),
            "total_episodes": self.total_episodes,
            "queue_size":     self._rollout_queue.qsize(),
        }

    def close(self) -> None:
        for proc in self._procs:
            proc.terminate()
            proc.join(timeout=3)
        print(f"[AsyncCollector] All {self.num_workers} workers closed.")


# ── 快速测试 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mp.freeze_support()   # spawn 模式必须加这行
    import time
    from model.model_ppo_actor_critic import ActorCriticPPO

    print("Testing AsyncRolloutCollector with 4 workers...")
    policy = ActorCriticPPO()
    scheduler = CurriculumScheduler()

    collector = AsyncRolloutCollector(
        num_workers=4,
        rollout_steps=64,
        scheduler=scheduler,
        queue_maxsize=16,
    )
    collector.start(policy)

    print("Waiting for first rollout (spawn模式首次启动较慢，约30秒)...")
    t0 = time.time()
    total_steps = 0

    for i in range(8):
        rollout = collector.get_rollout(timeout=120)
        total_steps += len(rollout.obs)
        elapsed = time.time() - t0
        print(
            f"Rollout {i+1}: worker={rollout.worker_id} "
            f"steps={len(rollout.obs)} "
            f"sps={total_steps/elapsed:.0f} "
            f"eps={len(rollout.episode_stats)}"
        )

    collector.close()
    print(f"\nTotal: {total_steps} steps in {elapsed:.1f}s = {total_steps/elapsed:.0f} sps")
    print(f"\nTotal: {total_steps} steps in {elapsed:.1f}s = {total_steps/elapsed:.0f} sps")