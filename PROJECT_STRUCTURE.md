# RL for Mario - 项目架构说明

**最后更新**: 2026-04-25

---

## 📁 整体架构

```
RL_for_Mario/                    # 主项目：Mario强化学习训练
│
├── 📄 核心文件
│   ├── README.md                # 项目主说明
│   ├── LICENSE                  # MIT许可证
│   ├── CODE_OF_CONDUCT.md       # 行为准则
│   ├── requirements.txt         # Python依赖
│   ├── .gitignore               
│   └── PROJECT_STRUCTURE.md     # 本文件
│
├── 📚 docs/                     # 主项目文档
│   ├── mario_ppo_report.md      # PPO数据收集报告
│   └── mario_transformer_todo.md # DT任务清单
│
├── 🎮 envs/                     # 环境封装
│   └── (nes_py包装等)
│
├── 🧠 model/                    # 模型定义
│   ├── decision_transformer/    # DT模型
│   └── (其他模型)
│
├── 🏋️ trainer/                  # 训练器
│   ├── ppo/                     # PPO训练器
│   └── dt/                      # DT训练器
│
├── 🚀 scripts/                  # 训练脚本
│   └── mario/                   # Mario相关脚本
│
├── 💾 trained_models/           # 训练好的权重
│   └── dt_mario_pro_hs512_L6_best.pth
│
└── 🎯 nes_emulator_gpu/         # 🆕 GPU NES模拟器子项目
    ├── README.md                # 模拟器项目说明
    ├── LICENSE                  # GPL-2.0
    │
    ├── docs/                    # 技术文档
    │   ├── gpu_emulator_research.md
    │   ├── reference_impl_choice.md
    │   └── rom_setup_guide.md
    │
    ├── phases/                  # 🆕 阶段任务追踪
    │   ├── phase0_research/     # ✅ 已完成
    │   │   ├── README.md
    │   │   ├── tasks.md
    │   │   └── completion_report.md
    │   ├── phase1_cpu/          # ⏳ 待开始
    │   ├── phase2_ppu/
    │   ├── phase3_cuda_single/
    │   ├── phase4_cuda_batch/
    │   ├── phase5_python/
    │   └── phase6_integration/
    │
    ├── src/                     # 源代码
    │   ├── reference/           # C++ CPU参考实现
    │   │   ├── cpu/
    │   │   ├── ppu/
    │   │   └── common/
    │   ├── cuda/                # CUDA GPU实现
    │   │   ├── kernels/
    │   │   └── device/
    │   └── python/              # Python绑定
    │
    ├── tests/                   # 测试
    │   ├── roms/                # 测试ROM (11个)
    │   ├── unit/                # 单元测试
    │   └── integration/         # 集成测试
    │       └── nes-test-roms/   # 67个测试套件
    │
    └── benchmarks/              # 性能测试
        ├── cpu_baseline/
        └── gpu_profile/
```

---

## 🎯 项目关系

1. **主项目** (`RL_for_Mario/`)
   - Mario强化学习训练
   - Decision Transformer预训练
   - PPO在线fine-tuning

2. **GPU模拟器子项目** (`nes_emulator_gpu/`)
   - 独立的GPU NES模拟器
   - 目标：加速PPO训练100倍
   - 可独立编译和测试

3. **集成方式** (Phase 6)
   - GPU模拟器编译为Python包
   - 替换`envs/`中的nes_py
   - 无缝集成到训练流程

---

## 📊 当前状态

### 主项目
- ✅ Decision Transformer预训练完成
- ✅ PPO数据收集完成
- ⏸️ PPO在线训练受CPU瓶颈限制（等待GPU模拟器）

### GPU模拟器子项目
- ✅ Phase 0: 技术调研与环境准备 (已完成)
- ⏳ Phase 1: CPU参考实现 - 6502 CPU (待开始)
- ⏳ Phase 2-6: 后续阶段

---

## 🔄 工作流程

### 当前阶段 (Phase 0完成)
1. ✅ 确认技术可行性（cuLE证明）
2. ✅ 选择参考实现（quickerNES）
3. ✅ 环境准备完成（CUDA 12.4 + V100）
4. ✅ 测试ROM就绪

### 下一步 (Phase 1)
1. 实现6502 CPU模拟器
2. 通过11个指令测试ROM
3. 为Phase 2 PPU实现做准备

### 长期目标 (Phase 6)
1. GPU模拟器集成到训练流程
2. 实现30,000+ sps训练速度
3. 完成PPO在线fine-tuning

---

## 📝 文档索引

### 主项目文档
- [`README.md`](README.md) - 项目总览
- [`docs/mario_ppo_report.md`](docs/mario_ppo_data_collection_report.md) - PPO报告
- [`docs/mario_transformer_todo.md`](docs/mario_transformer_todo_list.txt) - DT任务

### GPU模拟器文档
- [`nes_emulator_gpu/README.md`](nes_emulator_gpu/README.md) - 模拟器总览
- [`nes_emulator_gpu/docs/gpu_emulator_research.md`](nes_emulator_gpu/docs/gpu_emulator_research.md) - 技术调研
- [`nes_emulator_gpu/phases/phase0_research/`](nes_emulator_gpu/phases/phase0_research/) - Phase 0详情

---

## 🛠️ 开发指引

### 主项目开发
```bash
cd /work/xmyan/RL_for_Mario
pip install -r requirements.txt
# 训练脚本在 scripts/mario/
```

### GPU模拟器开发
```bash
cd /work/xmyan/RL_for_Mario/nes_emulator_gpu

# 查看当前阶段
cat phases/phase0_research/README.md

# 编译CUDA测试
cd tests/unit
nvcc test_cuda.cu -o test_cuda && ./test_cuda

# 运行CPU测试ROM (Phase 1后)
cd tests/roms
# (待实现)
```

---

**维护者**: AI Assistant  
**问题反馈**: 请创建Issue或查看各phase的tasks.md
