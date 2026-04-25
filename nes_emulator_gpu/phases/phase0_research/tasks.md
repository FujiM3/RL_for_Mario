# Phase 0 任务清单

## 任务0.1: 调研GPU模拟器实现 ✅
- [x] 搜索学术论文和开源项目
- [x] 分析cuLE (CUDA Atari)架构
- [x] 研究EnvPool/WarpDrive/Madrona
- [x] 输出调研报告

**产出**: `docs/gpu_emulator_research.md`

---

## 任务0.2: 选择CPU参考实现 ✅
- [x] 对比fceux/nestopia/quickerNES/LaiNES
- [x] 评估代码量和许可证
- [x] 决定使用quickerNES
- [x] 输出方案选择文档

**决策**: quickerNES (GPL-2.0, ~15K LOC)

---

## 任务0.3: 验证CUDA环境 ✅
- [x] 确认nvcc可用 (CUDA 12.4)
- [x] 检测GPU (Tesla V100-32GB × 10)
- [x] 编译测试CUDA程序
- [x] 验证计算能力7.0

**环境**: GPU 2 (最空闲), 80 SM, 32GB显存

---

## 任务0.4: ROM文件准备 ✅
- [x] 下载nes-test-roms (67个测试套件)
- [x] 获取11个CPU指令测试ROM
- [x] 准备PPU测试ROM
- [x] 创建ROM获取指南
- [ ] Super Mario Bros ROM (用户自行提供)

**ROM清单**:
- CPU测试: 01-implied.nes ~ 11-special.nes
- PPU测试: ppu_vbl_nmi, sprite_hit_tests等
- 训练ROM: smb.nes (待提供)

---

## 任务0.5: 完善项目结构 ✅
- [x] 创建src/reference目录
- [x] 创建src/cuda目录
- [x] 创建tests目录
- [x] 创建docs目录
- [x] 设置.gitignore

**结构**: 完全按照设计实现

---

## 总结
- **完成任务**: 5/5
- **验收通过**: 100%
- **下一步**: Phase 1 - 6502 CPU实现
