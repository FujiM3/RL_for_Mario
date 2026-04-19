#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import atexit
import os
import pickle
import random
import re
import sys
import uuid
import warnings
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from typing import Any, Dict, List, Optional, Tuple

import gym_super_mario_bros
import numpy as np
import torch
from nes_py.wrappers import JoypadSpace
from tqdm import tqdm

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.mario.collect_dt_dataset_from_ppo import (
    BatchedPolicyAdapter,
    CustomRewardWrapper,
    CustomSkipFrameWrapper,
    atomic_pickle_dump,
    compute_returns_to_go,
    get_action_set,
    obs_for_storage,
    validate_episode_shapes,
)

_WORKER_CFG: Dict[str, Any] = {}
_POLICY_CACHE: Dict[str, BatchedPolicyAdapter] = {}
_ENV_CACHE: Dict[str, Any] = {}


def parse_level_from_ckpt_name(name: str) -> Tuple[int, int]:
    m = re.fullmatch(r"ppo_super_mario_bros_(\d+)_(\d+)", name)
    if not m:
        raise ValueError(f"Invalid checkpoint filename: {name}")
    return int(m.group(1)), int(m.group(2))


def discover_models(ckpt_dir: str) -> List[Dict[str, Any]]:
    if not os.path.isdir(ckpt_dir):
        raise FileNotFoundError(f"ckpt_dir not found: {ckpt_dir}")
    catalog: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(ckpt_dir)):
        path = os.path.join(ckpt_dir, fname)
        if not os.path.isfile(path):
            continue
        if not fname.startswith("ppo_super_mario_bros_"):
            continue
        try:
            world, stage = parse_level_from_ckpt_name(fname)
        except ValueError:
            continue
        catalog.append(
            {
                "model_path": path,
                "world": world,
                "stage": stage,
                "level_tag": f"{world}-{stage}",
                "env_id": f"SuperMarioBros-{world}-{stage}-v0",
            }
        )
    if not catalog:
        raise RuntimeError(f"No valid checkpoints found in {ckpt_dir}")
    return catalog


def make_env(env_id: str, action_type: str, skip: int, seed: Optional[int] = None):
    try:
        base_env = gym_super_mario_bros.make(
            env_id,
            apply_api_compatibility=True,
            disable_env_checker=True,
        )
    except TypeError:
        base_env = gym_super_mario_bros.make(env_id)
    if not hasattr(base_env, "render_mode"):
        base_env.render_mode = None

    actions = get_action_set(action_type)
    env = JoypadSpace(base_env, actions)
    m = re.search(r"SuperMarioBros-(\d+)-(\d+)-", env_id)
    world = int(m.group(1)) if m else None
    stage = int(m.group(2)) if m else None
    env = CustomRewardWrapper(env, world=world, stage=stage)
    env = CustomSkipFrameWrapper(env, skip=skip)
    if seed is not None:
        try:
            env.reset(seed=seed)
        except TypeError:
            env.reset()
    return env


def unpack_step(step_out: Tuple[Any, ...]) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
    if len(step_out) == 5:
        obs, reward, terminated, truncated, info = step_out
        return obs, float(reward), bool(terminated), bool(truncated), dict(info)
    if len(step_out) == 4:
        obs, reward, done, info = step_out
        done = bool(done)
        return obs, float(reward), done, False, dict(info)
    raise ValueError(f"Unsupported step output len: {len(step_out)}")


def _get_worker_policy(model_path: str) -> BatchedPolicyAdapter:
    policy = _POLICY_CACHE.get(model_path)
    if policy is not None:
        return policy
    policy = BatchedPolicyAdapter(model_path=model_path, device=_WORKER_CFG["device"])
    if policy.backend == "torch":
        act_dim = int(policy.torch_model.actor_linear.out_features)
        expected = _WORKER_CFG["expected_act_dim"]
        if act_dim != expected:
            raise ValueError(
                f"Action-space mismatch for {model_path}: model outputs {act_dim}, expected {expected}."
            )
    _POLICY_CACHE[model_path] = policy
    return policy


def _close_worker_envs() -> None:
    global _ENV_CACHE
    for env in _ENV_CACHE.values():
        try:
            env.close()
        except Exception:
            pass
    _ENV_CACHE = {}


def _get_worker_env(spec: Dict[str, Any]):
    global _ENV_CACHE
    level_tag = spec["level_tag"]
    env = _ENV_CACHE.get(level_tag)
    if env is not None:
        return env
    env = make_env(
        env_id=spec["env_id"],
        action_type=_WORKER_CFG["action_type"],
        skip=_WORKER_CFG["skip"],
        seed=None,
    )
    _ENV_CACHE[level_tag] = env
    return env


def _reset_env_with_seed(env, seed: int):
    try:
        out = env.reset(seed=seed)
    except TypeError:
        out = env.reset()
    return out


def _deterministic_action(policy: BatchedPolicyAdapter, obs: Any) -> int:
    arr = np.asarray(obs)
    if arr.ndim == 3:
        arr = arr[None, ...]
    return int(policy.deterministic_actions(arr)[0])


def _estimate_single_level_cap(
    spec: Dict[str, Any],
    action_type: str,
    skip: int,
    max_steps: int,
    seed: int,
    device: str,
) -> int:
    env = make_env(spec["env_id"], action_type=action_type, skip=skip, seed=seed)
    policy = BatchedPolicyAdapter(spec["model_path"], device=device)
    try:
        out = env.reset()
        obs = out[0] if isinstance(out, tuple) and len(out) == 2 else out
        max_x = 0
        steps = 0
        while steps < max_steps:
            action = _deterministic_action(policy, obs)
            next_obs, _, terminated, truncated, info = unpack_step(env.step(action))
            x = int(info.get("x_pos", 0))
            if x > max_x:
                max_x = x
            obs = next_obs
            steps += 1
            if terminated or truncated:
                break
        return max_x
    finally:
        env.close()


def estimate_level_caps(
    catalog: List[Dict[str, Any]],
    action_type: str,
    skip: int,
    max_steps: int,
    seed: int,
    device: str,
) -> Dict[str, int]:
    caps: Dict[str, int] = {}
    for i, spec in enumerate(catalog):
        cap = _estimate_single_level_cap(
            spec=spec,
            action_type=action_type,
            skip=skip,
            max_steps=max_steps,
            seed=seed + i,
            device=device,
        )
        caps[spec["level_tag"]] = max(cap, 0)
    return caps


def worker_init(cfg: Dict[str, Any]):
    global _WORKER_CFG, _POLICY_CACHE, _ENV_CACHE
    _WORKER_CFG = cfg
    _POLICY_CACHE = {}
    _ENV_CACHE = {}
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    torch.set_num_threads(1)
    warnings.filterwarnings("ignore", category=UserWarning, message=".*environment .* is out of date.*")
    atexit.register(_close_worker_envs)


def resolve_runtime_device(device_arg: str, num_workers: int) -> str:
    if device_arg == "cpu":
        return "cpu"
    if device_arg == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is False.")
        if num_workers > 1:
            print("[Perf] device=cuda with num_workers>1 may cause GPU contention across worker processes.")
        return "cuda"
    if num_workers > 1:
        print("[Perf] device=auto with multi-process collection -> using CPU workers to avoid GPU contention.")
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def collect_one_episode(task: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _WORKER_CFG
    task_id = int(task["task_id"])
    chosen_level = task.get("level")
    rng = random.Random(cfg["seed"] + task_id * 9973 + os.getpid())

    if chosen_level and chosen_level in cfg["catalog_by_level"]:
        spec = cfg["catalog_by_level"][chosen_level]
    else:
        spec = rng.choice(cfg["catalog"])
    level_tag = spec["level_tag"]
    env_id = spec["env_id"]
    model_path = spec["model_path"]
    epsilon = rng.uniform(cfg["epsilon_min"], cfg["epsilon_max"])
    use_gate = rng.random() < cfg["gate_ratio"]
    cap_x = int(task.get("cap_x", cfg["fallback_cap_x"]))

    gate_low = int(cfg["gate_min_x"])
    gate_high = int(min(cap_x, cfg["gate_max_x"]))
    if gate_high < gate_low:
        gate_low = 0
        gate_high = max(cap_x, 0)
    target_x = rng.randint(gate_low, gate_high) if use_gate and gate_high > 0 else 0

    env = _get_worker_env(spec)
    policy = _get_worker_policy(model_path)

    obs_buf: List[np.ndarray] = []
    act_buf: List[int] = []
    rew_buf: List[float] = []
    term_buf: List[bool] = []
    trunc_buf: List[bool] = []
    flag_buf: List[bool] = []

    # Mixed sampling:
    # - gate mode: silent greedy rollout to random target_x, then start recording
    # - full mode: record from timestep 0
    while True:
        out = _reset_env_with_seed(env, cfg["seed"] + task_id)
        obs, info = out if isinstance(out, tuple) and len(out) == 2 else (out, {})
        if not use_gate:
            start_x = int(info.get("x_pos", 0))
            break

        silent_steps = 0
        start_x = int(info.get("x_pos", 0))
        while True:
            x = int(info.get("x_pos", 0))
            reached = x >= target_x
            timed_out = silent_steps >= cfg["max_silent_steps"]
            if reached or timed_out:
                start_x = x
                break

            greedy_action = _deterministic_action(policy, obs)
            next_obs, _, terminated, truncated, info = unpack_step(env.step(greedy_action))
            obs = next_obs
            silent_steps += 1
            if terminated or truncated:
                # restart silent phase on death during spawn
                break
        if reached or timed_out:
            break

    done = False
    steps = 0
    best_x = int(start_x)
    stagnant_steps = 0
    while not done and steps < cfg["max_steps"]:
        greedy_action = _deterministic_action(policy, obs)
        if rng.random() < epsilon:
            action = int(env.action_space.sample())
        else:
            action = greedy_action

        next_obs, reward, terminated, truncated, info = unpack_step(env.step(action))
        done = bool(terminated or truncated)

        obs_buf.append(obs_for_storage(obs))
        act_buf.append(int(action))
        rew_buf.append(float(reward))
        term_buf.append(bool(terminated))
        trunc_buf.append(bool(truncated))
        flag_buf.append(bool(info.get("flag_get", False)))

        obs = next_obs
        steps += 1

        x = int(info.get("x_pos", best_x))
        if x > best_x:
            best_x = x
            stagnant_steps = 0
        else:
            stagnant_steps += 1
            if stagnant_steps >= cfg["max_stagnant_steps"]:
                done = True
                trunc_buf[-1] = True

    rewards_np = np.asarray(rew_buf, dtype=np.float32)
    episode = {
        "observations": np.asarray(obs_buf, dtype=np.uint8),
        "actions": np.asarray(act_buf, dtype=np.int64),
        "rewards": rewards_np,
        "returns_to_go": compute_returns_to_go(rewards_np),
        "timesteps": np.arange(len(act_buf), dtype=np.int32),
        "terminateds": np.asarray(term_buf, dtype=np.bool_),
        "truncateds": np.asarray(trunc_buf, dtype=np.bool_),
        "flag_gets": np.asarray(flag_buf, dtype=np.bool_),
    }
    validate_episode_shapes(episode)
    ep_return = float(np.sum(episode["rewards"]))
    ep_len = int(len(episode["actions"]))
    ep_clear = bool(np.any(episode["flag_gets"]))
    accepted = bool(ep_return >= cfg["min_return"] and ep_len >= cfg["min_length"])
    result = {
        "accepted": accepted,
        "source": {
            "model_path": model_path,
            "env_id": env_id,
            "level": level_tag,
            "epsilon": float(epsilon),
            "use_gate": bool(use_gate),
            "target_x": int(target_x),
            "start_x": int(start_x),
            "cap_x": int(cap_x),
            "return": ep_return,
            "length": ep_len,
            "flag_get": ep_clear,
        },
    }
    # Only transfer large trajectory arrays across process boundary when the episode is kept.
    if accepted:
        if bool(cfg.get("spill_accepted_episode", False)):
            spill_dir = str(cfg.get("spill_dir", "")).strip()
            if not spill_dir:
                raise RuntimeError("spill_accepted_episode is enabled but spill_dir is empty.")
            os.makedirs(spill_dir, exist_ok=True)
            spill_path = os.path.join(
                spill_dir,
                f"episode_t{task_id:08d}_p{os.getpid()}_{uuid.uuid4().hex[:10]}.pkl",
            )
            atomic_pickle_dump(episode, spill_path)
            result["episode_file"] = spill_path
        else:
            result["episode"] = episode
    return result


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Random level/model epsilon-greedy collector with multiprocessing and mixed x_pos gating: "
            "70% gate-after-random-x, 30% full-trajectory."
        )
    )
    parser.add_argument("--ckpt_dir", type=str, default="PPO_trained_models")
    parser.add_argument("--output_path", type=str, default="dataset\\aligned_greedy\\random_level_eps_rollouts.pkl")
    parser.add_argument("--total_episodes", type=int, default=100)
    parser.add_argument("--max_steps", type=int, default=4000)
    parser.add_argument("--epsilon_min", type=float, default=0.0)
    parser.add_argument("--epsilon_max", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min_return", type=float, default=-1000000.0)
    parser.add_argument("--min_length", type=int, default=1)
    parser.add_argument("--action_type", type=str, choices=["right", "simple", "complex"], default="simple")
    parser.add_argument("--skip", type=int, default=4)
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--min_per_level", type=int, default=0)
    parser.add_argument("--max_per_level", type=int, default=0)
    parser.add_argument("--gate_ratio", type=float, default=0.7)
    parser.add_argument("--gate_min_x", type=int, default=400)
    parser.add_argument("--gate_max_x", type=int, default=3200)
    parser.add_argument("--max_silent_steps", type=int, default=1200)
    parser.add_argument("--max_stagnant_steps", type=int, default=250)
    parser.add_argument("--cap_probe_steps", type=int, default=5000)
    parser.add_argument("--cap_mode", type=str, choices=["full", "fast", "ondemand"], default="ondemand")
    parser.add_argument("--fast_start", action="store_true", help="Skip per-level cap probing and use default_cap_x.")
    parser.add_argument("--default_cap_x", type=int, default=3200)
    parser.add_argument("--device", type=str, choices=["cpu", "cuda", "auto"], default="auto")
    parser.add_argument(
        "--ipc_mode",
        type=str,
        choices=["auto", "memory", "spill"],
        default="auto",
        help="Episode transfer mode between workers and parent process.",
    )
    parser.add_argument(
        "--spill_dir",
        type=str,
        default="",
        help="Directory for temporary spill files when ipc_mode=spill.",
    )
    parser.add_argument(
        "--shard_size",
        type=int,
        default=0,
        help="If >0, write accepted episodes to shard files to reduce memory peak.",
    )
    args = parser.parse_args()

    if args.total_episodes <= 0:
        raise ValueError("--total_episodes must be > 0")
    if args.max_steps <= 0:
        raise ValueError("--max_steps must be > 0")
    if args.skip <= 0:
        raise ValueError("--skip must be > 0")
    if args.num_workers <= 0:
        raise ValueError("--num_workers must be > 0")
    if args.min_per_level < 0:
        raise ValueError("--min_per_level must be >= 0")
    if args.max_per_level < 0:
        raise ValueError("--max_per_level must be >= 0")
    if args.min_length < 1:
        raise ValueError("--min_length must be >= 1")
    if args.max_silent_steps <= 0:
        raise ValueError("--max_silent_steps must be > 0")
    if args.max_stagnant_steps <= 0:
        raise ValueError("--max_stagnant_steps must be > 0")
    if args.cap_probe_steps <= 0:
        raise ValueError("--cap_probe_steps must be > 0")
    if args.default_cap_x <= 0:
        raise ValueError("--default_cap_x must be > 0")
    if args.shard_size < 0:
        raise ValueError("--shard_size must be >= 0")
    if not (0.0 <= args.epsilon_min <= 1.0 and 0.0 <= args.epsilon_max <= 1.0):
        raise ValueError("epsilon_min/epsilon_max must be in [0,1]")
    if args.epsilon_min > args.epsilon_max:
        raise ValueError("epsilon_min must be <= epsilon_max")
    if not (0.0 <= args.gate_ratio <= 1.0):
        raise ValueError("--gate_ratio must be in [0,1]")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    catalog = discover_models(args.ckpt_dir)
    levels = sorted([spec["level_tag"] for spec in catalog])
    if args.min_per_level * len(levels) > args.total_episodes:
        raise ValueError(
            f"min_per_level * level_count exceeds total_episodes: {args.min_per_level} * {len(levels)} > {args.total_episodes}"
        )
    if args.max_per_level > 0 and args.max_per_level * len(levels) < args.total_episodes:
        raise ValueError(
            f"max_per_level * level_count is smaller than total_episodes: {args.max_per_level} * {len(levels)} < {args.total_episodes}"
        )
    if args.max_per_level > 0 and args.min_per_level > args.max_per_level:
        raise ValueError("--min_per_level cannot exceed --max_per_level")
    device = resolve_runtime_device(args.device, args.num_workers)
    ipc_mode = args.ipc_mode
    if ipc_mode == "auto":
        ipc_mode = "spill" if args.num_workers > 1 else "memory"
    if ipc_mode == "spill" and args.num_workers <= 1:
        print("[Perf] ipc_mode=spill ignored in single-worker mode; fallback to memory.")
        ipc_mode = "memory"
    spill_enabled = ipc_mode == "spill"
    spill_dir = ""
    if spill_enabled:
        if args.spill_dir.strip():
            spill_dir = os.path.abspath(args.spill_dir)
        else:
            out_dir = os.path.dirname(os.path.abspath(args.output_path))
            spill_dir = os.path.join(out_dir, f".episode_spill_{uuid.uuid4().hex[:10]}")
        os.makedirs(spill_dir, exist_ok=True)
        print(f"[Perf] worker spill enabled: {spill_dir}")
    use_shards = args.shard_size > 0
    shard_dir = ""
    if use_shards:
        base_name = os.path.splitext(os.path.basename(args.output_path))[0]
        out_dir = os.path.dirname(os.path.abspath(args.output_path))
        shard_dir = os.path.join(out_dir, f"{base_name}_shards")
        os.makedirs(shard_dir, exist_ok=True)
        print(f"[Perf] shard sink enabled: shard_size={args.shard_size}, shard_dir={shard_dir}")

    cap_mode = "fast" if args.fast_start else args.cap_mode
    print(f"Catalog size: {len(catalog)} levels, workers={args.num_workers}, device={device}, cap_mode={cap_mode}")
    spec_by_level = {spec["level_tag"]: spec for spec in catalog}
    if cap_mode == "full":
        print("Estimating per-level x_pos caps with 1 greedy probe per level...")
        level_caps = estimate_level_caps(
            catalog=catalog,
            action_type=args.action_type,
            skip=args.skip,
            max_steps=args.cap_probe_steps,
            seed=args.seed,
            device=device,
        )
    elif cap_mode == "fast":
        print(f"Fast cap mode: skip probing, use default_cap_x={args.default_cap_x}")
        level_caps = {spec["level_tag"]: int(args.default_cap_x) for spec in catalog}
    else:
        print("On-demand cap mode: estimate cap_x only when a level is first sampled.")
        level_caps = {}

    episodes: List[Dict[str, np.ndarray]] = []
    episode_sources: List[Dict[str, Any]] = []
    level_stats = defaultdict(lambda: {"count": 0, "accepted": 0, "clear": 0, "returns": [], "lengths": []})

    worker_cfg = {
        "seed": args.seed,
        "catalog": catalog,
        "catalog_by_level": {spec["level_tag"]: spec for spec in catalog},
        "action_type": args.action_type,
        "skip": args.skip,
        "epsilon_min": args.epsilon_min,
        "epsilon_max": args.epsilon_max,
        "max_steps": args.max_steps,
        "max_silent_steps": args.max_silent_steps,
        "max_stagnant_steps": args.max_stagnant_steps,
        "gate_ratio": args.gate_ratio,
        "gate_min_x": args.gate_min_x,
        "gate_max_x": args.gate_max_x,
        "fallback_cap_x": args.gate_max_x,
        "min_return": float(args.min_return),
        "min_length": int(args.min_length),
        "spill_accepted_episode": spill_enabled,
        "spill_dir": spill_dir,
        "device": device,
        "expected_act_dim": len(get_action_set(args.action_type)),
    }

    submitted = 0
    kept_count = 0
    accepted_by_level = {lvl: 0 for lvl in levels}
    pending_by_level = {lvl: 0 for lvl in levels}
    shard_files: List[str] = []
    shard_counts: List[int] = []
    shard_episode_buf: List[Dict[str, np.ndarray]] = []
    shard_source_buf: List[Dict[str, Any]] = []

    def flush_shard_buffer(force: bool = False) -> None:
        nonlocal shard_episode_buf, shard_source_buf
        if not use_shards:
            return
        if not shard_episode_buf:
            return
        if (not force) and len(shard_episode_buf) < args.shard_size:
            return
        shard_index = len(shard_files) + 1
        shard_path = os.path.join(shard_dir, f"episodes_shard_{shard_index:06d}.pkl")
        shard_payload = {
            "metadata": {
                "collector_type": "random_level_random_epsilon_multiprocess_mixed_gate_shard",
                "shard_index": shard_index,
                "episodes_in_shard": len(shard_episode_buf),
            },
            "episodes": shard_episode_buf,
            "episode_sources": shard_source_buf,
        }
        atomic_pickle_dump(shard_payload, shard_path)
        shard_files.append(shard_path)
        shard_counts.append(len(shard_episode_buf))
        shard_episode_buf = []
        shard_source_buf = []

    def pick_level_for_task() -> Optional[str]:
        eligible = [
            lvl
            for lvl in levels
            if args.max_per_level <= 0 or (accepted_by_level[lvl] + pending_by_level[lvl] < args.max_per_level)
        ]
        if not eligible:
            return None
        if args.min_per_level <= 0:
            return random.choice(eligible)
        deficits = [lvl for lvl in eligible if accepted_by_level[lvl] < args.min_per_level]
        if not deficits:
            return random.choice(eligible)
        min_count = min(accepted_by_level[lvl] + pending_by_level[lvl] for lvl in deficits)
        candidates = [lvl for lvl in deficits if accepted_by_level[lvl] + pending_by_level[lvl] == min_count]
        return random.choice(candidates)

    def get_level_cap(level: str) -> int:
        if level in level_caps:
            return int(level_caps[level])
        if cap_mode == "ondemand":
            cap = _estimate_single_level_cap(
                spec=spec_by_level[level],
                action_type=args.action_type,
                skip=args.skip,
                max_steps=args.cap_probe_steps,
                seed=args.seed + submitted + len(level_caps),
                device=device,
            )
            level_caps[level] = max(int(cap), 0)
            return int(level_caps[level])
        return int(args.default_cap_x)

    def consume_result(result: Dict[str, Any]) -> None:
        nonlocal kept_count
        src = result["source"]
        lvl = src["level"]
        ep_return = float(src["return"])
        ep_len = int(src["length"])
        ep_clear = bool(src["flag_get"])
        accepted = bool(result.get("accepted", False))

        level_stats[lvl]["count"] += 1
        level_stats[lvl]["returns"].append(ep_return)
        level_stats[lvl]["lengths"].append(ep_len)
        if ep_clear:
            level_stats[lvl]["clear"] += 1

        if accepted:
            episode = result.get("episode")
            if episode is None:
                episode_file = result.get("episode_file")
                if episode_file is None:
                    raise RuntimeError("Worker marked accepted episode but did not return payload.")
                with open(episode_file, "rb") as f:
                    episode = pickle.load(f)
                try:
                    os.remove(episode_file)
                except OSError:
                    pass
            level_stats[lvl]["accepted"] += 1
            accepted_by_level[lvl] += 1
            kept_count += 1
            if use_shards:
                shard_episode_buf.append(episode)
                shard_source_buf.append(src)
                flush_shard_buffer(force=False)
            else:
                episodes.append(episode)
                episode_sources.append(src)
            pbar.update(1)
            pbar.set_postfix(kept=f"{kept_count}", lvl=lvl, eps=f"{src['epsilon']:.3f}", gate=src["use_gate"])

    pbar = tqdm(total=args.total_episodes, desc="Collecting random-level rollouts", dynamic_ncols=True)
    if args.num_workers == 1:
        worker_init(worker_cfg)
        while kept_count < args.total_episodes:
            selected_level = pick_level_for_task()
            if selected_level is None:
                raise RuntimeError("No schedulable levels left under current min/max per-level constraints.")
            selected_cap = get_level_cap(selected_level)
            task_id = submitted
            submitted += 1
            pending_by_level[selected_level] += 1
            result = collect_one_episode({"task_id": task_id, "level": selected_level, "cap_x": selected_cap})
            pending_by_level[selected_level] = max(0, pending_by_level[selected_level] - 1)
            consume_result(result)
    else:
        with ProcessPoolExecutor(max_workers=args.num_workers, initializer=worker_init, initargs=(worker_cfg,)) as ex:
            pending = set()
            future_level: Dict[Any, str] = {}
            for _ in range(args.num_workers):
                selected_level = pick_level_for_task()
                if selected_level is None:
                    break
                selected_cap = get_level_cap(selected_level)
                fut = ex.submit(
                    collect_one_episode,
                    {"task_id": submitted, "level": selected_level, "cap_x": selected_cap},
                )
                pending.add(fut)
                future_level[fut] = selected_level
                pending_by_level[selected_level] += 1
                submitted += 1

            while kept_count < args.total_episodes:
                if not pending:
                    raise RuntimeError("No schedulable levels left under current min/max per-level constraints.")
                done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done_set:
                    assigned_level = future_level.pop(fut)
                    pending_by_level[assigned_level] = max(0, pending_by_level[assigned_level] - 1)
                    result = fut.result()
                    consume_result(result)

                    if kept_count < args.total_episodes:
                        selected_level = pick_level_for_task()
                        if selected_level is not None:
                            selected_cap = get_level_cap(selected_level)
                            fut = ex.submit(
                                collect_one_episode,
                                {"task_id": submitted, "level": selected_level, "cap_x": selected_cap},
                            )
                            pending.add(fut)
                            future_level[fut] = selected_level
                            pending_by_level[selected_level] += 1
                            submitted += 1
                if kept_count >= args.total_episodes:
                    for fut in pending:
                        fut.cancel()
                    break
    pbar.close()
    flush_shard_buffer(force=True)
    if spill_enabled:
        try:
            if os.path.isdir(spill_dir):
                for name in os.listdir(spill_dir):
                    path = os.path.join(spill_dir, name)
                    if os.path.isfile(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                if len(os.listdir(spill_dir)) == 0:
                    os.rmdir(spill_dir)
        except OSError:
            pass

    serializable_level_stats: Dict[str, Dict[str, Any]] = {}
    for lvl in sorted(level_stats.keys()):
        s = level_stats[lvl]
        serializable_level_stats[lvl] = {
            "count": int(s["count"]),
            "accepted": int(s["accepted"]),
            "accept_ratio": float(s["accepted"] / max(1, s["count"])),
            "clear_count": int(s["clear"]),
            "clear_ratio": float(s["clear"] / max(1, s["count"])),
            "avg_return": float(np.mean(s["returns"])) if s["returns"] else 0.0,
            "avg_length": float(np.mean(s["lengths"])) if s["lengths"] else 0.0,
        }

    metadata = {
        "collector_type": "random_level_random_epsilon_multiprocess_mixed_gate",
        "ckpt_dir": args.ckpt_dir,
        "total_episodes_requested": args.total_episodes,
        "max_steps": args.max_steps,
        "epsilon_min": args.epsilon_min,
        "epsilon_max": args.epsilon_max,
        "seed": args.seed,
        "min_return": args.min_return,
        "min_length": args.min_length,
        "action_type": args.action_type,
        "skip": args.skip,
        "num_workers": args.num_workers,
        "min_per_level": args.min_per_level,
        "max_per_level": args.max_per_level,
        "gate_ratio": args.gate_ratio,
        "gate_min_x": args.gate_min_x,
        "gate_max_x": args.gate_max_x,
        "max_silent_steps": args.max_silent_steps,
        "max_stagnant_steps": args.max_stagnant_steps,
        "cap_probe_steps": args.cap_probe_steps,
        "cap_mode": cap_mode,
        "fast_start": bool(args.fast_start),
        "default_cap_x": int(args.default_cap_x),
        "device": device,
        "catalog_size": len(catalog),
        "episodes_kept": kept_count,
        "episodes_attempted": submitted,
        "ipc_mode": ipc_mode,
        "spill_enabled": bool(spill_enabled),
        "shard_size": int(args.shard_size),
        "sharded_output": bool(use_shards),
        "shard_count": len(shard_files),
        "sampling_mix": {"gate_after_xpos": args.gate_ratio, "full_trajectory": 1.0 - args.gate_ratio},
    }

    if use_shards:
        payload = {
            "metadata": metadata,
            "episodes": [],
            "episode_sources": [],
            "level_caps": level_caps,
            "level_stats": serializable_level_stats,
            "shard_dir": shard_dir,
            "shard_files": shard_files,
            "shard_counts": shard_counts,
        }
    else:
        payload = {
            "metadata": metadata,
            "episodes": episodes[: args.total_episodes],
            "episode_sources": episode_sources[: args.total_episodes],
            "level_caps": level_caps,
            "level_stats": serializable_level_stats,
        }
    atomic_pickle_dump(payload, args.output_path)

    print("\n=== Level Stats ===")
    for lvl in sorted(serializable_level_stats.keys()):
        s = serializable_level_stats[lvl]
        print(
            f"{lvl}: count={s['count']}, accepted={s['accepted']}, clear={s['clear_count']}, "
            f"clear_ratio={s['clear_ratio']:.3f}, avg_return={s['avg_return']:.2f}, avg_length={s['avg_length']:.2f}"
        )
    print(f"\nSaved dataset to: {args.output_path}")
    if use_shards:
        print(f"Episodes kept: {kept_count}")
        print(f"Shards written: {len(shard_files)}, shard_dir={shard_dir}")
    else:
        print(f"Episodes kept: {len(payload['episodes'])}")


if __name__ == "__main__":
    main()

