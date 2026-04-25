import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import torch
import torch.nn.functional as F
from torch import nn
from transformers import PreTrainedModel, PretrainedConfig
from transformers.activations import ACT2FN
from transformers.modeling_outputs import ModelOutput


# ============================================================
# Config
# ============================================================

class DecisionTransformerConfig(PretrainedConfig):
    model_type = "mario-decision-transformer"

    def __init__(
        self,
        state_shape: Tuple[int, int, int] = (4, 84, 84),
        act_dim: int = 7,                   # FIX 1: 原来是 8，Mario 动作空间是 7
        max_ep_len: int = 4096,
        context_len: int = 64,              # FIX 建议: 128→64，attention 计算量减少 75%
        hidden_size: int = 512,
        intermediate_size: Optional[int] = None,
        num_hidden_layers: int = 6,         # 与训练报告一致
        num_attention_heads: int = 8,
        num_key_value_heads: int = 2,
        hidden_act: str = "silu",
        dropout: float = 0.1,
        rms_norm_eps: float = 1e-5,
        rope_theta: float = 10000.0,        # 对 context=64*3=192 足够，原来 1e6 overkill
        flash_attn: bool = True,
        label_smoothing: float = 0.1,       # 新增: 缓解动作分布不均匀带来的过自信
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.state_shape = tuple(state_shape)
        self.act_dim = act_dim
        self.max_ep_len = max_ep_len
        self.context_len = context_len
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.num_key_value_heads = num_key_value_heads
        self.hidden_act = hidden_act
        self.dropout = dropout
        self.rms_norm_eps = rms_norm_eps
        self.rope_theta = rope_theta
        self.flash_attn = flash_attn
        self.label_smoothing = label_smoothing
        self.max_position_embeddings = context_len * 3


# ============================================================
# Output dataclass
# ============================================================

@dataclass
class DecisionTransformerOutput(ModelOutput):
    loss: Optional[torch.FloatTensor] = None
    action_logits: Optional[torch.FloatTensor] = None
    value_preds: Optional[torch.FloatTensor] = None
    last_hidden_state: Optional[torch.FloatTensor] = None
    past_key_values: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None
    # FIX 7: aux_loss 移除，原来永远返回 zero tensor 会污染 compile 计算图


# ============================================================
# Norms
# ============================================================

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def _norm(self, x: torch.Tensor) -> torch.Tensor:
        return x * torch.rsqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.weight * self._norm(x.float()).type_as(x)


# ============================================================
# RoPE
# ============================================================

def precompute_freqs_cis(dim: int, end: int, rope_base: float):
    freqs = 1.0 / (rope_base ** (torch.arange(0, dim, 2).float() / dim))
    t = torch.arange(end, device=freqs.device)
    freqs = torch.outer(t, freqs).float()
    freqs_cos = torch.cat([torch.cos(freqs), torch.cos(freqs)], dim=-1)
    freqs_sin = torch.cat([torch.sin(freqs), torch.sin(freqs)], dim=-1)
    return freqs_cos, freqs_sin


# FIX 2: rotate_half 从闭包提到模块级，避免每次 forward 重新分配函数对象
def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    return torch.cat((-x[..., half:], x[..., :half]), dim=-1)


def apply_rotary_pos_emb(
    q: torch.Tensor, k: torch.Tensor,
    cos: torch.Tensor, sin: torch.Tensor
) -> Tuple[torch.Tensor, torch.Tensor]:
    # q, k: [B, S, H, D]；cos/sin: [S, D]
    cos = cos.unsqueeze(1)  # [S, 1, D]
    sin = sin.unsqueeze(1)
    q_embed = (q * cos) + (_rotate_half(q) * sin)
    k_embed = (k * cos) + (_rotate_half(k) * sin)
    return q_embed, k_embed


# FIX 3: repeat_kv 改为接受 [B, H, S, D]（已转置格式），消除调用处三次转置
def repeat_kv(x: torch.Tensor, n_rep: int) -> torch.Tensor:
    """x: [B, n_kv_heads, S, head_dim] → [B, n_heads, S, head_dim]"""
    if n_rep == 1:
        return x
    B, H, S, D = x.shape
    return (
        x[:, :, None, :, :]
        .expand(B, H, n_rep, S, D)
        .reshape(B, H * n_rep, S, D)
    )


# ============================================================
# Attention
# ============================================================

class DecisionTransformerAttention(nn.Module):
    def __init__(self, config: DecisionTransformerConfig):
        super().__init__()
        self.num_key_value_heads = (
            config.num_attention_heads
            if config.num_key_value_heads is None
            else config.num_key_value_heads
        )
        if config.num_attention_heads % self.num_key_value_heads != 0:
            raise ValueError("num_attention_heads must be divisible by num_key_value_heads")

        self.n_local_heads = config.num_attention_heads
        self.n_local_kv_heads = self.num_key_value_heads
        self.n_rep = self.n_local_heads // self.n_local_kv_heads
        self.head_dim = config.hidden_size // config.num_attention_heads
        self.dropout = config.dropout
        self.flash = (
            hasattr(torch.nn.functional, "scaled_dot_product_attention")
            and config.flash_attn
        )

        self.q_proj = nn.Linear(config.hidden_size, config.num_attention_heads * self.head_dim, bias=False)
        self.k_proj = nn.Linear(config.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(config.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(config.num_attention_heads * self.head_dim, config.hidden_size, bias=False)
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)

    def forward(
        self,
        x: torch.Tensor,
        position_embeddings: Tuple[torch.Tensor, torch.Tensor],
        past_key_value: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
        use_cache: bool = False,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Optional[Tuple[torch.Tensor, torch.Tensor]]]:
        bsz, seq_len, _ = x.shape

        xq = self.q_proj(x).view(bsz, seq_len, self.n_local_heads, self.head_dim)
        xk = self.k_proj(x).view(bsz, seq_len, self.n_local_kv_heads, self.head_dim)
        xv = self.v_proj(x).view(bsz, seq_len, self.n_local_kv_heads, self.head_dim)

        cos, sin = position_embeddings
        xq, xk = apply_rotary_pos_emb(xq, xk, cos, sin)

        # 转为 [B, H, S, D] 格式，后续统一在此格式操作
        xq = xq.transpose(1, 2)                         # [B, H_q,  S,      D]
        xk_cache = xk.transpose(1, 2)                   # [B, H_kv, S,      D]
        xv_cache = xv.transpose(1, 2)                   # [B, H_kv, S,      D]

        # KV Cache 拼接
        if past_key_value is not None:
            xk_cache = torch.cat([past_key_value[0], xk_cache], dim=2)
            xv_cache = torch.cat([past_key_value[1], xv_cache], dim=2)
        past_kv = (xk_cache, xv_cache) if use_cache else None

        # FIX 3: 消除三次转置，repeat_kv 直接在 [B, H, S, D] 上操作
        xk_full = repeat_kv(xk_cache, self.n_rep)       # [B, H_q, kv_len, D]
        xv_full = repeat_kv(xv_cache, self.n_rep)       # [B, H_q, kv_len, D]

        # FIX 4: 移除 torch.all() GPU sync，直接将 padding mask 传给 SDPA
        if self.flash and seq_len > 1 and past_key_value is None:
            if attention_mask is None:
                # 纯因果 mask，SDPA 内部用 FlashAttention 实现
                output = F.scaled_dot_product_attention(
                    xq, xk_full, xv_full,
                    dropout_p=self.dropout if self.training else 0.0,
                    is_causal=True,
                )
            else:
                # 有 padding mask：构建 [B, 1, S, kv_len] 的加法 mask
                # attention_mask: [B, S]，1=有效 0=padding
                kv_len = xk_full.shape[2]
                causal_mask = torch.triu(
                    torch.full((seq_len, kv_len), float("-inf"),
                               device=xq.device, dtype=xq.dtype),
                    diagonal=1,
                ).unsqueeze(0).unsqueeze(0)             # [1, 1, S, kv_len]
                pad_mask = (
                    (1.0 - attention_mask.to(xq.dtype))
                    .unsqueeze(1).unsqueeze(2) * -1e9    # [B, 1, 1, S]
                )
                combined_mask = causal_mask + pad_mask   # [B, 1, S, kv_len]
                output = F.scaled_dot_product_attention(
                    xq, xk_full, xv_full,
                    attn_mask=combined_mask,
                    dropout_p=self.dropout if self.training else 0.0,
                )
        else:
            # 慢路径：推理 KV cache 模式（seq_len 通常为 1）
            scores = (xq @ xk_full.transpose(-2, -1)) / math.sqrt(self.head_dim)
            kv_len = xk_full.shape[2]
            # 只对当前新 token 对应的列施加因果 mask
            causal = torch.triu(
                torch.full((seq_len, seq_len), float("-inf"),
                           device=scores.device, dtype=scores.dtype),
                diagonal=1,
            )
            scores[:, :, :, kv_len - seq_len:] = (
                scores[:, :, :, kv_len - seq_len:] + causal
            )
            if attention_mask is not None:
                scores = scores + (
                    (1.0 - attention_mask.to(scores.dtype))
                    .unsqueeze(1).unsqueeze(2) * -1e9
                )
            scores = F.softmax(scores.float(), dim=-1).type_as(xq)
            scores = self.attn_dropout(scores)
            output = scores @ xv_full

        output = output.transpose(1, 2).reshape(bsz, seq_len, -1)
        output = self.resid_dropout(self.o_proj(output))
        return output, past_kv


# ============================================================
# FFN (SwiGLU，不变)
# ============================================================

class FeedForward(nn.Module):
    def __init__(self, config: DecisionTransformerConfig):
        super().__init__()
        intermediate_size = config.intermediate_size
        if intermediate_size is None:
            intermediate_size = int(config.hidden_size * 8 / 3)
            intermediate_size = 64 * ((intermediate_size + 63) // 64)

        self.gate_proj = nn.Linear(config.hidden_size, intermediate_size, bias=False)
        self.up_proj   = nn.Linear(config.hidden_size, intermediate_size, bias=False)
        self.down_proj = nn.Linear(intermediate_size, config.hidden_size, bias=False)
        self.dropout   = nn.Dropout(config.dropout)
        self.act_fn    = ACT2FN[config.hidden_act]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.dropout(self.down_proj(self.act_fn(self.gate_proj(x)) * self.up_proj(x)))


# ============================================================
# Transformer Block (Pre-Norm，不变)
# ============================================================

class DecisionTransformerBlock(nn.Module):
    def __init__(self, config: DecisionTransformerConfig):
        super().__init__()
        self.input_layernorm        = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.post_attention_layernorm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.self_attn = DecisionTransformerAttention(config)
        self.mlp       = FeedForward(config)

    def forward(
        self,
        hidden_states: torch.Tensor,
        position_embeddings: Tuple[torch.Tensor, torch.Tensor],
        past_key_value: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
        use_cache: bool = False,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Optional[Tuple[torch.Tensor, torch.Tensor]]]:
        residual = hidden_states
        hidden_states, present_key_value = self.self_attn(
            self.input_layernorm(hidden_states),
            position_embeddings,
            past_key_value=past_key_value,
            use_cache=use_cache,
            attention_mask=attention_mask,
        )
        hidden_states = hidden_states + residual
        hidden_states = hidden_states + self.mlp(self.post_attention_layernorm(hidden_states))
        return hidden_states, present_key_value


# ============================================================
# State Encoder
# FIX 5: Flat Linear → Nature DQN CNN
#   原来: 4×84×84=28224 → Linear → 512，参数 14.5M，无空间归纳偏置
#   现在: CNN 提取空间特征，参数 ~1.7M，速度更快，效果更好
# FIX 6: states.float() → states.to(dtype)，恢复 bfloat16 混合精度
# ============================================================

class MarioStateEncoder(nn.Module):
    def __init__(self, state_shape: Tuple[int, int, int], hidden_size: int):
        super().__init__()
        c, h, w = state_shape
        # Nature DQN backbone（适配 84×84 输入）
        # Conv 输出尺寸：84→20→9→7，最终 64×7×7=3136
        self.cnn = nn.Sequential(
            nn.Conv2d(c,  32, kernel_size=8, stride=4),  # [B*T, 32, 20, 20]
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, kernel_size=4, stride=2),  # [B*T, 64,  9,  9]
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, kernel_size=3, stride=1),  # [B*T, 64,  7,  7]
            nn.ReLU(inplace=True),
            nn.Flatten(),                                 # [B*T, 3136]
            nn.Linear(64 * 7 * 7, hidden_size),          # [B*T, hidden_size]
        )

    def forward(self, states: torch.Tensor) -> torch.Tensor:
        if states.ndim != 5:
            raise ValueError(f"states must be [B,T,C,H,W], got {tuple(states.shape)}")
        B, T, C, H, W = states.shape
        # FIX 6: 跟随权重 dtype，不强制 fp32，让 autocast 正常工作
        x = states.to(self.cnn[0].weight.dtype)
        if x.max() > 1.0:
            x = x / 255.0
        # 合并 B×T 维度后过 CNN，再还原
        return self.cnn(x.reshape(B * T, C, H, W)).reshape(B, T, -1)


# ============================================================
# Backbone Model
# ============================================================

class DecisionTransformerModel(nn.Module):
    def __init__(self, config: DecisionTransformerConfig):
        super().__init__()
        self.config = config
        self.state_encoder   = MarioStateEncoder(config.state_shape, config.hidden_size)
        self.embed_return    = nn.Linear(1, config.hidden_size)
        self.embed_action    = nn.Embedding(config.act_dim, config.hidden_size)
        self.embed_timestep  = nn.Embedding(config.max_ep_len, config.hidden_size)
        self.embed_norm      = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.dropout         = nn.Dropout(config.dropout)
        self.layers          = nn.ModuleList(
            [DecisionTransformerBlock(config) for _ in range(config.num_hidden_layers)]
        )
        self.norm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)

        freqs_cos, freqs_sin = precompute_freqs_cis(
            dim=config.hidden_size // config.num_attention_heads,
            end=config.max_position_embeddings,
            rope_base=config.rope_theta,
        )
        self.register_buffer("freqs_cos", freqs_cos, persistent=False)
        self.register_buffer("freqs_sin", freqs_sin, persistent=False)

    def forward(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
        returns_to_go: torch.Tensor,
        timesteps: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        past_key_values: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None,
        use_cache: bool = False,
    ) -> Tuple[torch.Tensor, List, None]:
        batch_size, seq_len = states.shape[0], states.shape[1]

        # 输入校验
        if states.ndim != 5:
            raise ValueError(f"states must be [B,T,C,H,W], got {tuple(states.shape)}")
        if states.shape[2:] != tuple(self.config.state_shape):
            raise ValueError(
                f"states spatial shape {tuple(states.shape[2:])} != config {self.config.state_shape}"
            )
        if actions is None or actions.shape[:2] != (batch_size, seq_len):
            raise ValueError(
                f"actions must be [B,T], got {None if actions is None else tuple(actions.shape)}"
            )
        if returns_to_go.shape[:2] != (batch_size, seq_len):
            raise ValueError(f"returns_to_go must be [B,T], got {tuple(returns_to_go.shape)}")
        if timesteps.shape[:2] != (batch_size, seq_len):
            raise ValueError(f"timesteps must be [B,T], got {tuple(timesteps.shape)}")
        if seq_len > self.config.context_len:
            raise ValueError(f"seq_len={seq_len} exceeds context_len={self.config.context_len}")

        # Embeddings
        timesteps = timesteps.clamp(0, self.config.max_ep_len - 1).long()
        time_embeddings = self.embed_timestep(timesteps)

        state_embeddings   = self.state_encoder(states) + time_embeddings

        # FIX: returns_to_go 也要跟随权重 dtype，不强制 fp32
        rtg_dtype = self.embed_return.weight.dtype
        returns_embeddings = (
            self.embed_return(returns_to_go.unsqueeze(-1).to(rtg_dtype)) + time_embeddings
        )
        action_embeddings  = (
            self.embed_action(actions.long().clamp(0, self.config.act_dim - 1)) + time_embeddings
        )

        # 交错拼接 [R_0, S_0, A_0, R_1, S_1, A_1, ...]
        hidden_states = torch.stack(
            (returns_embeddings, state_embeddings, action_embeddings), dim=2
        ).reshape(batch_size, seq_len * 3, self.config.hidden_size)
        hidden_states = self.dropout(self.embed_norm(hidden_states))

        # Attention mask 扩展
        stacked_attention_mask = None
        if attention_mask is not None:
            if attention_mask.shape != (batch_size, seq_len):
                raise ValueError(
                    f"attention_mask must be [B,T], got {tuple(attention_mask.shape)}"
                )
            stacked_attention_mask = (
                torch.stack((attention_mask, attention_mask, attention_mask), dim=2)
                .reshape(batch_size, seq_len * 3)
                .to(hidden_states.dtype)
            )

        # Past KV 处理
        if hasattr(past_key_values, "layers"):
            past_key_values = None
        past_key_values = past_key_values or [None] * len(self.layers)
        start_pos = past_key_values[0][0].shape[2] if past_key_values[0] is not None else 0
        position_embeddings = (
            self.freqs_cos[start_pos: start_pos + seq_len * 3],
            self.freqs_sin[start_pos: start_pos + seq_len * 3],
        )

        # Transformer Layers
        presents = []
        for layer, past_key_value in zip(self.layers, past_key_values):
            hidden_states, present = layer(
                hidden_states=hidden_states,
                position_embeddings=position_embeddings,
                past_key_value=past_key_value,
                use_cache=use_cache,
                attention_mask=stacked_attention_mask,
            )
            presents.append(present)

        hidden_states = self.norm(hidden_states).view(
            batch_size, seq_len, 3, self.config.hidden_size
        )
        # FIX 7: aux_loss 移除，不再返回 zero tensor
        return hidden_states, presents


# ============================================================
# Top-level PreTrainedModel
# ============================================================

class MarioDecisionTransformer(PreTrainedModel):
    config_class = DecisionTransformerConfig
    base_model_prefix = "decision_transformer"

    def __init__(self, config: DecisionTransformerConfig):
        super().__init__(config)
        self.model       = DecisionTransformerModel(config)
        self.action_head = nn.Linear(config.hidden_size, config.act_dim, bias=False)
        self.value_head  = nn.Linear(config.hidden_size, 1)
        self.post_init()

    def forward(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
        returns_to_go: torch.Tensor,
        timesteps: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        action_targets: Optional[torch.Tensor] = None,
        past_key_values: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None,
        use_cache: bool = False,
        **kwargs,
    ) -> DecisionTransformerOutput:
        # FIX 7: backbone 不再返回 aux_loss
        hidden_states, past_key_values = self.model(
            states=states,
            actions=actions,
            returns_to_go=returns_to_go,
            timesteps=timesteps,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            use_cache=use_cache,
        )

        # hidden_states: [B, T, 3, H]
        # token 顺序: 0=return, 1=state, 2=action
        # 用 state token 预测下一步动作（标准 DT 做法）
        state_tokens = hidden_states[:, :, 1, :]          # [B, T, H]
        action_logits = self.action_head(state_tokens)    # [B, T, act_dim]
        value_preds   = self.value_head(state_tokens).squeeze(-1)  # [B, T]

        # FIX 8: 去掉永远为 True 的 if targets is not None 包装
        targets = action_targets if action_targets is not None else actions
        loss = F.cross_entropy(
            action_logits.reshape(-1, self.config.act_dim),
            targets.reshape(-1).long(),
            ignore_index=-100,
            label_smoothing=self.config.label_smoothing,  # 新增: 缓解动作频率偏置
        )

        return DecisionTransformerOutput(
            loss=loss,
            action_logits=action_logits,
            value_preds=value_preds,
            last_hidden_state=hidden_states,
            past_key_values=past_key_values,
        )

    @torch.no_grad()
    def act(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
        returns_to_go: torch.Tensor,
        timesteps: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        deterministic: bool = False,
    ) -> torch.Tensor:
        outputs = self.forward(
            states=states,
            actions=actions,
            returns_to_go=returns_to_go,
            timesteps=timesteps,
            attention_mask=attention_mask,
            action_targets=None,
            use_cache=False,
        )
        logits = outputs.action_logits[:, -1, :]          # 只取最后一步
        if deterministic:
            return torch.argmax(logits, dim=-1)
        return torch.distributions.Categorical(logits=logits).sample()