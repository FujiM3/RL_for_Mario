# NES GPU Emulator

**GPU原生NES模拟器，专为Mario强化学习训练加速设计**

---

## 🎯 项目目标

将Super Mario Bros强化学习训练速度从 **252 steps/sec** 提升至 **30,000+ steps/sec**

通过构建GPU并行NES模拟器，彻底解决PPO在线训练的CPU瓶颈问题。

---

## 📊 当前状态

| Phase | 名称 | 状态 | 预计时间 | 实际时间 |
|-------|------|------|----------|----------|
| **Phase 0** | 技术调研与环境准备 | ✅ **完成** | 1周 | < 1小时 |
| **Phase 1** | CPU参考实现 - 6502 CPU | ⏳ 待开始 | 2-3周 | - |
| **Phase 2** | CPU参考实现 - PPU图形 | ⏳ 待开始 | 3-4周 | - |
| **Phase 3** | 单实例GPU移植 | ⏳ 待开始 | 4-6周 | - |
| **Phase 4** | 批量并行GPU模拟器 | ⏳ 待开始 | 3-4周 | - |
| **Phase 5** | Python/Gymnasium接口 | ⏳ 待开始 | 1周 | - |
| **Phase 6** | 集成PPO训练验证 | ⏳ 待开始 | 1-2周 | - |

**总体进度**: 1/7 阶段完成 (14%)

---

## 🏗️ 项目结构

```
nes_emulator_gpu/
├── README.md              # 本文件
├── LICENSE                # GPL-2.0 (继承quickerNES)
├── .gitignore
│
├── docs/                  # 技术文档
│   ├── gpu_emulator_research.md      # GPU模拟器调研报告
│   ├── reference_impl_choice.md      # 参考实现选择
│   ├── rom_setup_guide.md            # ROM获取指南
│   └── architecture.md               # 架构设计(待创建)
│
├── phases/                # 各阶段任务追踪
│   ├── phase0_research/              # ✅ 已完成
│   ├── phase1_cpu/                   # ⏳ 待开始
│   ├── phase2_ppu/
│   ├── phase3_cuda_single/
│   ├── phase4_cuda_batch/
│   ├── phase5_python/
│   └── phase6_integration/
│
├── src/                   # 源代码
│   ├── reference/         # Phase1-2: C/C++ CPU参考实现
│   │   ├── cpu/           # 6502 CPU模拟器
│   │   ├── ppu/           # PPU图形渲染
│   │   └── common/        # 公共代码
│   ├── cuda/              # Phase3-4: CUDA GPU实现
│   │   ├── kernels/       # CUDA kernel
│   │   └── device/        # Device函数
│   └── python/            # Phase5: Python绑定
│
├── tests/                 # 测试
│   ├── roms/              # 测试ROM (11个CPU测试)
│   ├── unit/              # 单元测试
│   └── integration/       # 集成测试
│       └── nes-test-roms/ # 公开测试ROM集(67套件)
│
└── benchmarks/            # 性能测试
    ├── cpu_baseline/      # CPU基准
    └── gpu_profile/       # GPU性能分析
```

---

## 🔬 技术架构

### CPU参考实现 (Phase 1-2)
- **基于**: quickerNES (GPL-2.0)
- **语言**: C++
- **关键组件**:
  * 6502 CPU (~2000行)
  * NES PPU (~3000行)
  * Mapper 0 (NROM)

### CUDA GPU实现 (Phase 3-4)
- **架构参考**: cuLE (NVIDIA CUDA Learning Environment)
- **并行策略**: 每warp一个NES实例
- **内存布局**: SoA (Structure of Arrays)
- **目标性能**: 1000实例 × 30fps = 30,000 sps

### Python接口 (Phase 5)
- **绑定**: pybind11
- **接口**: Gymnasium兼容
- **零拷贝**: 直接返回CUDA Tensor

---

## 🛠️ 硬件环境

- **GPU**: 10× Tesla V100 PCIe 32GB (使用1块)
- **CUDA**: 12.4
- **Driver**: 570.124.06
- **计算能力**: 7.0
- **Multiprocessors**: 80

---

## 📚 关键参考

### 开源项目
- [cuLE](https://github.com/NVlabs/cule) - CUDA Atari模拟器（架构参考）
- [quickerNES](https://github.com/SergioMartin86/quickerNES) - 高性能NES模拟器（代码参考）
- [EnvPool](https://github.com/sail-sg/envpool) - 多环境并行框架

### 文档资源
- [NESdev Wiki](https://www.nesdev.org/wiki/Nesdev_Wiki) - NES硬件权威文档
- [6502指令集](http://obelisk.me.uk/6502/) - CPU指令参考
- [CUDA编程指南](https://docs.nvidia.com/cuda/cuda-c-programming-guide/) - NVIDIA官方文档

### 测试ROM
- [nes-test-roms](https://github.com/christopherpow/nes-test-roms) - 公开测试ROM集合

---

## 🚀 快速开始

### 查看Phase 0成果
```bash
cd phases/phase0_research
cat README.md              # 阶段总结
cat tasks.md               # 任务清单
cat completion_report.md   # 完成报告
```

### 查看技术文档
```bash
cd docs
cat gpu_emulator_research.md    # 调研报告
cat reference_impl_choice.md    # 技术选型
cat rom_setup_guide.md          # ROM准备指南
```

### 运行CUDA测试
```bash
cd tests/unit
nvcc test_cuda.cu -o test_cuda
./test_cuda
```

---

## ⚠️ 风险与挑战

1. **PPU复杂度**: NES PPU远比Atari TIA复杂，渲染逻辑是瓶颈
2. **Warp Divergence**: GPU分支密集代码性能损失
3. **开发周期**: 预计3-6个月，期间无法训练
4. **GPL许可**: 代码必须开源（学术项目可接受）

### 放弃条件
- Phase 3单实例GPU无法在1个月内实现
- Phase 4批量并行速度不超过stable-retro的2倍
- Phase 6观察值与nes_py有显著差异，DT权重无法迁移

---

## 📝 许可证

本项目基于quickerNES移植，继承 **GPL-2.0** 许可证。

所有衍生代码必须以GPL-2.0开源。

---

## 🤝 贡献

本项目为研究项目，Phase by Phase推进。

详见各Phase的`tasks.md`查看待办事项。

---

**最后更新**: 2026-04-25  
**当前Phase**: Phase 1 准备中
