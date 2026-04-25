#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import pickle
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

def normalize_cli_path(path: str) -> str:
    return os.path.normpath(path.replace("\\", os.sep).replace("/", os.sep))

def atomic_pickle_dump(obj: Any, output_path: str) -> None:
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    tmp_path = output_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

@dataclass
class Tier:
    name: str
    epsilon_min: float
    epsilon_max: float
    ratio: float
    episodes: int
    output_path: str

def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 100:
        return float(max(values))
    xs = sorted(float(v) for v in values)
    pos = (len(xs) - 1) * (q / 100.0)
    left = int(pos)
    right = min(left + 1, len(xs) - 1)
    frac = pos - left
    return float(xs[left] * (1.0 - frac) + xs[right] * frac)

def discover_collector_script() -> str:
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect_random_level_eps_rollouts.py")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"collector script not found: {script_path}")
    return script_path

def run_tier(script_path: str, args: argparse.Namespace, tier: Tier, tier_seed: int) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        script_path,
        "--ckpt_dir", args.ckpt_dir,
        "--output_path", tier.output_path,
        "--total_episodes", str(tier.episodes),
        "--max_steps", str(args.max_steps),
        "--epsilon_min", str(tier.epsilon_min),
        "--epsilon_max", str(tier.epsilon_max),
        "--seed", str(tier_seed),
        "--min_return", str(args.min_return),
        "--min_length", str(args.min_length),
        "--action_type", args.action_type,
        "--skip", str(args.skip),
        "--num_workers", str(args.num_workers),
        "--min_per_level", str(args.min_per_level),
        "--max_per_level", str(args.max_per_level),
        "--gate_ratio", str(args.gate_ratio),
        "--gate_min_x", str(args.gate_min_x),
        "--gate_max_x", str(args.gate_max_x),
        "--max_silent_steps", str(args.max_silent_steps),
        "--max_stagnant_steps", str(args.max_stagnant_steps),
        "--cap_probe_steps", str(args.cap_probe_steps),
        "--cap_mode", args.cap_mode,
        "--default_cap_x", str(args.default_cap_x),
        "--device", args.device,
        "--ipc_mode", args.ipc_mode,
        "--shard_size", str(args.shard_size),
        "--checkpoint_interval", str(args.checkpoint_interval),
        "--spill_direct_shard", str(args.spill_direct_shard),
        "--compact_direct_shards", str(args.compact_direct_shards),
        "--resume", str(args.resume)
    ]
    if args.spill_dir:
        cmd.extend(["--spill_dir", args.spill_dir])
    if args.fast_start:
        cmd.append("--fast_start")

    print(f"\n[Stratified] Running tier '{tier.name}' with epsilon=[{tier.epsilon_min:.3f},{tier.epsilon_max:.3f}] episodes={tier.episodes}")
    subprocess.run(cmd, check=True)
    with open(tier.output_path, "rb") as f:
        return pickle.load(f)

def make_shard_payload(episodes: List[Dict[str, Any]], shard_index: int) -> Dict[str, Any]:
    return {
        "metadata": {
            "collector_type": "stratified_merge_shard",
            "shard_index": shard_index,
            "episodes_in_shard": len(episodes),
        },
        "episodes": episodes,
        "episode_sources": [],
    }

def collect_tier_sources(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    if not isinstance(obj, dict):
        return sources
    for s in obj.get("episode_sources", []):
        if isinstance(s, dict):
            sources.append(s)
    for sf in obj.get("shard_files", []):
        if not isinstance(sf, str) or not os.path.isfile(sf):
            continue
        try:
            with open(sf, "rb") as f:
                sobj = pickle.load(f)
        except Exception:
            continue
        if isinstance(sobj, dict):
            for s in sobj.get("episode_sources", []):
                if isinstance(s, dict):
                    sources.append(s)
    return sources

def evaluate_tier_quality(args: argparse.Namespace, tier: Tier, obj: Dict[str, Any]) -> Dict[str, Any]:
    skip_failure = bool(int(args.qc_skip_failure_tier))
    if skip_failure and tier.name == "exploratory_failure":
        return {
            "tier": tier.name, "checked": False, "passed": True,
            "reason": "skipped_failure_tier", "episodes": 0, "clear_ratio": 0.0, "p90_x": 0.0
        }

    sources = collect_tier_sources(obj)
    x_positions: List[float] = []
    clears: List[bool] = []
    for s in sources:
        x = float(s.get("max_x_pos", s.get("x_pos", 0.0)))
        x_positions.append(x)
        clears.append(bool(s.get("flag_get", False)))

    n = len(x_positions)
    if n == 0:
        return {
            "tier": tier.name, "checked": True, "passed": False,
            "reason": "no_episode_sources", "episodes": 0, "clear_ratio": 0.0, "p90_x": 0.0
        }

    if tier.name == "expert":
        req_clear = args.qc_expert_min_clear_ratio
        req_p90_x = args.qc_expert_min_p90_x
    elif tier.name == "micro_recovery":
        req_clear = args.qc_micro_min_clear_ratio
        req_p90_x = args.qc_micro_min_p90_x
    else:
        req_clear = args.qc_failure_min_clear_ratio
        req_p90_x = args.qc_failure_min_p90_x

    clear_ratio = float(sum(1 for c in clears if c) / max(1, n))
    p90_x = percentile(x_positions, 90.0)
    passed = (clear_ratio >= req_clear) and (p90_x >= req_p90_x)
    reason = "ok" if passed else "threshold_not_met"

    return {
        "tier": tier.name, "checked": True, "passed": bool(passed), "reason": reason,
        "episodes": n, "clear_ratio": clear_ratio, "p90_x": p90_x,
        "min_clear_ratio_required": float(req_clear), "min_p90_x_required": float(req_p90_x),
    }

def cleanup_single_tier_artifacts(tier: Tier, obj: Dict[str, Any]) -> None:
    try:
        if os.path.isfile(tier.output_path):
            os.remove(tier.output_path)
    except OSError:
        pass
    if isinstance(obj, dict):
        shard_dir = obj.get("shard_dir")
        if isinstance(shard_dir, str) and shard_dir.strip():
            shutil.rmtree(shard_dir, ignore_errors=True)

def merge_tier_outputs(args: argparse.Namespace, tiers: List[Tier], tier_objects: List[Dict[str, Any]], 
                       qc_reports: List[Dict[str, Any]], qc_failed: Dict[str, Any], interrupted: bool) -> Dict[str, Any]:
    output_abs = os.path.abspath(args.output_path)
    base_name = os.path.splitext(os.path.basename(output_abs))[0]
    out_dir = os.path.dirname(output_abs)
    merged_shard_dir = os.path.join(out_dir, f"{base_name}_shards")
    os.makedirs(merged_shard_dir, exist_ok=True)

    merged_shard_files: List[str] = []
    merged_shard_counts: List[int] = []
    total_kept = 0
    shard_index = 0

    preserve_tier_artifacts = bool(args.keep_tier_outputs)
    for tier, obj in zip(tiers, tier_objects):
        shard_files = obj.get("shard_files", []) if isinstance(obj, dict) else []
        if shard_files:
            for src in shard_files:
                if not os.path.isfile(src):
                    continue
                shard_index += 1
                dst = os.path.join(merged_shard_dir, f"episodes_shard_{shard_index:06d}.pkl")
                if preserve_tier_artifacts:
                    shutil.copy2(src, dst)
                else:
                    shutil.move(src, dst)
                with open(dst, "rb") as f:
                    sobj = pickle.load(f)
                cnt = len(sobj.get("episodes", []))
                merged_shard_files.append(dst)
                merged_shard_counts.append(cnt)
                total_kept += cnt
            continue

        episodes = obj.get("episodes", []) if isinstance(obj, dict) else []
        if episodes:
            shard_index += 1
            dst = os.path.join(merged_shard_dir, f"episodes_shard_{shard_index:06d}.pkl")
            atomic_pickle_dump(make_shard_payload(episodes, shard_index), dst)
            cnt = len(episodes)
            merged_shard_files.append(dst)
            merged_shard_counts.append(cnt)
            total_kept += cnt

    tier_runs = []
    for tier, obj in zip(tiers, tier_objects):
        meta = obj.get("metadata", {}) if isinstance(obj, dict) else {}
        tier_runs.append({
            "name": tier.name, "epsilon_min": tier.epsilon_min, "epsilon_max": tier.epsilon_max,
            "ratio": tier.ratio, "episodes_requested": tier.episodes,
            "episodes_kept": int(meta.get("episodes_kept", 0)),
            "interrupted": bool(meta.get("interrupted", False)),
            "output_path": tier.output_path,
        })

    if len(merged_shard_files) == 0:
        shutil.rmtree(merged_shard_dir, ignore_errors=True)
        merged_shard_dir = ""

    merged = {
        "metadata": {
            "collector_type": "stratified_random_level_scheduler",
            "total_episodes_requested": int(args.total_episodes),
            "episodes_kept": int(total_kept),
            "sharded_output": True,
            "shard_count": len(merged_shard_files),
            "ratios": {"expert": args.expert_ratio, "micro_recovery": args.micro_ratio, "exploratory_failure": args.failure_ratio},
            "constraints": {"failure_eps_max_cap": 0.15, "min_length": args.min_length, "min_return": args.min_return},
            "tier_runs": tier_runs,
            "quality_gate": {
                "enabled": bool(not args.disable_qc),
                "skip_failure_tier": bool(int(args.qc_skip_failure_tier)),
                "failed": bool(qc_failed),
                "failed_detail": qc_failed,
                "tier_reports": qc_reports,
            },
            "scheduler_interrupted": bool(interrupted),
            "collection_completed": bool(len(tiers) == 3 and not qc_failed and not interrupted)
        },
        "episodes": [], "episode_sources": [],
        "shard_dir": merged_shard_dir, "shard_files": merged_shard_files, "shard_counts": merged_shard_counts,
    }
    return merged

def main():
    parser = argparse.ArgumentParser(description="Stratified random-level data collection scheduler for DT.")
    parser.add_argument("--ckpt_dir", type=str, default="trained_models")
    parser.add_argument("--output_path", type=str, default="dataset/random_data/stratified_random_level_rollouts.pkl")
    parser.add_argument("--total_episodes", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)

    # Tier ratios
    parser.add_argument("--expert_ratio", type=float, default=0.35)
    parser.add_argument("--micro_ratio", type=float, default=0.45)
    parser.add_argument("--failure_ratio", type=float, default=0.20)

    # Tier epsilons
    parser.add_argument("--expert_epsilon_min", type=float, default=0.0)
    parser.add_argument("--expert_epsilon_max", type=float, default=0.0)
    parser.add_argument("--micro_epsilon_min", type=float, default=0.01)
    parser.add_argument("--micro_epsilon_max", type=float, default=0.05)
    parser.add_argument("--failure_epsilon_min", type=float, default=0.05)
    parser.add_argument("--failure_epsilon_max", type=float, default=0.15)

    # Quality gates (Per-Tier X_Pos Based)
    parser.add_argument("--disable_qc", action="store_true")
    parser.add_argument("--qc_expert_min_clear_ratio", type=float, default=0.20)
    parser.add_argument("--qc_expert_min_p90_x", type=float, default=2800.0)
    parser.add_argument("--qc_micro_min_clear_ratio", type=float, default=0.10)
    parser.add_argument("--qc_micro_min_p90_x", type=float, default=2200.0)
    parser.add_argument("--qc_failure_min_clear_ratio", type=float, default=0.0)
    parser.add_argument("--qc_failure_min_p90_x", type=float, default=1000.0)
    parser.add_argument("--qc_skip_failure_tier", type=int, choices=[0, 1], default=1)

    # Forwarded collector args
    parser.add_argument("--min_length", type=int, default=100)
    parser.add_argument("--min_return", type=float, default=500.0)
    parser.add_argument("--max_steps", type=int, default=4000)
    parser.add_argument("--action_type", type=str, choices=["right", "simple", "complex"], default="simple")
    parser.add_argument("--skip", type=int, default=4)
    parser.add_argument("--num_workers", type=int, default=8)
    parser.add_argument("--min_per_level", type=int, default=0)
    parser.add_argument("--max_per_level", type=int, default=0)
    parser.add_argument("--gate_ratio", type=float, default=0.7)
    parser.add_argument("--gate_min_x", type=int, default=400)
    parser.add_argument("--gate_max_x", type=int, default=3200)
    parser.add_argument("--max_silent_steps", type=int, default=1200)
    parser.add_argument("--max_stagnant_steps", type=int, default=250)
    parser.add_argument("--cap_probe_steps", type=int, default=5000)
    parser.add_argument("--cap_mode", type=str, choices=["full", "fast", "ondemand"], default="ondemand")
    parser.add_argument("--fast_start", action="store_true")
    parser.add_argument("--default_cap_x", type=int, default=3200)
    parser.add_argument("--device", type=str, choices=["cpu", "cuda", "auto"], default="auto")
    parser.add_argument("--ipc_mode", type=str, choices=["auto", "memory", "spill"], default="spill")
    parser.add_argument("--spill_dir", type=str, default="")
    parser.add_argument("--shard_size", type=int, default=64)
    
    # Checkpoint & Recovery
    parser.add_argument("--checkpoint_interval", type=int, default=128)
    parser.add_argument("--spill_direct_shard", type=int, choices=[0, 1], default=0)
    parser.add_argument("--compact_direct_shards", type=int, choices=[0, 1], default=0)
    parser.add_argument("--resume", type=int, choices=[0, 1], default=1)

    # Merge behavior
    parser.add_argument("--keep_tier_outputs", action="store_true")
    args = parser.parse_args()

    args.ckpt_dir = normalize_cli_path(args.ckpt_dir)
    args.output_path = normalize_cli_path(args.output_path)
    if args.spill_dir:
        args.spill_dir = normalize_cli_path(args.spill_dir)

    c1 = int(round(args.total_episodes * args.expert_ratio))
    c2 = int(round(args.total_episodes * args.micro_ratio))
    c3 = args.total_episodes - c1 - c2

    out_abs = os.path.abspath(args.output_path)
    out_dir = os.path.dirname(out_abs)
    base = os.path.splitext(os.path.basename(out_abs))[0]
    tier_dir = os.path.join(out_dir, f"{base}_tiers")
    os.makedirs(tier_dir, exist_ok=True)

    tiers = [
        Tier("expert", args.expert_epsilon_min, args.expert_epsilon_max, args.expert_ratio, c1, os.path.join(tier_dir, f"{base}_tier1_expert.pkl")),
        Tier("micro_recovery", args.micro_epsilon_min, args.micro_epsilon_max, args.micro_ratio, c2, os.path.join(tier_dir, f"{base}_tier2_micro.pkl")),
        Tier("exploratory_failure", args.failure_epsilon_min, args.failure_epsilon_max, args.failure_ratio, c3, os.path.join(tier_dir, f"{base}_tier3_failure.pkl")),
    ]

    script_path = discover_collector_script()
    completed_tiers: List[Tier] = []
    tier_objects: List[Dict[str, Any]] = []
    qc_reports: List[Dict[str, Any]] = []
    qc_failed: Dict[str, Any] = {}
    interrupted = False

    try:
        for i, tier in enumerate(tiers):
            tier_seed = args.seed + i * 100003
            if bool(int(args.resume)) and os.path.isfile(tier.output_path):
                print(f"[Resume] Reusing existing tier output: {tier.output_path}")
                with open(tier.output_path, "rb") as f:
                    obj = pickle.load(f)
            else:
                obj = run_tier(script_path, args, tier, tier_seed)
            qc = evaluate_tier_quality(args, tier, obj)
            qc_reports.append(qc)

            if (not args.disable_qc) and (not qc.get("passed", False)):
                qc_failed = qc
                print(f"[QC STOP] tier={tier.name} failed: clear_ratio={qc.get('clear_ratio', 0.0):.4f}, p90_x={qc.get('p90_x', 0.0):.2f}")
                if not args.keep_tier_outputs:
                    cleanup_single_tier_artifacts(tier, obj)
                break

            completed_tiers.append(tier)
            tier_objects.append(obj)
            
    except KeyboardInterrupt:
        print("\n[Interrupt] Caught KeyboardInterrupt. Gracefully halting and merging completed data...")
        interrupted = True

    if completed_tiers:
        merged = merge_tier_outputs(args, completed_tiers, tier_objects, qc_reports, qc_failed, interrupted)
        atomic_pickle_dump(merged, out_abs)

        if not args.keep_tier_outputs:
            for tier in completed_tiers:
                try:
                    os.remove(tier.output_path)
                except OSError:
                    pass
            for obj in tier_objects:
                if isinstance(obj, dict):
                    shard_dir = obj.get("shard_dir")
                    if isinstance(shard_dir, str) and shard_dir.strip():
                        shutil.rmtree(shard_dir, ignore_errors=True)
            shutil.rmtree(tier_dir, ignore_errors=True)

        print("\n=== Stratified Collection Summary ===")
        for tier, obj in zip(completed_tiers, tier_objects):
            meta = obj.get("metadata", {}) if isinstance(obj, dict) else {}
            kept = int(meta.get("episodes_kept", 0))
            print(f"{tier.name}: eps=[{tier.epsilon_min:.3f},{tier.epsilon_max:.3f}], requested={tier.episodes}, kept={kept}")
        
        if qc_failed:
            print(f"[QC STOP] Failed tier: {qc_failed.get('tier')} ({qc_failed.get('reason')})")
        if interrupted:
            print("[Interrupt] Partial stratified dataset has been merged and saved.")
            
        print(f"Merged output index: {out_abs}")
        print(f"Total episodes kept: {int(merged['metadata']['episodes_kept'])}")
    else:
        print("\n[Exit] No completed tiers to merge.")

if __name__ == "__main__":
    main()
