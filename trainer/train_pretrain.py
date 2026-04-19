import os
import sys

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


def get_lr(current_step, total_steps, lr):
    if total_steps <= 0:
        return lr
    return lr * (0.1 + 0.45 * (1 + torch.cos(torch.tensor(torch.pi * current_step / total_steps)).item()))


def save_checkpoint(model, optimizer, epoch, step, save_path):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    ckpt_tmp = save_path + ".tmp"
    payload = {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "epoch": epoch,
        "step": step,
    }
    torch.save(payload, ckpt_tmp)
    os.replace(ckpt_tmp, save_path)


def train_epoch(epoch, loader, iters):
    model.train()
    start_time = time.time()
    optimizer.zero_grad(set_to_none=True)

    for step, batch in enumerate(loader, start=1):
        states, actions, returns_to_go, timesteps, attention_mask = batch
        states = states.to(args.device, non_blocking=True)
        actions = actions.to(args.device, non_blocking=True)
        returns_to_go = returns_to_go.to(args.device, non_blocking=True)
        timesteps = timesteps.to(args.device, non_blocking=True)
        attention_mask = attention_mask.to(args.device, non_blocking=True)

        action_targets = actions.clone()
        action_targets = action_targets.masked_fill(attention_mask == 0, -100)

        lr = get_lr((epoch - 1) * iters + step, args.epochs * iters, args.learning_rate)
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
            loss = (res.loss + (res.aux_loss if res.aux_loss is not None else 0.0)) / args.accumulation_steps

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

        if (step % args.save_interval == 0 or step == iters):
            ckpt_name = f"{args.save_weight}_hs{args.hidden_size}_L{args.num_hidden_layers}.pth"
            save_path = os.path.join(args.save_dir, ckpt_name)
            save_checkpoint(model, optimizer, epoch, step, save_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decision Transformer Offline Pretraining")
    parser.add_argument("--data_root", type=str, default="dataset\\vec_smoke.pkl", help="离线数据目录或pkl文件")
    parser.add_argument("--save_dir", type=str, default="out", help="模型保存目录")
    parser.add_argument("--save_weight", type=str, default="dt_pretrain", help="保存权重前缀")
    parser.add_argument("--epochs", type=int, default=1, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=4, help="batch size")
    parser.add_argument("--learning_rate", type=float, default=3e-4, help="初始学习率")
    parser.add_argument("--device", type=str, default="cuda:0" if torch.cuda.is_available() else "cpu", help="训练设备")
    parser.add_argument("--dtype", type=str, default="bfloat16", choices=["float32", "float16", "bfloat16"], help="混合精度类型")
    parser.add_argument("--num_workers", type=int, default=0, help="数据加载线程数")
    parser.add_argument("--accumulation_steps", type=int, default=1, help="梯度累积步数")
    parser.add_argument("--grad_clip", type=float, default=1.0, help="梯度裁剪阈值")
    parser.add_argument("--log_interval", type=int, default=5, help="日志打印间隔")
    parser.add_argument("--save_interval", type=int, default=50, help="模型保存间隔")
    parser.add_argument("--context_len", type=int, default=64, help="DT上下文窗口长度")
    parser.add_argument("--max_ep_len", type=int, default=4096, help="最大时间步")
    parser.add_argument("--hidden_size", type=int, default=256, help="隐藏层维度")
    parser.add_argument("--num_hidden_layers", type=int, default=4, help="隐藏层数量")
    parser.add_argument("--num_attention_heads", type=int, default=8, help="注意力头数量")
    parser.add_argument("--num_key_value_heads", type=int, default=2, help="KV头数量")
    parser.add_argument("--dropout", type=float, default=0.1, help="dropout")
    parser.add_argument("--cache_size", type=int, default=8, help="离线pkl缓存数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--use_compile", type=int, default=0, choices=[0, 1], help="是否使用torch.compile")
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    os.makedirs(args.save_dir, exist_ok=True)
    train_ds = MarioDTOfflineDataset(
        data_root=args.data_root,
        context_len=args.context_len,
        cache_size=args.cache_size,
        strict=True,
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
        model = torch.compile(model)
        Logger("torch.compile enabled")

    loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=torch.cuda.is_available(),
        drop_last=False,
    )

    optimizer = optim.AdamW(model.parameters(), lr=args.learning_rate, betas=(0.9, 0.95), weight_decay=0.01)

    device_type = "cuda" if "cuda" in args.device else "cpu"
    if args.dtype == "float16":
        amp_dtype = torch.float16
    elif args.dtype == "bfloat16":
        amp_dtype = torch.bfloat16
    else:
        amp_dtype = torch.float32

    autocast_ctx = nullcontext() if (device_type == "cpu" or amp_dtype == torch.float32) else torch.cuda.amp.autocast(dtype=amp_dtype)
    scaler = torch.cuda.amp.GradScaler(enabled=(device_type == "cuda" and amp_dtype == torch.float16))

    Logger(f"Dataset steps(weighted): {len(train_ds)}, batches/epoch: {len(loader)}")
    Logger(
        f"DT config: state_shape={state_shape}, act_dim={act_dim}, context_len={args.context_len}, "
        f"hidden={args.hidden_size}, layers={args.num_hidden_layers}"
    )

    for ep in range(1, args.epochs + 1):
        train_epoch(ep, loader, len(loader))

    final_path = os.path.join(args.save_dir, f"{args.save_weight}_final.pth")
    save_checkpoint(model, optimizer, args.epochs, len(loader), final_path)
    Logger(f"Training finished, final checkpoint saved: {final_path}")
