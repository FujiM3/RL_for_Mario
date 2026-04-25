# Trained Models - 已训练模型权重

本目录存放已完成训练的模型权重。

---

## 📊 模型清单

### Decision Transformer (DT)
| 文件名 | 大小 | 描述 | 训练步数 | 日期 |
|--------|------|------|----------|------|
| `dt_mario_pro_hs512_L6_best.pth` | 238 MB | DT预训练最佳权重 | 145万步 | 2024 |

**架构**:
- Hidden size: 512
- Layers: 6
- State encoder: Nature DQN CNN
- 数据: 145万步专家数据（已收敛）

**用途**: PPO fine-tuning的初始化权重

---

### PPO 权重 (16个关卡)
| 文件名 | 大小 | 描述 |
|--------|------|------|
| `ppo_super_mario_bros_1_1` | 2.4 MB | 关卡 1-1 |
| `ppo_super_mario_bros_1_2` | 2.4 MB | 关卡 1-2 |
| `ppo_super_mario_bros_1_3` | 2.4 MB | 关卡 1-3 |
| `ppo_super_mario_bros_1_4` | 2.4 MB | 关卡 1-4 |
| `ppo_super_mario_bros_2_1` | 2.4 MB | 关卡 2-1 |
| `ppo_super_mario_bros_2_2` | 2.4 MB | 关卡 2-2 |
| `ppo_super_mario_bros_2_3` | 2.4 MB | 关卡 2-3 |
| `ppo_super_mario_bros_2_4` | 2.4 MB | 关卡 2-4 |
| `ppo_super_mario_bros_3_1` | 2.4 MB | 关卡 3-1 |
| `ppo_super_mario_bros_3_2` | 2.4 MB | 关卡 3-2 |
| `ppo_super_mario_bros_3_3` | 2.4 MB | 关卡 3-3 |
| `ppo_super_mario_bros_3_4` | 2.4 MB | 关卡 3-4 |
| `ppo_super_mario_bros_4_1` | 2.4 MB | 关卡 4-1 |
| `ppo_super_mario_bros_4_2` | 2.4 MB | 关卡 4-2 |
| `ppo_super_mario_bros_4_3` | 2.4 MB | 关卡 4-3 |
| `ppo_super_mario_bros_4_4` | 2.5 MB | 关卡 4-4 |

**架构**: Nature DQN CNN + PPO策略头  
**用途**: 各关卡专家策略

---

## 📥 加载模型

### Decision Transformer
```python
import torch
from model.decision_transformer import DecisionTransformer

# 加载模型
model = DecisionTransformer(...)
checkpoint = torch.load('trained_models/dt_mario_pro_hs512_L6_best.pth')
model.load_state_dict(checkpoint['model_state_dict'])
```

### PPO 模型
```python
import torch

# 加载PPO权重
model = torch.load('trained_models/ppo_super_mario_bros_1_1')
```

---

## 💾 存储说明

- **Git 追踪**: ✅ 这些权重会被git追踪（重要资产）
- **备份**: 建议定期备份到云存储
- **大小**: 总计约 280 MB

---

## 🚀 未来模型

### GPU NES模拟器训练后 (Phase 6)
- `ppo_gpu_finetune_*.pth` - 使用GPU模拟器fine-tune的权重
- 预期速度提升100倍，可能获得更好的策略

---

**最后更新**: 2026-04-25  
**总权重数**: 17 (1 DT + 16 PPO)
