# NES GPU模拟器 - 目录结构说明

**最后更新**: 2026-04-25

---

## 📁 完整目录树

```
nes_emulator_gpu/
│
├── �� README.md             # 项目总览
├── 📄 LICENSE               # GPL-2.0许可证
├── 📄 .gitignore            # Git忽略规则
├── 📄 STRUCTURE.md          # 本文件
│
├── 📚 docs/                 # 技术文档
│   ├── gpu_emulator_research.md    # GPU模拟器调研报告
│   ├── reference_impl_choice.md    # 参考实现选择方案
│   └── rom_setup_guide.md          # ROM文件获取指南
│
├── 📊 phases/               # 7个Phase任务追踪
│   ├── phase0_research/              # ✅ 已完成
│   │   ├── README.md                 # Phase 0总结
│   │   ├── tasks.md                  # 任务清单
│   │   └── completion_report.md      # 完成报告
│   ├── phase1_cpu/                   # ⏳ 待开始
│   ├── phase2_ppu/
│   ├── phase3_cuda_single/
│   ├── phase4_cuda_batch/
│   ├── phase5_python/
│   └── phase6_integration/
│
├── 💻 src/                  # 源代码
│   ├── reference/           # Phase 1-2: C++ CPU参考实现
│   │   ├── cpu/             # 6502 CPU模拟器
│   │   ├── ppu/             # PPU图形渲染
│   │   └── common/          # 公共代码
│   ├── cuda/                # Phase 3-4: CUDA GPU实现
│   │   ├── kernels/         # CUDA kernel
│   │   └── device/          # Device函数
│   └── python/              # Phase 5: Python绑定
│
├── 🧪 tests/                # 测试
│   ├── roms/                # 测试ROM (11个CPU测试 + SMB)
│   │   ├── 01-implied.nes ~ 11-special.nes
│   │   └── README.md
│   ├── unit/                # 单元测试
│   │   ├── test_cuda.cu     # CUDA环境测试
│   │   └── README.md
│   └── integration/         # 集成测试
│       ├── nes-test-roms/   # 67个公开测试ROM套件
│       └── README.md
│
└── 📈 benchmarks/           # 性能测试
    ├── cpu_baseline/        # CPU基准性能
    └── gpu_profile/         # GPU性能分析
```

---

## 📂 目录说明

### 根目录文件
- `README.md` - 项目总览，当前状态，快速开始
- `LICENSE` - GPL-2.0许可证（继承quickerNES）
- `.gitignore` - 排除ROM文件，build目录等
- `STRUCTURE.md` - 本文件，详细的目录结构说明

### docs/ - 技术文档
设计决策和技术调研文档，**不随代码变化**

| 文件 | 内容 |
|------|------|
| `gpu_emulator_research.md` | GPU模拟器调研报告，cuLE分析 |
| `reference_impl_choice.md` | 为什么选择quickerNES |
| `rom_setup_guide.md` | ROM文件获取和使用指南 |

### phases/ - Phase任务追踪
每个Phase的**进度追踪和验收文档**

每个Phase目录包含:
- `README.md` - 阶段目标、验收标准、当前状态
- `tasks.md` - 详细任务清单（checkbox）
- `progress.md` / `completion_report.md` - 进度或完成报告

### src/ - 源代码
按**功能模块**和**开发阶段**分层

| 目录 | Phase | 用途 |
|------|-------|------|
| `src/reference/cpu/` | 1 | 6502 CPU模拟器（C++） |
| `src/reference/ppu/` | 2 | PPU图形渲染（C++） |
| `src/reference/common/` | 1-2 | 公共工具函数 |
| `src/cuda/kernels/` | 3-4 | CUDA kernel实现 |
| `src/cuda/device/` | 3-4 | CUDA device函数 |
| `src/python/` | 5 | Python绑定（pybind11） |

### tests/ - 测试
按**测试类型**分类

| 目录 | 内容 |
|------|------|
| `tests/roms/` | 11个CPU测试ROM + SMB训练ROM |
| `tests/unit/` | 单元测试（test_*.cu, test_*.cpp） |
| `tests/integration/` | 集成测试（使用真实ROM验证） |

### benchmarks/ - 性能测试
性能基准和优化分析

| 目录 | 用途 |
|------|------|
| `benchmarks/cpu_baseline/` | CPU版本性能基准 |
| `benchmarks/gpu_profile/` | GPU性能分析（nsight-compute） |

---

## 🔄 文件流转

### Phase 1 (CPU实现)
1. 参考 `docs/reference_impl_choice.md`
2. 在 `src/reference/cpu/` 编写代码
3. 在 `tests/unit/` 编写单元测试
4. 用 `tests/roms/` 中的11个ROM验证
5. 更新 `phases/phase1_cpu/progress.md`

### Phase 2 (PPU实现)
1. 在 `src/reference/ppu/` 编写代码
2. 用 `tests/integration/nes-test-roms/ppu_*` 验证
3. 截屏对比fceux输出
4. 更新 `phases/phase2_ppu/completion_report.md`

### Phase 3-4 (CUDA移植)
1. 在 `src/cuda/` 编写CUDA代码
2. 用 `benchmarks/` 进行性能测试
3. 逐步对比CPU版本输出
4. 更新对应Phase的文档

---

## 📝 命名规范

### 文件命名
- C/C++源文件: `snake_case.cpp`, `snake_case.h`
- CUDA文件: `snake_case.cu`, `snake_case.cuh`
- Python文件: `snake_case.py`
- 文档: `kebab-case.md`

### 目录命名
- 功能模块: `snake_case`（如 `cpu_baseline`）
- Phase目录: `phaseN_name`（如 `phase1_cpu`）

---

## 🎯 设计原则

1. **模块化**: 每个Phase独立开发和测试
2. **可追溯**: 完整的文档和决策记录
3. **可验证**: 每个阶段都有明确的验收标准
4. **可重用**: 参考实现和CUDA实现分离

---

**维护**: 随项目进展更新  
**查看**: `cat STRUCTURE.md`
