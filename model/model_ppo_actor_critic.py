"""
model/model_ppo_actor_critic.py

Actor-Critic network for PPO fine-tuning on Super Mario Bros.

Architecture:
  state_encoder  →  从预训练 DT checkpoint 加载 (Nature DQN CNN, 512-dim)
  actor_head     →  512 → 256 → 7  (随机初始化)
  critic_head    →  512 → 256 → 1  (随机初始化)

使用方法:
  model = ActorCriticPPO()
  model.load_encoder_from_dt("trainer/out/mario_dt_v2/dt_mario_v2_hs512_L6_best.pth")
  param_groups = model.get_param_groups(encoder_lr=1e-5, head_lr=3e-4)
  optimizer = torch.optim.Adam(param_groups)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple, List, Dict


# ── Nature DQN CNN ────────────────────────────────────────────────────────────

class NatureCNN(nn.Module):
    """
    Nature DQN CNN，与 DT 里的 state_encoder 结构完全对齐。

    输入:  (B, 4, 84, 84)  uint8 或 float32
    输出:  (B, hidden_size)
    """

    def __init__(self, in_channels: int = 4, hidden_size: int = 512):
        super().__init__()

        # 结构与 DT 的 state_encoder.cnn 完全对齐：
        # cnn.0 Conv, cnn.1 ReLU, cnn.2 Conv, cnn.3 ReLU,
        # cnn.4 Conv, cnn.5 ReLU, cnn.6 Flatten, cnn.7 Linear
        self.cnn = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=8, stride=4),  # 0
            nn.ReLU(inplace=True),                                  # 1
            nn.Conv2d(32, 64, kernel_size=4, stride=2),             # 2
            nn.ReLU(inplace=True),                                  # 3
            nn.Conv2d(64, 64, kernel_size=3, stride=1),             # 4
            nn.ReLU(inplace=True),                                  # 5
            nn.Flatten(),                                           # 6
            nn.Linear(64 * 7 * 7, hidden_size),                    # 7
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.dtype == torch.uint8:
            x = x.float() / 255.0
        return F.relu(self.cnn(x))


# ── Actor-Critic ──────────────────────────────────────────────────────────────

class ActorCriticPPO(nn.Module):
    """
    PPO Actor-Critic。

    设计原则：
    - state_encoder 加载预训练权重，使用较小学习率慢速微调
    - actor/critic head 随机初始化，使用正常学习率
    - 支持 get_param_groups() 返回分组学习率

    Args:
        act_dim:     动作维度，SIMPLE_MOVEMENT = 7
        hidden_size: CNN 输出维度，需与 DT 的 hidden_size 一致 (512)
        head_hidden: Actor/Critic 隐层维度 (256)
    """

    def __init__(
        self,
        act_dim: int = 7,
        hidden_size: int = 512,
        head_hidden: int = 256,
    ):
        super().__init__()

        self.act_dim = act_dim
        self.hidden_size = hidden_size

        # ── Encoder（预训练权重来源）────────────────────────────────────
        self.state_encoder = NatureCNN(in_channels=4, hidden_size=hidden_size)

        # ── Actor Head ──────────────────────────────────────────────────
        self.actor = nn.Sequential(
            nn.Linear(hidden_size, head_hidden),
            nn.ReLU(inplace=True),
            nn.Linear(head_hidden, act_dim),
        )

        # ── Critic Head ─────────────────────────────────────────────────
        self.critic = nn.Sequential(
            nn.Linear(hidden_size, head_hidden),
            nn.ReLU(inplace=True),
            nn.Linear(head_hidden, 1),
        )

        self._init_heads()

    def _init_heads(self):
        """
        Orthogonal 初始化 head 层，标准 PPO 做法。
        最后一层 actor 用极小 gain，使初始策略接近均匀分布。
        """
        for module in [self.actor, self.critic]:
            for layer in module:
                if isinstance(layer, nn.Linear):
                    nn.init.orthogonal_(layer.weight, gain=1.0)
                    nn.init.constant_(layer.bias, 0.0)

        # Actor 最后一层用小 gain → 初始策略近似均匀
        nn.init.orthogonal_(self.actor[-1].weight, gain=0.01)
        # Critic 最后一层
        nn.init.orthogonal_(self.critic[-1].weight, gain=1.0)

    # ── Forward ──────────────────────────────────────────────────────────────

    def forward(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            obs: (B, 4, 84, 84) uint8 or float32
        Returns:
            logits: (B, act_dim)
            value:  (B,)
        """
        feat = self.state_encoder(obs)          # (B, 512)
        logits = self.actor(feat)               # (B, 7)
        value = self.critic(feat).squeeze(-1)   # (B,)
        return logits, value

    def get_action_and_value(
        self,
        obs: torch.Tensor,
        action: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Rollout 采样 & PPO update 共用接口。

        Args:
            obs:    (B, 4, 84, 84)
            action: (B,) 若为 None 则自动采样
        Returns:
            action:   (B,)
            log_prob: (B,)
            entropy:  (B,)
            value:    (B,)
        """
        logits, value = self.forward(obs)
        dist = torch.distributions.Categorical(logits=logits)

        if action is None:
            action = dist.sample()

        log_prob = dist.log_prob(action)
        entropy = dist.entropy()
        return action, log_prob, entropy, value

    def get_value(self, obs: torch.Tensor) -> torch.Tensor:
        """仅需 value 时（GAE bootstrapping）用此接口，省去 actor 计算。"""
        feat = self.state_encoder(obs)
        return self.critic(feat).squeeze(-1)

    # ── Weight Loading ────────────────────────────────────────────────────────

    def load_encoder_from_dt(
        self,
        dt_checkpoint_path: str,
        device: str = "cpu",
        strict: bool = True,
    ) -> None:
        """
        从 Decision Transformer checkpoint 加载 state_encoder 权重。

        DT checkpoint 格式支持：
          1. {'model_state_dict': {...}}   ← train_pretrain.py 保存格式
          2. {'state_dict': {...}}
          3. 直接是 state_dict

        Args:
            dt_checkpoint_path: .pth 文件路径
            device:             加载到哪个设备（建议先 cpu，之后 .to(device)）
            strict:             是否严格匹配所有 key（默认 True）
        """
        print(f"[ActorCritic] Loading encoder from: {dt_checkpoint_path}")
        ckpt = torch.load(dt_checkpoint_path, map_location=device)

        # 解析 checkpoint 格式
        if isinstance(ckpt, dict):
            if "model_state_dict" in ckpt:
                state_dict = ckpt["model_state_dict"]
                epoch = ckpt.get("epoch", "?")
                val_loss = ckpt.get("val_loss", "?")
                print(f"[ActorCritic] Checkpoint: epoch={epoch}, val_loss={val_loss}")
            elif "model" in ckpt and isinstance(ckpt["model"], dict):
                state_dict = ckpt["model"]
                epoch = ckpt.get("epoch", "?")
                val_loss = ckpt.get("val_loss", "?")
                print(f"[ActorCritic] Checkpoint: epoch={epoch}, val_loss={val_loss}")
            elif "state_dict" in ckpt:
                state_dict = ckpt["state_dict"]
            else:
                state_dict = ckpt
        else:
            raise ValueError(f"Unexpected checkpoint type: {type(ckpt)}")

        # 兼容两种前缀：
        #   'state_encoder.*'        (直接保存 model.state_dict())
        #   'model.state_encoder.*'  (外层 wrapper 的 state_dict())
        encoder_state = {}
        matched_prefix = None
        for prefix in ("model.state_encoder.", "state_encoder."):
            encoder_state = {
                k[len(prefix):]: v
                for k, v in state_dict.items()
                if k.startswith(prefix)
            }
            if encoder_state:
                matched_prefix = prefix
                print(f"[ActorCritic] Using checkpoint prefix: '{prefix}'")
                break

        if not encoder_state:
            all_prefixes = sorted(set(k.split(".")[0] for k in state_dict.keys()))
            raise KeyError(
                f"No 'state_encoder.*' or 'model.state_encoder.*' keys found.\n"
                f"Available top-level keys: {all_prefixes}"
            )

        missing, unexpected = self.state_encoder.load_state_dict(
            encoder_state, strict=strict
        )

        if missing:
            print(f"[ActorCritic] WARNING: Missing keys in encoder: {missing}")
        if unexpected:
            print(f"[ActorCritic] WARNING: Unexpected keys in encoder: {unexpected}")

        total_params = sum(p.numel() for p in self.state_encoder.parameters())
        print(
            f"[ActorCritic] Encoder loaded successfully. "
            f"Params: {total_params:,} ({total_params/1e6:.1f}M)"
        )

    # ── Optimizer Param Groups ────────────────────────────────────────────────

    def get_param_groups(
        self,
        encoder_lr: float = 1e-5,
        head_lr: float = 3e-4,
    ) -> List[Dict]:
        """
        返回分组学习率的 param_groups，用于 optimizer 构造。

        encoder_lr: 1e-5  → 慢速微调预训练 CNN，防止破坏已收敛的视觉特征
        head_lr:    3e-4  → 正常速度训练 actor/critic head

        Example:
            param_groups = model.get_param_groups(encoder_lr=1e-5, head_lr=3e-4)
            optimizer = torch.optim.Adam(param_groups, eps=1e-5)
        """
        return [
            {
                "params": list(self.state_encoder.parameters()),
                "lr": encoder_lr,
                "name": "encoder",
            },
            {
                "params": (
                    list(self.actor.parameters())
                    + list(self.critic.parameters())
                ),
                "lr": head_lr,
                "name": "heads",
            },
        ]

    def freeze_encoder(self, freeze: bool = True) -> None:
        """
        冻结/解冻 state_encoder。
        训练前几万 step 建议冻结 encoder，让 head 先收敛，再解冻联合微调。
        """
        for p in self.state_encoder.parameters():
            p.requires_grad = not freeze
        status = "frozen" if freeze else "unfrozen"
        print(f"[ActorCritic] state_encoder is now {status}")

    # ── Utility ───────────────────────────────────────────────────────────────

    def count_parameters(self) -> Dict[str, int]:
        enc = sum(p.numel() for p in self.state_encoder.parameters())
        act = sum(p.numel() for p in self.actor.parameters())
        cri = sum(p.numel() for p in self.critic.parameters())
        total = enc + act + cri
        print(
            f"[ActorCritic] Parameters:\n"
            f"  state_encoder : {enc:>10,}\n"
            f"  actor_head    : {act:>10,}\n"
            f"  critic_head   : {cri:>10,}\n"
            f"  total         : {total:>10,} ({total/1e6:.2f}M)"
        )
        return {"encoder": enc, "actor": act, "critic": cri, "total": total}


# ── Quick sanity check ────────────────────────────────────────────────────────

if __name__ == "__main__":
    model = ActorCriticPPO(act_dim=7, hidden_size=512, head_hidden=256)
    model.count_parameters()

    # 模拟一个 batch
    obs = torch.randint(0, 255, (4, 4, 84, 84), dtype=torch.uint8)
    action, log_prob, entropy, value = model.get_action_and_value(obs)

    print(f"\nForward pass OK:")
    print(f"  obs.shape    : {obs.shape}")
    print(f"  action       : {action}")
    print(f"  log_prob     : {log_prob.shape}")
    print(f"  entropy mean : {entropy.mean().item():.4f}  (should be ≈ log(7) ≈ 1.95 at init)")
    print(f"  value        : {value}")

    # 测试 param groups
    groups = model.get_param_groups()
    for g in groups:
        n = sum(p.numel() for p in g["params"])
        print(f"  group '{g['name']}': {n:,} params, lr={g['lr']}")