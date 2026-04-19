# mario_rl

基于 **Super Mario Bros** 的离线强化学习项目，核心是把 PPO 策略采样得到的轨迹整理成离线数据，再训练 **Decision Transformer (DT)** 做动作预测。

项目同时保留了 `model_minimind.py`（通用 Decoder-only Transformer / MoE 版本）作为结构参考；Mario 训练主线使用的是 `model_decision_transformer.py`。

## 项目包含什么

- **环境封装**：`envs\mario_env.py`
  - 帧跳跃、灰度化、84x84 缩放、帧堆叠、奖励裁剪
- **DT 模型**：`model\model_decision_transformer.py`
  - RoPE + GQA + RMSNorm 的 Decoder-only 主干
  - `action_head` 预测离散动作，`value_head` 预测状态价值
- **离线数据加载**：`scripts\mario\dt_offline_dataset.py`
  - 按轨迹长度加权采样、固定上下文窗口、自动 padding + attention mask
- **数据采集脚本**：
  - `scripts\mario\collect_dt_dataset_from_ppo.py`（单关/向量化采集）
  - `scripts\mario\collect_random_level_eps_rollouts.py`（多关随机并发采集）
- **训练脚本**：`trainer\train_pretrain.py`
- **可视化与联调**：
  - `scripts\mario\visualize_ppo_rollout.py`
  - `scripts\mario\test_io.py`

## 目录结构

```text
mario_rl/
├─ envs/
├─ model/
├─ scripts/mario/
├─ trainer/
├─ requirements.txt
└─ mario_ppo_data_collection_report.md
```

## 环境准备（Windows）

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

> 说明：采集脚本使用了 `stable_baselines3.common.vec_env.SubprocVecEnv`，若环境中缺失请额外安装：
>
> ```powershell
> pip install stable-baselines3
> ```

## 快速开始

### 1) 从 PPO 权重采集离线数据（单关）

```powershell
python scripts\mario\collect_dt_dataset_from_ppo.py `
  --model_path PPO_trained_models\ppo_super_mario_bros_1_1 `
  --env_id SuperMarioBros-1-1-v0 `
  --output_path dataset\aligned_greedy\ppo_1_1_greedy.pkl `
  --total_episodes 100 `
  --num_envs 8 `
  --action_type simple
```

### 2) 多关随机并发采集（推荐构建大数据集）

```powershell
python scripts\mario\collect_random_level_eps_rollouts.py `
  --ckpt_dir PPO_trained_models `
  --output_path dataset\aligned_greedy\random_level_eps_rollouts.pkl `
  --total_episodes 500 `
  --num_workers 8 `
  --epsilon_min 0.00 `
  --epsilon_max 0.25 `
  --gate_ratio 0.70 `
  --cap_mode ondemand
```

### 3) 训练 Decision Transformer

```powershell
python trainer\train_pretrain.py `
  --data_root dataset\aligned_greedy\random_level_eps_rollouts.pkl `
  --save_dir out `
  --save_weight dt_pretrain `
  --epochs 1 `
  --batch_size 4 `
  --context_len 64 `
  --hidden_size 256 `
  --num_hidden_layers 4
```

### 4) 数据与模型联调

```powershell
python scripts\mario\dt_offline_dataset.py --data_root dataset\aligned_greedy\random_level_eps_rollouts.pkl --context_len 64 --batch_size 4
python scripts\mario\test_io.py
```

### 5) PPO 策略可视化回放

```powershell
python scripts\mario\visualize_ppo_rollout.py `
  --model_path PPO_trained_models\ppo_super_mario_bros_1_1 `
  --env_id SuperMarioBros-1-1-v3 `
  --num_rollouts 5 `
  --action_type simple
```

## 离线数据格式（pkl）

采集结果通常是一个字典：

- `metadata`：采集配置和统计信息
- `episodes`：轨迹列表，每条轨迹包含：
  - `observations` `[T,4,84,84]`（uint8）
  - `actions` `[T]`（int64）
  - `rewards` `[T]`（float32）
  - `returns_to_go` `[T]`（float32）
  - `timesteps` `[T]`（int32/int64）
  - `terminateds` / `truncateds` / `flag_gets`

## 常见注意事项

1. `action_type` 必须和 checkpoint 的动作维度匹配，否则脚本会报错。
2. 采集与可视化脚本依赖 Mario Gym 环境（`gym-super-mario-bros`, `nes-py`）。
3. `model\model_minimind.py` 主要用于通用语言模型结构实验，不是 Mario 训练主入口。

## 采集速度优化建议（重点）

1. 多进程采集优先使用 `--device auto`（脚本会在 `num_workers>1` 时自动使用 CPU worker，避免多进程争抢单卡 GPU）。
2. 随机关卡采集优先使用 `--cap_mode ondemand` 或 `--cap_mode fast`，避免启动时全关卡探测导致长时间冷启动。
3. 对低质量轨迹过滤较严格时（`--min_return`/`--min_length`），新版本会在 worker 侧先过滤，减少进程间大数组传输开销。
4. 若要进一步降低 IPC 与内存峰值，建议开启：
   - `--ipc_mode spill`（worker 先落盘再回传路径）
   - `--shard_size 128`（父进程按分片落盘，避免单文件大内存累积）

