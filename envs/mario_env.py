from collections import deque
import inspect
from typing import Deque, Optional, Tuple

import cv2
import gym_super_mario_bros
import numpy as np
from gym import spaces
from gym_super_mario_bros.actions import SIMPLE_MOVEMENT
from nes_py.wrappers import JoypadSpace


class MarioEnvWrapper:
    def __init__(
        self,
        world: int = 1,
        stage: int = 1,
        version: str = "v3",
        movement=SIMPLE_MOVEMENT,
        frame_skip: int = 4,
        frame_stack: int = 4,
        resize_shape: Tuple[int, int] = (84, 84),
        grayscale: bool = True,
        reward_clip: Optional[Tuple[float, float]] = (-1.0, 1.0),
        render_mode: Optional[str] = None,
    ):
        env_id = f"SuperMarioBros-{world}-{stage}-{version}"
        make_kwargs = {
            "apply_api_compatibility": True,
            "disable_env_checker": True,
        }
        if render_mode is not None:
            make_kwargs["render_mode"] = render_mode
        base_env = gym_super_mario_bros.make(env_id, **make_kwargs)
        self.env = JoypadSpace(base_env, movement)

        self.frame_skip = frame_skip
        self.frame_stack = frame_stack
        self.resize_shape = resize_shape
        self.grayscale = grayscale
        self.reward_clip = reward_clip
        self.frames: Deque[np.ndarray] = deque(maxlen=frame_stack)
        self.action_space = self.env.action_space
        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(frame_stack, resize_shape[1], resize_shape[0]),
            dtype=np.uint8,
        )

    def _preprocess(self, obs: np.ndarray) -> np.ndarray:
        if self.grayscale:
            obs = cv2.cvtColor(obs, cv2.COLOR_RGB2GRAY)
        obs = cv2.resize(obs, self.resize_shape, interpolation=cv2.INTER_AREA)
        if obs.ndim == 3:
            obs = np.transpose(obs, (2, 0, 1))
        else:
            obs = obs[None, ...]
        return obs.astype(np.uint8)

    def _stack_obs(self) -> np.ndarray:
        if len(self.frames) < self.frame_stack:
            first = self.frames[-1]
            while len(self.frames) < self.frame_stack:
                self.frames.appendleft(first.copy())
        return np.concatenate(list(self.frames), axis=0)

    def reset(self, seed: Optional[int] = None):
        if seed is not None and "seed" in inspect.signature(self.env.reset).parameters:
            reset_out = self.env.reset(seed=seed)
        else:
            reset_out = self.env.reset()
        if isinstance(reset_out, tuple):
            obs, info = reset_out
        else:
            obs, info = reset_out, {}
        self.frames.clear()
        frame = self._preprocess(obs)
        for _ in range(self.frame_stack):
            self.frames.append(frame.copy())
        return self._stack_obs(), info

    def step(self, action: int):
        total_reward = 0.0
        info = {}
        terminated = False
        truncated = False
        obs = None
        for _ in range(self.frame_skip):
            out = self.env.step(action)
            if len(out) == 5:
                obs, reward, terminated, truncated, info = out
                done = terminated or truncated
            else:
                obs, reward, done, info = out
                terminated, truncated = done, False
            total_reward += float(reward)
            if done:
                break

        frame = self._preprocess(obs)
        self.frames.append(frame)
        if self.reward_clip is not None:
            total_reward = float(np.clip(total_reward, self.reward_clip[0], self.reward_clip[1]))
        return self._stack_obs(), total_reward, terminated, truncated, info

    def render(self):
        return self.env.render()

    def close(self):
        return self.env.close()
