"""
trainer/train_ppo_finetune.py

PPO Fine-tune 主训练循环。

从预训练 DT checkpoint 加载 state_encoder，在真实 Mario 环境里
用 PPO 继续训练，实现通用过关策略。

关键超参：
  num_envs         = 16       并行环境数
  rollout_steps    = 512      每轮每个 env 收集的步数 → 总 8192 transitions
  minibatch_size   = 512      每个 minibatch
  update_epochs    = 4        每轮 rollout 的 PPO update 次数
  encoder_lr       = 1e-5     state_encoder 学习率（慢速微调）
  head_lr          = 3e-4     actor/critic head 学习率
  clip_coef        = 0.1      PPO clip ε（保守，防止破坏预训练特征）
  freeze_encoder_steps = 1e6  前 100 万步冻结 encoder，仅训练 head

运行：
  python trainer/train_ppo_finetune.py
  python trainer/train_ppo_finetune.py --resume trainer/out/ppo_finetune/ckpt_latest.pth
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

# 项目路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from model.model_ppo_actor_critic import ActorCriticPPO
from scripts.mario.mario_vec_env import MarioVecEnv
from scripts.mario.gpu_vec_env import GpuMarioVecEnvStats
from scripts.mario.curriculum import CurriculumScheduler
from trainer.ppo_buffer import RolloutBuffer


# ── 超参配置 ──────────────────────────────────────────────────────────────────

def get_default_config(use_gpu: bool = False) -> dict:
    cfg = {
        # 环境
        "num_envs":            2048 if use_gpu else 16,
        "rollout_steps":       2048,
        "total_timesteps":     10_000_000,   # 50M → 10M（DT预训练已收敛，不需要从零探索）

        # 模型
        "hidden_size":         512,
        "head_hidden":         256,
        "act_dim":             7,

        # 优化器
        "encoder_lr":          1e-5,
        "head_lr":             3e-4,
        "max_grad_norm":       0.5,

        # PPO
        "clip_coef":           0.1,
        "ent_coef":            0.1,    # 0.05 → 0.1，进一步抑制策略过早收敛
        "vf_coef":             0.5,
        "update_epochs":       4,
        "minibatch_size":      512,
        "gamma":               0.99,
        "gae_lambda":          0.95,

        # Encoder 冻结策略
        "freeze_encoder_steps":  1_000_000,   # 前 100 万步冻结 encoder

        # 课程学习 (仅 CPU 模式；GPU 固定 World 1-1)
        "curriculum_threshold":  0.6,
        "curriculum_window":     200,
        "curriculum_min_eps":    500,

        # 路径
        "dt_checkpoint":  "trainer/out/mario_dt_v2/dt_mario_v2_hs512_L6_best.pth",
        "out_dir":        "trainer/out/ppo_finetune",
        "save_interval":  50,      # 每 N 轮 rollout 保存一次
        "log_interval":   1,       # 每轮都打印

        # GPU 模式标志
        "use_gpu": use_gpu,
    }
    return cfg


# ── PPO Update ────────────────────────────────────────────────────────────────

def ppo_update(
    model: ActorCriticPPO,
    optimizer: torch.optim.Optimizer,
    buffer: RolloutBuffer,
    cfg: dict,
    device: str,
) -> dict:
    """
    执行一轮 PPO update（多个 epoch × 多个 minibatch）。

    Returns:
        loss_info: dict，包含各 loss 分量的均值
    """
    pg_losses, value_losses, entropy_losses, total_losses = [], [], [], []
    approx_kls, clip_fracs = [], []

    for _ in range(cfg["update_epochs"]):
        for batch in buffer.get_minibatches(
            minibatch_size=cfg["minibatch_size"],
            normalize_advantages=True,
        ):
            # ── 用新策略重新评估 ────────────────────────────────────────
            _, new_log_prob, entropy, new_value = model.get_action_and_value(
                batch.obs, action=batch.actions
            )

            # ── Policy Loss (clipped surrogate) ─────────────────────────
            log_ratio = new_log_prob - batch.log_probs
            ratio = log_ratio.exp()

            # 检测近似 KL（用于监控，不做 early stopping）
            with torch.no_grad():
                approx_kl = ((ratio - 1) - log_ratio).mean()
                clip_frac = ((ratio - 1.0).abs() > cfg["clip_coef"]).float().mean()

            pg_loss1 = -batch.advantages * ratio
            pg_loss2 = -batch.advantages * torch.clamp(
                ratio, 1.0 - cfg["clip_coef"], 1.0 + cfg["clip_coef"]
            )
            pg_loss = torch.max(pg_loss1, pg_loss2).mean()

            # ── Value Loss (clipped) ─────────────────────────────────────
            value_pred_clipped = batch.values + torch.clamp(
                new_value - batch.values,
                -cfg["clip_coef"],
                cfg["clip_coef"],
            )
            vf_loss1 = F.mse_loss(new_value, batch.returns)
            vf_loss2 = F.mse_loss(value_pred_clipped, batch.returns)
            vf_loss = 0.5 * torch.max(vf_loss1, vf_loss2)

            # ── Entropy Bonus ────────────────────────────────────────────
            entropy_loss = -entropy.mean()

            # ── Total Loss ───────────────────────────────────────────────
            loss = (
                pg_loss
                + cfg["vf_coef"] * vf_loss
                + cfg["ent_coef"] * entropy_loss
            )

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), cfg["max_grad_norm"])
            optimizer.step()

            # 记录
            pg_losses.append(pg_loss.item())
            value_losses.append(vf_loss.item())
            entropy_losses.append(entropy_loss.item())
            total_losses.append(loss.item())
            approx_kls.append(approx_kl.item())
            clip_fracs.append(clip_frac.item())

    return {
        "loss/policy":       np.mean(pg_losses),
        "loss/value":        np.mean(value_losses),
        "loss/entropy":      -np.mean(entropy_losses),   # 正值更好理解
        "loss/total":        np.mean(total_losses),
        "debug/approx_kl":   np.mean(approx_kls),
        "debug/clip_frac":   np.mean(clip_fracs),
    }


# ── Checkpoint ────────────────────────────────────────────────────────────────

def save_checkpoint(
    path: str,
    model: ActorCriticPPO,
    optimizer: torch.optim.Optimizer,
    scheduler: CurriculumScheduler,
    global_step: int,
    rollout_count: int,
    cfg: dict,
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save(
        {
            "model_state_dict":     model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "curriculum_state":     scheduler.state_dict(),
            "global_step":          global_step,
            "rollout_count":        rollout_count,
            "config":               cfg,
        },
        path,
    )


def load_checkpoint(
    path: str,
    model: ActorCriticPPO,
    optimizer: torch.optim.Optimizer,
    scheduler: CurriculumScheduler,
) -> tuple:
    print(f"[PPO] Resuming from: {path}")
    ckpt = torch.load(path, map_location="cpu")
    model.load_state_dict(ckpt["model_state_dict"])
    optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    scheduler.load_state_dict(ckpt["curriculum_state"])
    global_step = ckpt.get("global_step", 0)
    rollout_count = ckpt.get("rollout_count", 0)
    print(f"[PPO] Resumed at global_step={global_step:,}, rollout={rollout_count}")
    return global_step, rollout_count


# ── Logger ────────────────────────────────────────────────────────────────────

class Logger:
    """简单的 JSON Lines 日志器。"""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._f = open(path, "a")

    def log(self, data: dict) -> None:
        self._f.write(json.dumps(data) + "\n")
        self._f.flush()

    def close(self):
        self._f.close()


# ── 主训练循环 ────────────────────────────────────────────────────────────────

def train(args):
    cfg = get_default_config(use_gpu=getattr(args, "use_gpu", False))

    # 命令行参数覆盖
    if args.num_envs:
        cfg["num_envs"] = args.num_envs
    if args.total_timesteps:
        cfg["total_timesteps"] = args.total_timesteps
    if cfg["use_gpu"]:
        cfg["out_dir"] = "trainer/out/ppo_finetune_gpu"

    # ── 设备 ─────────────────────────────────────────────────────────────────
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[PPO] Device: {device}")
    if device == "cuda":
        print(f"[PPO] GPU: {torch.cuda.get_device_name(0)}")
        print(f"[PPO] VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    os.makedirs(cfg["out_dir"], exist_ok=True)
    logger = Logger(os.path.join(cfg["out_dir"], "train_log.jsonl"))

    # ── 模型 ─────────────────────────────────────────────────────────────────
    model = ActorCriticPPO(
        act_dim=cfg["act_dim"],
        hidden_size=cfg["hidden_size"],
        head_hidden=cfg["head_hidden"],
    ).to(device)
    model.count_parameters()

    # 加载 DT 预训练 encoder
    dt_ckpt = os.path.join(ROOT, cfg["dt_checkpoint"])
    if os.path.exists(dt_ckpt):
        model.load_encoder_from_dt(dt_ckpt, device=device)
    else:
        print(f"[PPO] WARNING: DT checkpoint not found at {dt_ckpt}, training from scratch.")

    # 前 freeze_encoder_steps 步冻结 encoder
    model.freeze_encoder(freeze=True)
    encoder_frozen = True

    # ── 优化器 ───────────────────────────────────────────────────────────────
    optimizer = torch.optim.Adam(
        model.get_param_groups(
            encoder_lr=cfg["encoder_lr"],
            head_lr=cfg["head_lr"],
        ),
        eps=1e-5,
    )

    # ── Curriculum & 环境 ─────────────────────────────────────────────────────
    curriculum = CurriculumScheduler(
        advance_threshold=cfg["curriculum_threshold"],
        window_size=cfg["curriculum_window"],
        min_episodes=cfg["curriculum_min_eps"],
    )

    if cfg["use_gpu"]:
        print(f"[PPO] Using GPU environment: GpuMarioVecEnvStats (N={cfg['num_envs']})")
        venv = GpuMarioVecEnvStats(num_envs=cfg["num_envs"])
    else:
        print(f"[PPO] Using CPU environment: MarioVecEnv (N={cfg['num_envs']})")
        venv = MarioVecEnv(
            num_envs=cfg["num_envs"],
            scheduler=curriculum,
        )

    # ── Buffer ───────────────────────────────────────────────────────────────
    buffer = RolloutBuffer(
        rollout_steps=cfg["rollout_steps"],
        num_envs=cfg["num_envs"],
        obs_shape=(4, 84, 84),
        gamma=cfg["gamma"],
        gae_lambda=cfg["gae_lambda"],
        device=device,
    )

    # ── Resume ───────────────────────────────────────────────────────────────
    global_step = 0
    rollout_count = 0

    if args.resume and os.path.exists(args.resume):
        global_step, rollout_count = load_checkpoint(
            args.resume, model, optimizer, curriculum
        )

    # ── 初始 obs ──────────────────────────────────────────────────────────────
    obs = venv.reset()           # (N, 4, 84, 84) uint8

    # ── 训练循环 ──────────────────────────────────────────────────────────────
    total_rollouts = cfg["total_timesteps"] // (cfg["num_envs"] * cfg["rollout_steps"])
    print(f"\n[PPO] Training for {cfg['total_timesteps']:,} steps")
    print(f"[PPO] = {total_rollouts} rollouts × {cfg['num_envs']} envs × {cfg['rollout_steps']} steps\n")

    # 追踪 episode 统计
    episode_rewards = []
    episode_lengths = []
    episode_clears = []

    t_start = time.time()

    for rollout_idx in range(rollout_count, rollout_count + total_rollouts):

        # ── 解冻 encoder ──────────────────────────────────────────────────────
        if encoder_frozen and global_step >= cfg["freeze_encoder_steps"]:
            model.freeze_encoder(freeze=False)
            encoder_frozen = False
            print(f"\n[PPO] Step {global_step:,}: Encoder unfrozen, fine-tuning all params.\n")

        # ── Rollout 收集 ──────────────────────────────────────────────────────
        model.eval()
        buffer.reset()

        for step in range(cfg["rollout_steps"]):
            with torch.no_grad():
                obs_tensor = torch.from_numpy(obs).to(device)
                action, log_prob, _, value = model.get_action_and_value(obs_tensor)

                action_np   = action.cpu().numpy()
                log_prob_np = log_prob.cpu().numpy()
                value_np    = value.cpu().numpy()

            next_obs, rewards, dones, infos = venv.step(action_np)

            # Reward scaling：与 DT 预训练数据对齐（数据集里 reward 已除以 10）
            # 原始 Mario reward 最大约 54，除以 10 → ~5.4，与 dataset 一致
            rewards = rewards / 10.0

            buffer.add(
                obs=obs,
                actions=action_np,
                rewards=rewards,
                dones=dones,
                values=value_np,
                log_probs=log_prob_np,
            )

            obs = next_obs
            global_step += cfg["num_envs"]

            # 收集 episode 统计
            for info in infos:
                ep = info.get("episode")
                if ep is not None:
                    episode_rewards.append(ep["r"])
                    episode_lengths.append(ep["l"])
                    episode_clears.append(int(ep["flag_get"]))

        # ── Bootstrap last value ──────────────────────────────────────────────
        with torch.no_grad():
            last_value = model.get_value(
                torch.from_numpy(obs).to(device)
            ).cpu().numpy()

        buffer.compute_returns_and_advantages(last_values=last_value)

        # ── PPO Update ────────────────────────────────────────────────────────
        model.train()
        loss_info = ppo_update(model, optimizer, buffer, cfg, device)

        # ── 课程调度 (CPU 模式；GPU 模式固定 World 1-1，仅统计 clear rate) ─────
        phase_advanced = curriculum.try_advance() if not cfg["use_gpu"] else False

        # ── 日志 ─────────────────────────────────────────────────────────────
        rollout_count += 1

        if rollout_count % cfg["log_interval"] == 0:
            elapsed = time.time() - t_start
            sps = global_step / elapsed   # steps per second

            mean_ep_ret = np.mean(episode_rewards[-100:]) if episode_rewards else 0.0
            mean_ep_len = np.mean(episode_lengths[-100:]) if episode_lengths else 0.0
            clear_rate  = np.mean(episode_clears[-100:])  if episode_clears else 0.0
            adv_stats   = buffer.advantage_stats()

            log_data = {
                "rollout":           rollout_count,
                "global_step":       global_step,
                "sps":               round(sps, 1),
                "elapsed_h":         round(elapsed / 3600, 2),
                "curriculum_phase":  curriculum.phase,
                "curriculum_rate":   round(curriculum.current_clear_rate, 3),
                "ep_ret_mean":       round(mean_ep_ret, 2),
                "ep_len_mean":       round(mean_ep_len, 1),
                "clear_rate_100ep":  round(clear_rate, 3),
                **{k: round(v, 5) for k, v in loss_info.items()},
                "adv_mean":          round(adv_stats["mean"], 4),
                "adv_std":           round(adv_stats["std"], 4),
                "encoder_frozen":    encoder_frozen,
            }
            logger.log(log_data)

            print(
                f"[{rollout_count:5d}] "
                f"step={global_step/1e6:.2f}M | "
                f"sps={sps:.0f} | "
                f"ep_ret={mean_ep_ret:.1f} | "
                f"clear={clear_rate:.1%} | "
                f"phase={curriculum.phase} | "
                f"pg={loss_info['loss/policy']:.4f} | "
                f"vf={loss_info['loss/value']:.4f} | "
                f"ent={loss_info['loss/entropy']:.3f} | "
                f"kl={loss_info['debug/approx_kl']:.4f}"
            )

        # ── Checkpoint 保存 ───────────────────────────────────────────────────
        if rollout_count % cfg["save_interval"] == 0:
            # latest
            ckpt_latest = os.path.join(cfg["out_dir"], "ckpt_latest.pth")
            save_checkpoint(
                ckpt_latest, model, optimizer, curriculum,
                global_step, rollout_count, cfg
            )
            # milestone
            ckpt_milestone = os.path.join(
                cfg["out_dir"], f"ckpt_step{global_step//1_000_000}M.pth"
            )
            save_checkpoint(
                ckpt_milestone, model, optimizer, curriculum,
                global_step, rollout_count, cfg
            )
            print(f"[PPO] Checkpoint saved: {ckpt_latest}")

        # 课程升阶后立刻保存
        if phase_advanced:
            phase_ckpt = os.path.join(
                cfg["out_dir"], f"ckpt_phase{curriculum.phase}.pth"
            )
            save_checkpoint(
                phase_ckpt, model, optimizer, curriculum,
                global_step, rollout_count, cfg
            )

    # ── 训练结束 ──────────────────────────────────────────────────────────────
    print("\n[PPO] Training complete!")
    final_ckpt = os.path.join(cfg["out_dir"], "ckpt_final.pth")
    save_checkpoint(
        final_ckpt, model, optimizer, curriculum,
        global_step, rollout_count, cfg
    )
    print(f"[PPO] Final checkpoint: {final_ckpt}")
    logger.close()
    venv.close()


# ── 评估（greedy 推理） ────────────────────────────────────────────────────────

def evaluate(args):
    """
    在指定关卡上贪心推理，打印每局 reward 和 flag_get。

    用法：
      python trainer/train_ppo_finetune.py --eval --resume ckpt.pth --world 1 --stage 1
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cfg = get_default_config()

    model = ActorCriticPPO(
        act_dim=cfg["act_dim"],
        hidden_size=cfg["hidden_size"],
        head_hidden=cfg["head_hidden"],
    ).to(device)

    ckpt = torch.load(args.resume, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    print(f"[Eval] Loaded checkpoint: {args.resume}")

    from scripts.mario.mario_vec_env import make_mario_env
    env = make_mario_env(args.world, args.stage)

    n_episodes = getattr(args, "n_episodes", 10)
    rewards, clears = [], []

    for ep in range(n_episodes):
        obs, _ = env.reset()
        total_r = 0.0
        done = False
        while not done:
            obs_t = torch.from_numpy(obs[None]).to(device)
            with torch.no_grad():
                logits, _ = model(obs_t)
            action = logits.argmax(-1).item()
            obs, r, terminated, truncated, info = env.step(action)
            total_r += r
            done = terminated or truncated
        flag = info.get("flag_get", False)
        rewards.append(total_r)
        clears.append(flag)
        print(f"  Episode {ep+1:2d}: reward={total_r:.1f}  flag={flag}")

    print(f"\nMean reward: {np.mean(rewards):.1f}  Clear rate: {np.mean(clears):.1%}")
    env.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPO Fine-tune for Super Mario Bros")
    parser.add_argument("--resume",           type=str, default=None)
    parser.add_argument("--eval",             action="store_true")
    parser.add_argument("--use_gpu",          action="store_true",
                        help="Use GPU-accelerated GpuMarioVecEnv (default: CPU MarioVecEnv)")
    parser.add_argument("--num_envs",         type=int, default=None)
    parser.add_argument("--total_timesteps",  type=int, default=None)
    parser.add_argument("--world",            type=int, default=1)
    parser.add_argument("--stage",            type=int, default=1)
    parser.add_argument("--n_episodes",       type=int, default=10)
    args = parser.parse_args()

    if args.eval:
        if not args.resume:
            parser.error("--eval requires --resume <checkpoint_path>")
        evaluate(args)
    else:
        train(args)