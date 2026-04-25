# CPU参考实现选择方案

**状态**: ✅ 已决策  
**日期**: 2026-04-25

---

## 候选方案对比

| 维度 | fceux | nestopia | quickerNES | LaiNES |
|------|-------|----------|------------|---------|
| **代码量** | ~50K LOC | ~40K LOC | ~15K LOC | ~3K LOC |
| **语言** | C++ | C++ | C++ | C++ |
| **许可证** | GPL-2.0 | GPL-2.0 | GPL-2.0 | MIT ✅ |
| **CPU核心** | 复杂 | 复杂 | 优化精简 | 极简 |
| **PPU实现** | 完整 | 完整 | 完整 | 基础 |
| **Mapper支持** | 200+ | 100+ | 30+ | 5个 |
| **代码可读性** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **性能优化** | 中等 | 高 | 极高 ✅ | 低 |

---

## ✅ 最终选择: **quickerNES**

### 选择理由

1. **代码量适中** (~15K LOC)
   - CPU: ~2000行 (cpu.hpp, cpuFlat.cpp)
   - PPU: ~3000行 (ppu/*.cpp)
   - 不像fceux那样庞大，也不像LaiNES太简陋

2. **性能已优化**
   - 专门为TASing和botting优化
   - CPU指令分页对齐，减少cache miss
   - 强制little-endian优化（与我们目标一致）

3. **结构清晰**
   - Header-only设计便于编译器优化
   - 模块化良好（cpu/ppu/mapper分离）

4. **活跃维护**
   - 2024年仍在更新
   - 有完善的测试ROM集

5. **Mapper支持足够**
   - Super Mario Bros只需Mapper 0 (NROM)
   - quickerNES支持30+个mapper，绰绰有余

### 许可证分析

- **quickerNES**: GPL-2.0
- **影响**: 我们的GPU移植版本也必须GPL-2.0开源
- **接受理由**: 
  * 本项目是学术研究，开源无妨
  * GPL-2.0允许商用（只要开源代码）
  * 符合学术透明度原则

**备选**: 如果未来需要MIT许可，可以从LaiNES移植，但需补充很多功能

---

## 实施计划

### Phase 1: 移植quickerNES CPU核心

**关键文件**:
```
source/quickerNES/core/
├── cpu.hpp              # CPU接口定义
├── cpuFlat.cpp          # Flat模式6502实现
├── cpuPaged.cpp         # Paged模式（可选）
├── core.hpp             # 内存映射
└── cart.hpp             # Cartridge加载
```

**工作量**: 2-3周

### Phase 2: 移植quickerNES PPU核心

**关键文件**:
```
source/quickerNES/core/ppu/
├── ppu.hpp              # PPU接口
├── ppuImpl.cpp          # PPU核心逻辑
├── ppuRendering.cpp     # 渲染逻辑
└── ppuSprites.hpp       # 精灵处理
```

**工作量**: 3-4周

---

## 参考资料

- quickerNES源码: https://github.com/SergioMartin86/quickerNES
- quickNES原版: https://github.com/kode54/QuickNES
- LaiNES: https://github.com/AndreaOrru/LaiNES
