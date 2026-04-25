# Phase 1: CPU参考实现 - 6502 CPU模拟器

**状态**: 🚧 进行中  
**开始日期**: 2026-04-25  
**预计时间**: 2-3周  
**实际耗时**: TBD

---

## 🎯 阶段目标

实现完整的6502 CPU模拟器（C++），作为后续GPU移植的参考实现。

### 核心任务
1. 实现6502寄存器模型 (A, X, Y, SP, PC, P)
2. 实现13种寻址模式
3. 实现所有官方指令 (56条) + 部分非官方指令
4. 实现NES内存映射
5. 实现Mapper 0 (NROM)
6. 实现中断处理 (NMI, IRQ, Reset)
7. 通过nestest.nes和blargg测试

---

## 📋 验收标准

| 标准 | 状态 | 备注 |
|------|------|------|
| 通过11个CPU指令测试ROM | ⏳ | nes_instr_test/rom_singles/ |
| 单元测试覆盖率 > 80% | ⏳ | 每条指令至少5个测试 |
| CPU单核运行SMB 1帧 < 50ms | ⏳ | 不含PPU |
| 代码可读性良好 | ⏳ | 注释 + 文档 |
| 无内存泄漏 | ⏳ | valgrind检查 |

**验收**: 全部通过后进入Phase 2

---

## 📂 产出文件

### src/reference/cpu/
- `cpu_6502.h` - CPU接口定义
- `cpu_6502.cpp` - CPU核心实现
- `registers.h` - 寄存器定义
- `instructions.cpp` - 指令实现
- `addressing.cpp` - 寻址模式
- `interrupts.cpp` - 中断处理

### src/reference/common/
- `memory.h/cpp` - 内存映射
- `mapper0.h/cpp` - Mapper 0实现
- `types.h` - 通用类型定义

### tests/unit/
- `test_cpu_registers.cpp`
- `test_addressing_modes.cpp`
- `test_instructions.cpp`
- `test_memory_map.cpp`
- `test_nestest.cpp` - 关键测试

---

## 🔄 当前进度

**总体进度**: 0% (刚启动)

详见: [`progress.md`](progress.md) 查看实时进度

---

## 📚 参考资料

- [NESdev Wiki - CPU](https://www.nesdev.org/wiki/CPU)
- [6502指令集参考](http://obelisk.me.uk/6502/)
- [quickerNES CPU实现](https://github.com/SergioMartin86/quickerNES/tree/main/source/quickerNES/core)
- [nestest ROM](../../tests/integration/nes-test-roms/)

---

**最后更新**: 2026-04-25  
**负责人**: AI Assistant
