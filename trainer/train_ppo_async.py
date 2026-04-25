"""
trainer/train_ppo_async.py

基于异步 Rollout 的 PPO 训练脚本。

架构：
  32 个 Worker 进程  →  持续采集 rollout，放入队列
  1 个 Learner 主进程 →  从队列取 rollout，做 PPO update，广播新权重

相比同步版本：
  - Worker 和 Learner 完全并行，无互相等待
  - 32 个 Worker × 128 steps = 4096 steps/update（数据量足够）
  - GPU 利用率从 11% 提升到 40%+

速度估算（8470Q 52核 + RTX 5090）：
  Worker 侧：32 进程 × ~25 sps/进程 ≈ 800 steps/sec
  Learner 侧：update 约 5s/次（4096 steps）
  有效 sps：约 600-800 steps/sec（Worker 和 Learner 重叠）
  10M 步总时间：约 3-4 小时

运行：
  python trainer/train_ppo_async.py
  python trainer/train_ppo_async.py --resume trainer/out/ppo_async/ckpt_latest.pth
"""

import os
import sys
import time
import argparse
import json
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from model.model_ppo_actor_critic import ActorCriticPPO
from scripts.mario.async_vec_env import AsyncRolloutCollector, Rollout
from scripts.mario.curriculum import CurriculumScheduler


# ── 超参 ─────────────────────────────────────────────────────────────────────

def get_config() -> dict:
    return {
        # Worker
        "num_workers":         32,      # Worker 进程数，建议 ≤ CPU核心数-4
        "rollout_steps":       128,     # 每个 Worker 每次采集步数（短=低 staleness）
        "rollouts_per_update": 4,       # 攒几个 rollout 才做一次 PPO update
                                        # 实际 batch = 32×128×4 = 16384 steps

        # PPO
        "total_updates":       600,     # 总 update 次数（≈10M步）
        "clip_coef":           0.1,
        "ent_coef":            0.05,
        "vf_coef":             0.5,
        "update_epochs":       4,
        "minibatch_size":      512,
        "gamma":               0.99,
        "gae_lambda":          0.95,
        "max_grad_norm":       0.5,

        # 模型
        "hidden_size":         512,
        "head_hidden":         256,
        "act_dim":             7,

        # 优化器
        "encoder_lr":          1e-5,
        "head_lr":             3e-4,

        # Encoder 冻结
        "freeze_encoder_updates": 100,  # 前 100 次 update 冻结 encoder

        # 课程
        "curriculum_threshold": 0.6,
        "curriculum_window":    200,
        "curriculum_min_eps":   500,

        # 路径
        "dt_checkpoint": "trainer/out/mario_dt_v2/dt_mario_v2_hs512_L6_best.pth",
        "out_dir":       "trainer/out/ppo_async",
        "save_interval": 50,
        "log_interval":  1,
    }


# ── GAE 计算（离线，在 Learner 侧做）────────────────────────────────────────

def compute_gae(
    rewards:    np.ndarray,   # (T,)
    dones:      np.ndarray,   # (T,)
    values:     np.ndarray,   # (T,)
    last_value: float,
    gamma:      float = 0.99,
    gae_lambda: float = 0.95,
):
    T = len(rewards)
    advantages = np.zeros(T, dtype=np.float32)
    last_gae = 0.0

    for t in reversed(range(T)):
        if t == T - 1:
            next_non_terminal = 1.0 - dones[t]
            next_value = last_value
        else:
            next_non_terminal = 1.0 - dones[t]
            next_value = values[t + 1]

        delta = rewards[t] + gamma * next_value * next_non_terminal - values[t]
        last_gae = delta + gamma * gae_lambda * next_non_terminal * last_gae
        advantages[t] = last_gae

    returns = advantages + values
    return advantages, returns


# ── PPO Update ────────────────────────────────────────────────────────────────

def ppo_update(
    model:     ActorCriticPPO,
    optimizer: torch.optim.Optimizer,
    obs:       torch.Tensor,        # (B, 4, 84, 84)
    actions:   torch.Tensor,        # (B,)
    log_probs: torch.Tensor,        # (B,)  旧策略
    returns:   torch.Tensor,        # (B,)
    advantages: torch.Tensor,       # (B,)
    values:    torch.Tensor,        # (B,)  旧 critic
    cfg:       dict,
    device:    str,
) -> dict:
    pg_losses, vf_losses, ent_losses = [], [], []
    approx_kls, clip_fracs = [], []

    # 标准化 advantage
    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    total = len(obs)
    for _ in range(cfg["update_epochs"]):
        indices = torch.randperm(total)
        for start in range(0, total, cfg["minibatch_size"]):
            idx = indices[start: start + cfg["minibatch_size"]]

            _, new_lp, entropy, new_val = model.get_action_and_value(
                obs[idx], action=actions[idx]
            )

            log_ratio = new_lp - log_probs[idx]
            ratio = log_ratio.exp()

            with torch.no_grad():
                approx_kl = ((ratio - 1) - log_ratio).mean()
                clip_frac = ((ratio - 1.0).abs() > cfg["clip_coef"]).float().mean()

            pg1 = -advantages[idx] * ratio
            pg2 = -advantages[idx] * torch.clamp(
                ratio, 1 - cfg["clip_coef"], 1 + cfg["clip_coef"]
            )
            pg_loss = torch.max(pg1, pg2).mean()

            v_clipped = values[idx] + torch.clamp(
                new_val - values[idx], -cfg["clip_coef"], cfg["clip_coef"]
            )
            vf_loss = 0.5 * torch.max(
                F.mse_loss(new_val, returns[idx]),
                F.mse_loss(v_clipped, returns[idx]),
            )

            ent_loss = -entropy.mean()
            loss = pg_loss + cfg["vf_coef"] * vf_loss + cfg["ent_coef"] * ent_loss

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), cfg["max_grad_norm"])
            optimizer.step()

            pg_losses.append(pg_loss.item())
            vf_losses.append(vf_loss.item())
            ent_losses.append(ent_loss.item())
            approx_kls.append(approx_kl.item())
            clip_fracs.append(clip_frac.item())

    return {
        "loss/policy":      np.mean(pg_losses),
        "loss/value":       np.mean(vf_losses),
        "loss/entropy":     -np.mean(ent_losses),
        "debug/approx_kl":  np.mean(approx_kls),
        "debug/clip_frac":  np.mean(clip_fracs),
    }


# ── Rollout 合并 ──────────────────────────────────────────────────────────────

def merge_rollouts(
    rollouts: list,
    model:    ActorCriticPPO,
    cfg:      dict,
    device:   str,
):
    """
    把多个 Rollout 合并，计算 GAE，返回 Tensor。
    """
    all_obs, all_actions, all_log_probs = [], [], []
    all_returns, all_advantages, all_values = [], [], []

    for r in rollouts:
        # bootstrap last value
        with torch.no_grad():
            last_val = model.get_value(
                torch.from_numpy(r.last_obs[None]).to(device)
            ).item()

        adv, ret = compute_gae(
            r.rewards, r.dones, r.values, last_val,
            cfg["gamma"], cfg["gae_lambda"],
        )

        all_obs.append(r.obs)
        all_actions.append(r.actions)
        all_log_probs.append(r.log_probs)
        all_returns.append(ret)
        all_advantages.append(adv)
        all_values.append(r.values)

    obs       = torch.from_numpy(np.concatenate(all_obs)).to(device)
    actions   = torch.from_numpy(np.concatenate(all_actions)).long().to(device)
    log_probs = torch.from_numpy(np.concatenate(all_log_probs)).to(device)
    returns   = torch.from_numpy(np.concatenate(all_returns)).to(device)
    advantages= torch.from_numpy(np.concatenate(all_advantages)).to(device)
    values    = torch.from_numpy(np.concatenate(all_values)).to(device)

    return obs, actions, log_probs, returns, advantages, values


# ── Checkpoint ────────────────────────────────────────────────────────────────

def save_checkpoint(path, model, optimizer, scheduler, update_count, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({
        "model_state_dict":     model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "curriculum_state":     scheduler.state_dict(),
        "update_count":         update_count,
        "config":               cfg,
    }, path)


# ── 主训练循环 ────────────────────────────────────────────────────────────────

def train(args):
    cfg = get_config()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Async PPO] Device: {device}")

    os.makedirs(cfg["out_dir"], exist_ok=True)
    log_path = os.path.join(cfg["out_dir"], "train_log.jsonl")
    log_f = open(log_path, "a")

    # ── 模型 ─────────────────────────────────────────────────────────────────
    model = ActorCriticPPO(
        act_dim=cfg["act_dim"],
        hidden_size=cfg["hidden_size"],
        head_hidden=cfg["head_hidden"],
    ).to(device)
    model.count_parameters()

    dt_ckpt = os.path.join(ROOT, cfg["dt_checkpoint"])
    if os.path.exists(dt_ckpt):
        model.load_encoder_from_dt(dt_ckpt, device=device)
    else:
        print("[Async PPO] WARNING: DT checkpoint not found, training from scratch.")

    model.freeze_encoder(freeze=True)
    encoder_frozen = True

    optimizer = torch.optim.Adam(
        model.get_param_groups(cfg["encoder_lr"], cfg["head_lr"]),
        eps=1e-5,
    )

    # ── 课程 + 异步采集器 ─────────────────────────────────────────────────────
    scheduler = CurriculumScheduler(
        advance_threshold=cfg["curriculum_threshold"],
        window_size=cfg["curriculum_window"],
        min_episodes=cfg["curriculum_min_eps"],
    )

    collector = AsyncRolloutCollector(
        num_workers=cfg["num_workers"],
        rollout_steps=cfg["rollout_steps"],
        scheduler=scheduler,
        hidden_size=cfg["hidden_size"],
        head_hidden=cfg["head_hidden"],
        act_dim=cfg["act_dim"],
    )
    collector.start(model)

    # ── Resume ───────────────────────────────────────────────────────────────
    update_count = 0
    if args.resume and os.path.exists(args.resume):
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        scheduler.load_state_dict(ckpt["curriculum_state"])
        update_count = ckpt.get("update_count", 0)
        collector.update_policy(model)
        print(f"[Async PPO] Resumed at update={update_count}")

    # ── 训练循环 ──────────────────────────────────────────────────────────────
    steps_per_update = cfg["num_workers"] * cfg["rollout_steps"] * cfg["rollouts_per_update"]
    total_steps = steps_per_update * cfg["total_updates"]
    print(f"\n[Async PPO] {cfg['total_updates']} updates × {steps_per_update} steps = {total_steps:,} total steps")
    print(f"[Async PPO] Collecting {cfg['rollouts_per_update']} rollouts per update\n")

    t_start = time.time()
    global_step = update_count * steps_per_update

    for update_idx in range(update_count, cfg["total_updates"]):

        # 解冻 encoder
        if encoder_frozen and update_idx >= cfg["freeze_encoder_updates"]:
            model.freeze_encoder(freeze=False)
            encoder_frozen = False
            print(f"\n[Async PPO] Update {update_idx}: Encoder unfrozen.\n")

        # ── 收集 rollouts ─────────────────────────────────────────────────
        t_collect = time.time()
        rollouts = []
        for _ in range(cfg["rollouts_per_update"]):
            rollout = collector.get_rollout(timeout=120)
            rollouts.append(rollout)
        collect_time = time.time() - t_collect

        # ── 合并 + GAE ────────────────────────────────────────────────────
        model.eval()
        obs, actions, log_probs, returns, advantages, values = merge_rollouts(
            rollouts, model, cfg, device
        )

        # ── PPO Update ────────────────────────────────────────────────────
        model.train()
        t_update = time.time()
        loss_info = ppo_update(
            model, optimizer,
            obs, actions, log_probs, returns, advantages, values,
            cfg, device,
        )
        update_time = time.time() - t_update

        # 广播新权重给 Workers
        collector.update_policy(model)

        update_count += 1
        global_step += steps_per_update
        elapsed = time.time() - t_start
        sps = global_step / elapsed

        # ── 日志 ─────────────────────────────────────────────────────────
        if update_count % cfg["log_interval"] == 0:
            stats = collector.stats()
            log_data = {
                "update":         update_count,
                "global_step":    global_step,
                "sps":            round(sps, 1),
                "elapsed_h":      round(elapsed / 3600, 2),
                "ep_ret":         round(stats["ep_ret"], 1),
                "clear_rate":     round(stats["clear_rate"], 3),
                "total_episodes": stats["total_episodes"],
                "curriculum_phase": scheduler.phase,
                "queue_size":     stats["queue_size"],
                "collect_time":   round(collect_time, 1),
                "update_time":    round(update_time, 1),
                "encoder_frozen": encoder_frozen,
                **{k: round(v, 5) for k, v in loss_info.items()},
            }
            log_f.write(json.dumps(log_data) + "\n")
            log_f.flush()

            print(
                f"[{update_count:4d}] "
                f"step={global_step/1e6:.2f}M | "
                f"sps={sps:.0f} | "
                f"ep_ret={stats['ep_ret']:.1f} | "
                f"clear={stats['clear_rate']:.1%} | "
                f"phase={scheduler.phase} | "
                f"vf={loss_info['loss/value']:.3f} | "
                f"ent={loss_info['loss/entropy']:.3f} | "
                f"collect={collect_time:.1f}s update={update_time:.1f}s"
            )

        # ── Checkpoint ───────────────────────────────────────────────────
        if update_count % cfg["save_interval"] == 0:
            path = os.path.join(cfg["out_dir"], "ckpt_latest.pth")
            save_checkpoint(path, model, optimizer, scheduler, update_count, cfg)
            milestone = os.path.join(cfg["out_dir"], f"ckpt_{global_step//1_000_000}M.pth")
            save_checkpoint(milestone, model, optimizer, scheduler, update_count, cfg)
            print(f"[Async PPO] Saved: {path}")

    # ── 结束 ─────────────────────────────────────────────────────────────────
    final = os.path.join(cfg["out_dir"], "ckpt_final.pth")
    save_checkpoint(final, model, optimizer, scheduler, update_count, cfg)
    print(f"\n[Async PPO] Training complete! Final checkpoint: {final}")
    log_f.close()
    collector.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=str, default=None)
    args = parser.parse_args()
    train(args)