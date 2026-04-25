"""
scripts/mario/mario_vec_env.py

Super Mario Bros 向量化并行环境。

包含完整 wrapper 链：
  原始 RGB (240,256,3)
  → JoypadSpace (SIMPLE_MOVEMENT, 7 动作)
  → SkipFrame (×4 帧跳过，累积 reward)
  → GrayScaleObservation (灰度)
  → ResizeObservation (84×84)
  → FrameStack (4 帧堆叠) → (4, 84, 84) uint8
  → StuckPenaltyWrapper (卡住惩罚)

MarioVecEnv 特性：
  - 每局结束后自动 reset 并随机换一个关卡（由 CurriculumScheduler 决定）
  - 支持随时切换课程阶段
  - 同步执行（无 subprocess），在 RTX 5090 + 大内存下已足够快

使用方法:
  from scripts.mario.curriculum import CurriculumScheduler
  scheduler = CurriculumScheduler()
  venv = MarioVecEnv(num_envs=16, scheduler=scheduler)
  obs = venv.reset()                    # (16, 4, 84, 84) uint8
  obs, rew, done, info = venv.step(actions)
  venv.close()
"""

import numpy as np
import cv2
import multiprocessing as mp
from collections import deque
from typing import List, Tuple, Optional, Dict, Any

import gymnasium as gym
import gymnasium
import gym_super_mario_bros
from gym_super_mario_bros.actions import SIMPLE_MOVEMENT
from nes_py.wrappers import JoypadSpace

from scripts.mario.curriculum import CurriculumScheduler


# ── 旧版 gym API 兼容层 ───────────────────────────────────────────────────────
#
# gym-super-mario-bros 7.4.0 + nes_py 8.2.1 使用旧版 gym API：
#   reset() → obs                        （无 info）
#   step()  → (obs, reward, done, info)  （4 值）
#
# gym 0.26.2 的 TimeLimit wrapper 内部期望 5 值，导致解包失败。
# 解法：拿 env.unwrapped 绕开 TimeLimit，在最底层接一个适配器。

class _OldAPIAdapter(gym.Wrapper):
    """
    将 nes_py 裸环境的旧 API 转成新 API：
      reset() → (obs, info)
      step()  → (obs, reward, terminated, truncated, info)
    """

    def reset(self, **kwargs):
        obs = self.env.reset()
        return obs, {}

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        return obs, reward, done, False, info


class _GymToGymnasiumWrapper(gymnasium.Env):
    """
    将 nes_py JoypadSpace（旧版 gym.Env）桥接为 gymnasium.Env。
    让我们的所有 wrapper 能正常套在上面。
    """

    def __init__(self, env):
        self._env = env
        self.observation_space = gymnasium.spaces.Box(
            low=env.observation_space.low,
            high=env.observation_space.high,
            shape=env.observation_space.shape,
            dtype=env.observation_space.dtype,
        )
        self.action_space = gymnasium.spaces.Discrete(env.action_space.n)

    def reset(self, **kwargs):
        obs = self._env.reset()
        if isinstance(obs, tuple):
            return obs[0], {}
        return obs, {}

    def step(self, action):
        result = self._env.step(action)
        if len(result) == 5:
            return result
        obs, reward, done, info = result
        return obs, reward, done, False, info

    def close(self):
        self._env.close()

    def render(self, **kwargs):
        return self._env.render(**kwargs)


# ── 单环境 Wrappers ───────────────────────────────────────────────────────────

class SkipFrame(gym.Wrapper):
    """重复执行同一动作 `skip` 帧，累加 reward。"""

    def __init__(self, env: gym.Env, skip: int = 4):
        super().__init__(env)
        self._skip = skip

    def reset(self, **kwargs):
        return self.env.reset(**kwargs)

    def step(self, action: int):
        total_reward = 0.0
        for _ in range(self._skip):
            obs, reward, terminated, truncated, info = self.env.step(action)
            total_reward += reward
            if terminated or truncated:
                break
        return obs, total_reward, terminated, truncated, info


class GrayScaleObservation(gym.Wrapper):
    """RGB (H, W, 3) → 灰度 (H, W)"""

    def __init__(self, env: gym.Env):
        super().__init__(env)
        h, w = self.observation_space.shape[:2]
        self.observation_space = gym.spaces.Box(
            low=0, high=255, shape=(h, w), dtype=np.uint8
        )

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        return cv2.cvtColor(obs, cv2.COLOR_RGB2GRAY), info

    def step(self, action: int):
        obs, reward, terminated, truncated, info = self.env.step(action)
        return cv2.cvtColor(obs, cv2.COLOR_RGB2GRAY), reward, terminated, truncated, info


class ResizeObservation(gym.Wrapper):
    """(H, W) → (84, 84)，使用 INTER_AREA 下采样。"""

    def __init__(self, env: gym.Env, shape: Tuple[int, int] = (84, 84)):
        super().__init__(env)
        self._shape = shape
        self.observation_space = gym.spaces.Box(
            low=0, high=255, shape=self._shape, dtype=np.uint8
        )

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        return cv2.resize(obs, self._shape[::-1], interpolation=cv2.INTER_AREA), info

    def step(self, action: int):
        obs, reward, terminated, truncated, info = self.env.step(action)
        return cv2.resize(obs, self._shape[::-1], interpolation=cv2.INTER_AREA), reward, terminated, truncated, info


class FrameStack(gym.Wrapper):
    """堆叠最近 k 帧，输出 (k, H, W) uint8。"""

    def __init__(self, env: gym.Env, k: int = 4):
        super().__init__(env)
        self.k = k
        self._frames: deque = deque(maxlen=k)
        h, w = env.observation_space.shape
        self.observation_space = gym.spaces.Box(
            low=0, high=255, shape=(k, h, w), dtype=np.uint8
        )

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        for _ in range(self.k):
            self._frames.append(obs)
        return np.array(self._frames, dtype=np.uint8), info

    def step(self, action: int):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._frames.append(obs)
        return np.array(self._frames, dtype=np.uint8), reward, terminated, truncated, info


class StuckPenaltyWrapper(gym.Wrapper):
    """当 Mario 卡住超过 patience 帧时给予负奖励。"""

    def __init__(self, env: gym.Env, patience: int = 60, penalty: float = -0.3):
        super().__init__(env)
        self._patience = patience
        self._penalty = penalty
        self._last_x: int = 0
        self._stuck_count: int = 0

    def reset(self, **kwargs):
        self._last_x = 0
        self._stuck_count = 0
        return self.env.reset(**kwargs)

    def step(self, action: int):
        obs, reward, terminated, truncated, info = self.env.step(action)
        x = info.get("x_pos", 0)
        if x > self._last_x:
            self._last_x = x
            self._stuck_count = 0
        else:
            self._stuck_count += 1
        if self._stuck_count >= self._patience:
            reward += self._penalty
        return obs, reward, terminated, truncated, info


class EpisodeStatsWrapper(gym.Wrapper):
    """跟踪每局统计，done 时写入 info['episode']。"""

    def __init__(self, env: gym.Env):
        super().__init__(env)
        self._episode_reward = 0.0
        self._episode_length = 0

    def reset(self, **kwargs):
        self._episode_reward = 0.0
        self._episode_length = 0
        return self.env.reset(**kwargs)

    def step(self, action: int):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._episode_reward += reward
        self._episode_length += 1
        if terminated or truncated:
            info["episode"] = {
                "r": self._episode_reward,
                "l": self._episode_length,
                "flag_get": info.get("flag_get", False),
            }
        return obs, reward, terminated, truncated, info


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def make_mario_env(
    world: int,
    stage: int,
    seed: Optional[int] = None,
    stuck_patience: int = 60,
    stuck_penalty: float = -0.3,
) -> gym.Env:
    """
    创建带完整 wrapper 链的单个 Mario 环境。

    Args:
        world, stage:    关卡编号，如 (1, 1) 到 (8, 4)
        seed:            随机种子（可选）
        stuck_patience:  卡住惩罚的判断帧数
        stuck_penalty:   卡住时的奖励惩罚值

    Returns:
        已包装的 gym.Env，obs_space=(4,84,84) uint8，act_space=Discrete(7)
    """
    env_id = f"SuperMarioBros-{world}-{stage}-v3"

    # v3 底层仍然是 nes_py，JoypadSpace 继承自旧版 gym.Env
    # 需要用 GymToGymnasiumWrapper 桥接到 gymnasium.Env
    raw = gym_super_mario_bros.make(env_id, apply_api_compatibility=True)
    joypad = JoypadSpace(raw.unwrapped, SIMPLE_MOVEMENT)
    env = _GymToGymnasiumWrapper(joypad)
    env = SkipFrame(env, skip=4)
    env = GrayScaleObservation(env)
    env = ResizeObservation(env, shape=(84, 84))
    env = FrameStack(env, k=4)
    env = StuckPenaltyWrapper(env, patience=stuck_patience, penalty=stuck_penalty)
    env = EpisodeStatsWrapper(env)

    return env


# ── 向量化环境 ────────────────────────────────────────────────────────────────

# ── Worker 进程函数 ───────────────────────────────────────────────────────────

def _worker(pipe, world: int, stage: int, stuck_patience: int, stuck_penalty: float):
    """
    子进程入口。每个子进程维护一个 Mario env，通过 Pipe 与主进程通信。

    协议：
      主→子  ('step',   action)       → 子→主  (obs, reward, terminated, truncated, info)
      主→子  ('reset',  (world,stage)) → 子→主  obs
      主→子  ('close',  None)          → 子退出
    """
    env = make_mario_env(world, stage, stuck_patience=stuck_patience, stuck_penalty=stuck_penalty)
    obs, _ = env.reset()
    pipe.send(obs)   # 发送初始 obs，通知主进程 worker 就绪

    while True:
        cmd, data = pipe.recv()

        if cmd == 'step':
            obs, reward, terminated, truncated, info = env.step(data)
            pipe.send((obs, reward, terminated, truncated, info))

        elif cmd == 'reset':
            w, s = data
            env.close()
            env = make_mario_env(w, s, stuck_patience=stuck_patience, stuck_penalty=stuck_penalty)
            obs, _ = env.reset()
            pipe.send(obs)

        elif cmd == 'close':
            env.close()
            pipe.close()
            break


# ── 多进程向量化环境 ──────────────────────────────────────────────────────────

class MarioVecEnv:
    """
    多进程向量化 Mario 环境。

    每个 env 运行在独立子进程里，主进程通过 Pipe 并发发送动作、接收结果。
    相比串行版本，速度提升约 num_envs 倍（CPU 瓶颈时接近线性加速）。

    课程调度在主进程侧管理：
      - 子进程上报 done=True 时，主进程记录通关率
      - 主进程采样新关卡，发送 ('reset', (world, stage)) 给子进程

    接口与串行版完全一致：
        obs = venv.reset()                    # (N, 4, 84, 84) uint8
        obs, rew, done, info = venv.step(a)   # a: (N,) int
        venv.close()
    """

    def __init__(
        self,
        num_envs: int = 16,
        scheduler: Optional[CurriculumScheduler] = None,
        stuck_patience: int = 60,
        stuck_penalty: float = -0.3,
    ):
        self.num_envs = num_envs
        self.scheduler = scheduler or CurriculumScheduler()
        self._stuck_patience = stuck_patience
        self._stuck_penalty = stuck_penalty

        # 启动子进程
        self._pipes: List[mp.connection.Connection] = []
        self._procs: List[mp.Process] = []
        self._current_levels: List[Tuple[int, int]] = []

        ctx = mp.get_context('fork')   # fork 比 spawn 快，Linux 下推荐

        init_obs = []
        for i in range(num_envs):
            w, s = self.scheduler.sample_level()
            parent_conn, child_conn = ctx.Pipe()
            proc = ctx.Process(
                target=_worker,
                args=(child_conn, w, s, stuck_patience, stuck_penalty),
                daemon=True,
            )
            proc.start()
            child_conn.close()   # 主进程关闭子端
            self._pipes.append(parent_conn)
            self._procs.append(proc)
            self._current_levels.append((w, s))

        # 等待所有 worker 就绪（收取初始 obs）
        for pipe in self._pipes:
            init_obs.append(pipe.recv())

        # 从临时单环境获取 space 信息
        _tmp = make_mario_env(1, 1)
        self.observation_space = _tmp.observation_space
        self.action_space = _tmp.action_space
        _tmp.close()

        print(
            f"[VecEnv] Created {num_envs} envs (multiprocess) | "
            f"obs: {self.observation_space.shape} | "
            f"act: {self.action_space.n}"
        )

    # ── Core Interface ────────────────────────────────────────────────────────

    def reset(self) -> np.ndarray:
        """重置所有环境，返回 (N, 4, 84, 84) uint8。"""
        for i, pipe in enumerate(self._pipes):
            w, s = self._current_levels[i]
            pipe.send(('reset', (w, s)))
        obs_list = [pipe.recv() for pipe in self._pipes]
        return np.stack(obs_list, axis=0)

    def step(
        self, actions: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        """
        并发发送动作，等待所有子进程返回结果。
        done=True 时自动向对应子进程发送新关卡 reset。

        Returns:
            obs:     (N, 4, 84, 84) uint8
            rewards: (N,) float32
            dones:   (N,) bool
            infos:   list of dict
        """
        # 并发发送动作
        for pipe, a in zip(self._pipes, actions):
            pipe.send(('step', int(a)))

        # 并发接收结果
        results = [pipe.recv() for pipe in self._pipes]

        obs_list = []
        rewards = np.zeros(self.num_envs, dtype=np.float32)
        dones = np.zeros(self.num_envs, dtype=bool)
        infos = []

        for i, (obs, rew, terminated, truncated, info) in enumerate(results):
            done = terminated or truncated
            rewards[i] = rew
            dones[i] = done

            if done:
                # 主进程侧记录通关率
                flag_get = info.get("episode", {}).get("flag_get", False)
                self.scheduler.record_episode(flag_get=flag_get)

                # 采样新关卡，发送 reset 指令给子进程
                w, s = self.scheduler.sample_level()
                self._current_levels[i] = (w, s)
                self._pipes[i].send(('reset', (w, s)))
                obs = self._pipes[i].recv()
                info["new_level"] = (w, s)

            obs_list.append(obs)
            infos.append(info)

        return np.stack(obs_list, axis=0), rewards, dones, infos

    def close(self) -> None:
        for pipe in self._pipes:
            try:
                pipe.send(('close', None))
            except Exception:
                pass
        for proc in self._procs:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
        print(f"[VecEnv] All {self.num_envs} envs closed.")

    def current_levels(self) -> List[Tuple[int, int]]:
        return list(self._current_levels)

    def __len__(self) -> int:
        return self.num_envs

    def __repr__(self) -> str:
        return (
            f"MarioVecEnv(num_envs={self.num_envs}, "
            f"phase={self.scheduler.phase}, "
            f"pool_size={len(self.scheduler.current_pool)})"
        )


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time

    print("Creating VecEnv with 4 envs...")
    scheduler = CurriculumScheduler(window_size=10, min_episodes=5)
    venv = MarioVecEnv(num_envs=4, scheduler=scheduler)

    print(f"obs_space: {venv.observation_space}")
    print(f"act_space: {venv.action_space}")

    obs = venv.reset()
    print(f"\nAfter reset: obs.shape={obs.shape}, dtype={obs.dtype}")

    # 随机跑 200 步
    t0 = time.time()
    total_episodes = 0
    for step in range(200):
        actions = np.array([venv.action_space.sample() for _ in range(4)])
        obs, rewards, dones, infos = venv.step(actions)
        total_episodes += dones.sum()

    elapsed = time.time() - t0
    print(f"\n200 steps × 4 envs in {elapsed:.2f}s ({200*4/elapsed:.0f} steps/s)")
    print(f"Episodes completed: {total_episodes}")
    print(f"Curriculum status: {scheduler.status()}")

    venv.close()