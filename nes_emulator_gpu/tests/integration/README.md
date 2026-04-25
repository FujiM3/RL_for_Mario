# NES GPU模拟器 - 集成测试

本目录包含集成测试，使用真实的NES测试ROM验证模拟器正确性。

## 测试ROM集合

### nes-test-roms/
公开可用的NES测试ROM集合（67个测试套件）

**来源**: https://github.com/christopherpow/nes-test-roms

**许可**: 多数为公开域或MIT

---

## 关键测试集

### CPU测试
- `nes_instr_test/` - blargg的CPU指令测试 (11个ROM)
- `cpu_dummy_reads/` - CPU虚读测试
- `cpu_exec_space/` - CPU执行空间测试

### PPU测试
- `ppu_vbl_nmi/` - VBlank和NMI时序
- `sprite_hit_tests_2005.10.05/` - 精灵0命中检测
- `sprite_overflow_tests/` - 精灵溢出
- `ppu_open_bus/` - PPU总线行为

### APU测试
- `apu_test/` - 音频处理单元测试
- `blargg_apu_2005.07.30/` - APU时序测试

---

## 运行测试 (Phase 1-2后)

```bash
# 运行单个CPU测试
cd ../.. && ./nes_emulator nes-test-roms/nes_instr_test/rom_singles/01-implied.nes

# 运行所有CPU指令测试
./run_cpu_tests.sh

# 运行PPU测试
./run_ppu_tests.sh
```

---

## 测试通过标准

### Phase 1 (CPU)
- ✅ 11个指令测试ROM全部通过
- ✅ CPU虚读测试通过
- ✅ 执行空间测试通过

### Phase 2 (PPU)
- ✅ VBlank时序测试通过
- ✅ 精灵0命中检测通过
- ✅ PPU渲染与fceux像素级一致

---

**最后更新**: 2026-04-25  
**状态**: 测试ROM已就绪，测试脚本待Phase 1-2实现
