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
  - `scripts\mario\collect_stratified_random_level_rollouts.py`（分层采样调度并自动合并）
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

### 2.1) 分层采样采集（Expert / Micro-Recovery / Exploratory）

```powershell
python scripts\mario\collect_stratified_random_level_rollouts.py `
  --ckpt_dir trained_models `
  --output_path dataset\random_data\stratified_rollouts_50000.pkl `
  --total_episodes 50000 `
  --expert_ratio 0.35 `
  --micro_ratio 0.45 `
  --failure_ratio 0.20 `
  --failure_epsilon_max 0.15 `
  --min_length 100 `
  --min_return 500 `
  --num_workers 8 `
  --ipc_mode spill `
  --shard_size 64
```

可选开启质量停机守门（默认开启）：
- `--qc_expert_min_clear_ratio` / `--qc_expert_min_p90_x`：专家层硬门槛（推荐最严格）
- `--qc_micro_min_clear_ratio` / `--qc_micro_min_p90_x`：微扰恢复层门槛
- `--qc_failure_min_clear_ratio` / `--qc_failure_min_p90_x`：失败探索层门槛
- `--qc_skip_failure_tier 0|1`：是否跳过失败层质检（默认 0，不跳过）
- `--qc_min_clear_ratio` / `--qc_min_p90_return` / `--qc_min_p90_x`：全局兜底阈值（兼容旧参数）
- `--disable_qc`：关闭自动停机（不推荐）
- `--resume 0|1`：是否复用已存在的 tier 输出并从断点继续（默认 1）

如果你希望只记住一个入口脚本，也可以通过 `collect_dt_dataset_from_ppo.py` 转发到随机采集器：

```powershell
python scripts\mario\collect_dt_dataset_from_ppo.py `
  --collector random_level `
  --ckpt_dir trained_models `
  --output_path dataset\aligned_greedy\random_level_eps_rollouts.pkl `
  --total_episodes 500 `
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
4. 两个采集脚本现在都支持中断落盘（例如 `Ctrl+C`）：会保存当前已保留的 episode，并在 `metadata` 中标记 `interrupted` 与 `collection_completed`；随机并发采集器还支持 `--checkpoint_interval` 周期性检查点，降低异常掉电时的数据损失。
5. 若单关采集环境缺少 `shimmy`，脚本会自动回退到进程内向量环境继续采集（速度可能略慢，但不阻塞保存）。

## 采集速度优化建议（重点）

1. 多进程采集优先使用 `--device auto`（脚本会在 `num_workers>1` 时自动使用 CPU worker，避免多进程争抢单卡 GPU）。
2. 随机关卡采集优先使用 `--cap_mode ondemand` 或 `--cap_mode fast`，避免启动时全关卡探测导致长时间冷启动。
3. 对低质量轨迹过滤较严格时（`--min_return`/`--min_length`），新版本会在 worker 侧先过滤，减少进程间大数组传输开销。
4. 若要进一步降低 IPC 与内存峰值，建议开启：
   - `--ipc_mode spill`（worker 先落盘再回传路径）
   - `--shard_size 128`（父进程按分片落盘，避免单文件大内存累积）
   - `--spill_direct_shard 1`（默认开启；在 spill+shard 模式下由 worker 按 `shard_size` 直接写 shard，减少父进程读回+重写）


---

## 🆕 GPU NES模拟器子项目

为解决PPO在线训练的CPU瓶颈，本项目正在开发GPU原生NES模拟器。

**详见**: [`nes_emulator_gpu/README.md`](nes_emulator_gpu/README.md)

**目标**: 将训练速度从 252 sps 提升至 30,000+ sps (100倍)

**当前状态**: Phase 0 已完成，Phase 1 准备中

