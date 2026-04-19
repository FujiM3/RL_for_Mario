#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import random
import re
import sys
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


def make_env(env_id: str, action_type: str, skip: int, seed: int):
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
            action = int(policy.deterministic_actions(np.asarray(obs))[0])
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
    global _WORKER_CFG, _POLICY_CACHE
    _WORKER_CFG = cfg
    _POLICY_CACHE = {}
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])


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
    cap_x = int(cfg["level_caps"].get(level_tag, cfg["fallback_cap_x"]))

    gate_low = int(cfg["gate_min_x"])
    gate_high = int(min(cap_x, cfg["gate_max_x"]))
    if gate_high < gate_low:
        gate_low = 0
        gate_high = max(cap_x, 0)
    target_x = rng.randint(gate_low, gate_high) if use_gate and gate_high > 0 else 0

    env = make_env(
        env_id=env_id,
        action_type=cfg["action_type"],
        skip=cfg["skip"],
        seed=cfg["seed"] + task_id,
    )
    policy = _get_worker_policy(model_path)

    obs_buf: List[np.ndarray] = []
    act_buf: List[int] = []
    rew_buf: List[float] = []
    term_buf: List[bool] = []
    trunc_buf: List[bool] = []
    flag_buf: List[bool] = []

    try:
        # Mixed sampling:
        # - gate mode: silent greedy rollout to random target_x, then start recording
        # - full mode: record from timestep 0
        while True:
            out = env.reset()
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

                greedy_action = int(policy.deterministic_actions(np.asarray(obs))[0])
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
        while not done and steps < cfg["max_steps"]:
            greedy_action = int(policy.deterministic_actions(np.asarray(obs))[0])
            if rng.random() < epsilon:
                action = int(env.action_space.sample())
            else:
                action = greedy_action

            next_obs, reward, terminated, truncated, info = unpack_step(env.step(action))
            done = bool(terminated or truncated)

            obs_buf.append(obs_for_storage(np.array(obs).copy()))
            act_buf.append(int(action))
            rew_buf.append(float(reward))
            term_buf.append(bool(terminated))
            trunc_buf.append(bool(truncated))
            flag_buf.append(bool(info.get("flag_get", False)))

            obs = next_obs
            steps += 1

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
        return {
            "episode": episode,
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
    finally:
        env.close()


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
    parser.add_argument("--cap_probe_steps", type=int, default=5000)
    parser.add_argument("--device", type=str, choices=["cpu", "cuda", "auto"], default="auto")
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
    if args.cap_probe_steps <= 0:
        raise ValueError("--cap_probe_steps must be > 0")
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
    device = "cuda" if (args.device == "auto" and torch.cuda.is_available()) else args.device
    if device == "auto":
        device = "cpu"

    print(f"Catalog size: {len(catalog)} levels, workers={args.num_workers}, device={device}")
    print("Estimating per-level x_pos caps with 1 greedy probe per level...")
    level_caps = estimate_level_caps(
        catalog=catalog,
        action_type=args.action_type,
        skip=args.skip,
        max_steps=args.cap_probe_steps,
        seed=args.seed,
        device=device,
    )

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
        "gate_ratio": args.gate_ratio,
        "gate_min_x": args.gate_min_x,
        "gate_max_x": args.gate_max_x,
        "level_caps": level_caps,
        "fallback_cap_x": args.gate_max_x,
        "device": device,
        "expected_act_dim": len(get_action_set(args.action_type)),
    }

    submitted = 0
    accepted_by_level = {lvl: 0 for lvl in levels}
    pending_by_level = {lvl: 0 for lvl in levels}

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

    pbar = tqdm(total=args.total_episodes, desc="Collecting random-level rollouts", dynamic_ncols=True)
    with ProcessPoolExecutor(max_workers=args.num_workers, initializer=worker_init, initargs=(worker_cfg,)) as ex:
        pending = set()
        future_level: Dict[Any, str] = {}
        for _ in range(args.num_workers):
            selected_level = pick_level_for_task()
            if selected_level is None:
                break
            fut = ex.submit(
                collect_one_episode,
                {"task_id": submitted, "level": selected_level},
            )
            pending.add(fut)
            future_level[fut] = selected_level
            pending_by_level[selected_level] += 1
            submitted += 1

        while len(episodes) < args.total_episodes:
            if not pending:
                raise RuntimeError("No schedulable levels left under current min/max per-level constraints.")
            done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done_set:
                assigned_level = future_level.pop(fut)
                pending_by_level[assigned_level] = max(0, pending_by_level[assigned_level] - 1)
                result = fut.result()
                episode = result["episode"]
                src = result["source"]
                lvl = src["level"]
                ep_return = float(src["return"])
                ep_len = int(src["length"])
                ep_clear = bool(src["flag_get"])

                level_stats[lvl]["count"] += 1
                level_stats[lvl]["returns"].append(ep_return)
                level_stats[lvl]["lengths"].append(ep_len)
                if ep_clear:
                    level_stats[lvl]["clear"] += 1

                if ep_return >= args.min_return and ep_len >= args.min_length:
                    level_stats[lvl]["accepted"] += 1
                    accepted_by_level[lvl] += 1
                    episodes.append(episode)
                    episode_sources.append(src)
                    pbar.update(1)
                    pbar.set_postfix(kept=f"{len(episodes)}", lvl=lvl, eps=f"{src['epsilon']:.3f}", gate=src["use_gate"])

                if len(episodes) < args.total_episodes:
                    selected_level = pick_level_for_task()
                    if selected_level is not None:
                        fut = ex.submit(
                            collect_one_episode,
                            {"task_id": submitted, "level": selected_level},
                        )
                        pending.add(fut)
                        future_level[fut] = selected_level
                        pending_by_level[selected_level] += 1
                        submitted += 1
            if len(episodes) >= args.total_episodes:
                for fut in pending:
                    fut.cancel()
                break
    pbar.close()

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
        "cap_probe_steps": args.cap_probe_steps,
        "device": device,
        "catalog_size": len(catalog),
        "episodes_kept": len(episodes),
        "episodes_attempted": submitted,
        "sampling_mix": {"gate_after_xpos": args.gate_ratio, "full_trajectory": 1.0 - args.gate_ratio},
    }

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
    print(f"Episodes kept: {len(payload['episodes'])}")


if __name__ == "__main__":
    main()

