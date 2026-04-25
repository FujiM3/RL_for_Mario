import os
import sys
import math

__package__ = "trainer"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import time
import warnings
from contextlib import nullcontext

import torch
from torch import optim
from torch.utils.data import DataLoader

from model.model_decision_transformer import DecisionTransformerConfig, MarioDecisionTransformer
from scripts.mario.dt_offline_dataset import MarioDTOfflineDataset

warnings.filterwarnings('ignore')


def Logger(content):
    print(content)


def get_lr(current_step: int, total_steps: int, lr: float, warmup_steps: int = 200) -> float:
    if total_steps <= 0:
        return lr
    # Linear warmup
    if current_step < warmup_steps:
        return lr * max(current_step, 1) / warmup_steps
    # Cosine decay：peak lr → 0.1 * peak lr
    progress = (current_step - warmup_steps) / max(total_steps - warmup_steps, 1)
    return lr * (0.1 + 0.45 * (1.0 + math.cos(math.pi * progress)))


def save_checkpoint(model, optimizer, epoch, step, save_path, extra=None):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    ckpt_tmp = save_path + ".tmp"
    raw_model = model._orig_mod if hasattr(model, "_orig_mod") else model
    payload = {
        "model":     raw_model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "epoch":     epoch,
        "step":      step,
    }
    if extra is not None:
        payload.update(extra)
    torch.save(payload, ckpt_tmp)
    os.replace(ckpt_tmp, save_path)


@torch.no_grad()
def validate(model, val_loader, autocast_ctx, device, max_batches=None):
    """
    在验证集上跑一遍，返回平均 loss
    max_batches=None 表示跑完整个 val_loader；指定数值可限制时间开销
    """
    was_training = model.training
    model.eval()
    total_loss = 0.0
    total_batches = 0
    for step, batch in enumerate(val_loader, start=1):
        if max_batches is not None and step > max_batches:
            break
        states, actions, returns_to_go, timesteps, attention_mask = batch
        states         = states.to(device, non_blocking=True)
        states         = states.float().div_(255.0)  # 在 GPU 上转，快很多
        actions        = actions.to(device, non_blocking=True)
        returns_to_go  = returns_to_go.to(device, non_blocking=True)
        timesteps      = timesteps.to(device, non_blocking=True)
        attention_mask = attention_mask.to(device, non_blocking=True)

        action_targets = actions.clone()
        action_targets = action_targets.masked_fill(attention_mask == 0, -100)

        with autocast_ctx:
            res = model(
                states=states,
                actions=actions,
                returns_to_go=returns_to_go,
                timesteps=timesteps,
                attention_mask=attention_mask,
                action_targets=action_targets,
            )
        total_loss += res.loss.item()
        total_batches += 1

    if was_training:
        model.train()
    return total_loss / max(total_batches, 1)


def train_epoch(epoch, loader, iters):
    model.train()
    start_time = time.time()
    optimizer.zero_grad(set_to_none=True)
    total_steps = args.epochs * iters

    for step, batch in enumerate(loader, start=1):
        states, actions, returns_to_go, timesteps, attention_mask = batch
        states         = states.to(args.device, non_blocking=True)
        actions        = actions.to(args.device, non_blocking=True)
        returns_to_go  = returns_to_go.to(args.device, non_blocking=True)
        timesteps      = timesteps.to(args.device, non_blocking=True)
        attention_mask = attention_mask.to(args.device, non_blocking=True)

        action_targets = actions.clone()
        action_targets = action_targets.masked_fill(attention_mask == 0, -100)

        lr = get_lr(
            (epoch - 1) * iters + step,
            total_steps,
            args.learning_rate,
            warmup_steps=args.warmup_steps,
        )
        for pg in optimizer.param_groups:
            pg["lr"] = lr

        with autocast_ctx:
            res = model(
                states=states,
                actions=actions,
                returns_to_go=returns_to_go,
                timesteps=timesteps,
                attention_mask=attention_mask,
                action_targets=action_targets,
            )
            aux = getattr(res, "aux_loss", None)
            loss = (res.loss + (aux if aux is not None else 0.0)) / args.accumulation_steps

        scaler.scale(loss).backward()

        if step % args.accumulation_steps == 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)

        if step % args.log_interval == 0 or step == iters:
            spend_time = time.time() - start_time
            current_loss = loss.item() * args.accumulation_steps
            eta_min = spend_time / max(step, 1) * iters / 60 - spend_time / 60
            Logger(
                f"Epoch:[{epoch}/{args.epochs}]({step}/{iters}), "
                f"loss:{current_loss:.4f}, lr:{optimizer.param_groups[-1]['lr']:.8f}, "
                f"eta:{eta_min:.1f}min"
            )

        # epoch 内的周期保存（不涉及 val）
        if args.save_interval > 0 and (step % args.save_interval == 0 or step == iters):
            ckpt_name = f"{args.save_weight}_hs{args.hidden_size}_L{args.num_hidden_layers}.pth"
            save_path = os.path.join(args.save_dir, ckpt_name)
            save_checkpoint(model, optimizer, epoch, step, save_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decision Transformer Offline Pretraining")
    parser.add_argument("--data_root",          type=str,   default="dataset/vec_smoke.pkl")
    parser.add_argument("--save_dir",           type=str,   default="out")
    parser.add_argument("--save_weight",        type=str,   default="dt_pretrain")
    parser.add_argument("--epochs",             type=int,   default=1)
    parser.add_argument("--batch_size",         type=int,   default=4)
    parser.add_argument("--learning_rate",      type=float, default=3e-4,
                        help="建议 1e-4 ~ 5e-4；原先默认 8e-4 对 DT 偏高")
    parser.add_argument("--device",             type=str,
                        default="cuda:0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--dtype",              type=str,   default="bfloat16",
                        choices=["float32", "float16", "bfloat16"])
    parser.add_argument("--num_workers",        type=int,   default=4)
    parser.add_argument("--accumulation_steps", type=int,   default=1)
    parser.add_argument("--grad_clip",          type=float, default=1.0)
    parser.add_argument("--log_interval",       type=int,   default=5)
    parser.add_argument("--save_interval",      type=int,   default=50)
    parser.add_argument("--context_len",        type=int,   default=64)
    parser.add_argument("--max_ep_len",         type=int,   default=4096)
    parser.add_argument("--hidden_size",        type=int,   default=256)
    parser.add_argument("--num_hidden_layers",  type=int,   default=4)
    parser.add_argument("--num_attention_heads",type=int,   default=8)
    parser.add_argument("--num_key_value_heads",type=int,   default=2)
    parser.add_argument("--dropout",            type=float, default=0.1)
    parser.add_argument("--cache_size",         type=int,   default=8)
    parser.add_argument("--seed",               type=int,   default=42)
    parser.add_argument("--use_compile",        type=int,   default=0, choices=[0, 1])
    parser.add_argument("--warmup_steps",       type=int,   default=200)

    # ========== 验证集相关参数（新增） ==========
    parser.add_argument("--val_ratio",          type=float, default=0.05,
                        help="按 episode 划分的 val 比例（建议 0.03 ~ 0.05）")
    parser.add_argument("--val_max_batches",    type=int,   default=200,
                        help="每次 val 最多跑多少 batch，避免 val 耗时过长；<=0 表示跑完整个 val set")
    parser.add_argument("--val_batch_size",     type=int,   default=0,
                        help="val 的 batch size；0 表示与 train 相同")
    parser.add_argument("--val_interval_epochs", type=int,  default=1,
                        help="每多少个 epoch 做一次 val，默认每 epoch 一次")
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    os.makedirs(args.save_dir, exist_ok=True)

    # ========== 按 episode 划分 train / val ==========
    train_ds, val_ds = MarioDTOfflineDataset.build_train_val_split(
        data_root=args.data_root,
        context_len=args.context_len,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )

    sample_states, _, _, _, _ = train_ds[0]
    state_shape = tuple(sample_states.shape[1:])
    act_dim = int(getattr(train_ds, "action_vocab_size", 0))
    if act_dim <= 0:
        raise RuntimeError("无法从离线数据推断有效 act_dim，请检查 actions 字段。")

    dt_config = DecisionTransformerConfig(
        state_shape=state_shape,
        act_dim=act_dim,
        max_ep_len=args.max_ep_len,
        context_len=args.context_len,
        hidden_size=args.hidden_size,
        num_hidden_layers=args.num_hidden_layers,
        num_attention_heads=args.num_attention_heads,
        num_key_value_heads=args.num_key_value_heads,
        dropout=args.dropout,
    )
    model = MarioDecisionTransformer(dt_config).to(args.device)

    if args.use_compile == 1 and hasattr(torch, "compile"):
        model = torch.compile(model, mode="reduce-overhead")
        Logger("torch.compile enabled (mode=reduce-overhead)")

    # ========== DataLoaders ==========
    use_multiproc = args.num_workers > 0
    loader = DataLoader(
    train_ds,
    batch_size=args.batch_size,
    shuffle=True,
    num_workers=0,
    pin_memory=True,  # 加这行
    drop_last=True,
    )

    val_bs = args.val_batch_size if args.val_batch_size > 0 else args.batch_size
    val_workers = max(args.num_workers // 2, 1) if use_multiproc else 0
    val_use_multiproc = val_workers > 0
    val_loader = DataLoader(
        val_ds,
        batch_size=val_bs,
        shuffle=False,
        num_workers=val_workers,
        persistent_workers=val_use_multiproc,
        prefetch_factor=(2 if val_use_multiproc else None),
        pin_memory=torch.cuda.is_available(),
        drop_last=False,
    )

    optimizer = optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.01,
    )

    device_type = "cuda" if "cuda" in args.device else "cpu"
    if args.dtype == "float16":
        amp_dtype = torch.float16
    elif args.dtype == "bfloat16":
        amp_dtype = torch.bfloat16
    else:
        amp_dtype = torch.float32

    autocast_ctx = (
        nullcontext()
        if (device_type == "cpu" or amp_dtype == torch.float32)
        else torch.cuda.amp.autocast(dtype=amp_dtype)
    )
    scaler = torch.cuda.amp.GradScaler(
        enabled=(device_type == "cuda" and amp_dtype == torch.float16)
    )

    total_steps = args.epochs * len(loader)
    Logger(f"Train steps={len(train_ds)}, Val steps={len(val_ds)}")
    Logger(f"Batches/epoch: train={len(loader)}, val={len(val_loader)}")
    Logger(f"Total steps: {total_steps}, warmup: {args.warmup_steps}")
    Logger(
        f"DT config: state_shape={state_shape}, act_dim={act_dim}, context_len={args.context_len}, "
        f"hidden={args.hidden_size}, layers={args.num_hidden_layers}"
    )
    Logger(
        f"DataLoader: train_workers={args.num_workers}, val_workers={val_workers}, "
        f"val_batch_size={val_bs}"
    )

    # ========== 训练 + 验证主循环 ==========
    val_max_batches = args.val_max_batches if args.val_max_batches > 0 else None
    best_val_loss = float("inf")
    val_history = []

    for ep in range(1, args.epochs + 1):
        train_epoch(ep, loader, len(loader))

        # 每 val_interval_epochs 跑一次 val（默认每 epoch 一次）
        if ep % args.val_interval_epochs == 0 or ep == args.epochs:
            val_t0 = time.time()
            val_loss = validate(
                model, val_loader, autocast_ctx, args.device,
                max_batches=val_max_batches,
            )
            val_time = time.time() - val_t0
            val_history.append((ep, val_loss))

            batches_used = (
                min(val_max_batches, len(val_loader)) if val_max_batches else len(val_loader)
            )
            Logger(
                f"[Val] Epoch {ep}/{args.epochs}, val_loss={val_loss:.4f}, "
                f"batches={batches_used}, time={val_time:.1f}s"
            )

            # 保存 best checkpoint（基于 val loss）
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_path = os.path.join(
                    args.save_dir,
                    f"{args.save_weight}_hs{args.hidden_size}_L{args.num_hidden_layers}_best.pth",
                )
                save_checkpoint(
                    model, optimizer, ep, len(loader), best_path,
                    extra={"val_loss": val_loss, "best_val_loss": best_val_loss},
                )
                Logger(f"  ✅ best val_loss updated → {val_loss:.4f}, saved to {best_path}")
            else:
                Logger(f"  val_loss {val_loss:.4f} 未优于历史最佳 {best_val_loss:.4f}")

    # ========== 最终保存 ==========
    final_path = os.path.join(args.save_dir, f"{args.save_weight}_final.pth")
    save_checkpoint(
        model, optimizer, args.epochs, len(loader), final_path,
        extra={"best_val_loss": best_val_loss, "val_history": val_history},
    )
    Logger(f"Training finished. Best val_loss={best_val_loss:.4f}")
    Logger(f"Final checkpoint saved: {final_path}")
    if val_history:
        Logger("Val loss history:")
        for ep_i, vl in val_history:
            Logger(f"  epoch {ep_i}: {vl:.4f}")