# `model_decision_transformer.py` 与 `model_minimind.py` 异同说明

## 总结

两者都属于 **Decoder-only Transformer** 风格实现，核心计算骨架（RMSNorm、RoPE、自注意力、SwiGLU-FFN、残差连接、KV Cache）高度一致；  
关键区别在于：`model_minimind.py` 面向 **文本自回归语言建模**，`model_decision_transformer.py` 面向 **序列决策建模（Mario）**。

## 相同点（结构层面）

1. **配置类 + 主模型类分层**
   - 都有 `PretrainedConfig` 子类负责超参管理。
   - 都有 `PreTrainedModel` 子类作为最终对外模型入口。

2. **Transformer 主干组件一致**
   - 使用 `RMSNorm`。
   - 使用 RoPE（`precompute_freqs_cis` + `apply_rotary_pos_emb`）。
   - 使用 GQA 形式的 Attention（`num_key_value_heads` + `repeat_kv`）。
   - 使用 Pre-Norm Block（Attention + FFN + 残差）。
   - 支持 `past_key_values` 缓存。

3. **训练接口形态相似**
   - `forward(...)` 中都返回 logits / loss 相关信息。
   - 都允许通过 `attention_mask` 控制有效 token。

## 不同点（任务与输入输出）

| 维度 | `model_minimind.py` | `model_decision_transformer.py` |
|---|---|---|
| 任务目标 | 语言建模（下一 token 预测） | 决策建模（给定状态/回报/历史动作预测动作） |
| 输入主体 | `input_ids`（文本 token） | `states`, `actions`, `returns_to_go`, `timesteps` |
| 输入嵌入 | `Embedding(vocab_size, hidden_size)` | 状态线性编码 + 回报线性编码 + 动作嵌入 + 时间嵌入 |
| 序列组织 | 纯文本 token 序列 | 每个时刻三元组 `(R_t, s_t, a_t)` 交错堆叠 |
| 输出头 | `lm_head`（词表 logits） | `action_head`（动作 logits） + `value_head`（状态价值） |
| loss | 文本交叉熵（shift logits/labels） | 动作交叉熵（可用 `action_targets`） |
| 生成/推理 | 语言生成（GenerationMixin） | `act()` 采样/贪心输出离散动作 |
| 专家网络 | 支持 MoE（路由、aux loss） | 当前为标准 FFN（`aux_loss` 固定为 0） |

## 关键设计差异说明

### 1) 建模对象不同
- `model_minimind.py` 学习的是 **token->token** 的统计关系；
- `model_decision_transformer.py` 学习的是 **(return, state, action) 序列->下一动作** 的策略关系。

### 2) token 语义不同
- MiniMind 的 token 是离散词表 ID；
- Decision Transformer 的 token 是多模态构造：
  - `return token`（标量回报）
  - `state token`（图像状态编码）
  - `action token`（离散动作嵌入）

### 3) 输出用途不同
- MiniMind 的 logits 用于文本解码；
- DT 的动作 logits 直接用于环境交互，value 头用于后续 RL 训练（如 PPO/优势估计）。

## 当前实现上的取舍

1. `model_decision_transformer.py` 已重构为与 MiniMind 类似的**自包含模块化实现**，不再依赖从 `model_minimind.py` 直接调用 Block。
2. 为保障 Mario 联调，DT 增加了更严格的输入形状检查（`[B,T,C,H,W]`、`context_len`、`state_shape` 等）。
3. DT 当前未实现 MoE 路由逻辑，保持结构简洁，优先稳定跑通决策任务。


## 后续可对齐优化（可选）

1. 将 DT 的 RoPE 外推与 MiniMind 的 YaRN 缩放策略对齐。
2. 为 DT 增加可选 MoE-FFN 分支（仅在性能瓶颈时启用）。
3. 统一两者输出结构与 checkpoint 字段命名，便于训练脚本复用。
