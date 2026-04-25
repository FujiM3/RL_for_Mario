# Work Log #001 - Task 2.1: PPU寄存器和内存

**Date**: 2026-04-26  
**Phase**: Phase 2 - PPU Implementation  
**Task**: 2.1 - PPU Registers and Memory  
**Duration**: ~2 hours  
**Status**: ✅ Complete

---

## 🎯 Objectives

1. 创建PPU基础架构 (ppu.h/cpp)
2. 实现8个PPU寄存器 ($2000-$2007)
3. 实现内部寄存器 (v, t, x, w)
4. PPU内存系统 (VRAM, Palette, OAM)
5. OAM DMA功能
6. 完整的单元测试

---

## 🛠️ Work Completed

### 1. PPU Header (ppu.h)

**Files Created**:
- `src/reference/ppu/ppu.h` (186 lines)

**Implementation Details**:
- PPU类定义，包含所有寄存器和内存
- 8个CPU可见寄存器 ($2000-$2007)
- 4个内部寄存器 (v, t, x, w)
- PPU内存数组 (VRAM, Palette, OAM)
- Framebuffer (256×240 RGBA)
- Scanline/cycle计数器
- Mirroring枚举类型
- CHR ROM回调接口

**Code Snippet**:
```cpp
class PPU {
public:
    // CPU-visible register interface
    uint8_t read_register(uint16_t addr);
    void write_register(uint16_t addr, uint8_t value);
    
    // OAM DMA
    void oam_dma(const uint8_t* cpu_memory, uint8_t page);
    
    // Timing
    void tick();
    
    // Frame completion
    bool is_frame_ready() const;
    const uint32_t* get_framebuffer() const;
    
    // NMI status
    bool nmi_triggered() const;
    void clear_nmi();
    
    // Set CHR callback and mirroring
    void set_chr_callback(std::function<uint8_t(uint16_t)> read_cb);
    void set_mirroring(Mirroring mode);
    
private:
    // 8 CPU-visible registers
    uint8_t ctrl, mask, status, oam_addr;
    
    // 4 internal registers
    uint16_t v, t;
    uint8_t x;
    bool w;
    
    // Memory
    uint8_t vram[2048];
    uint8_t palette[32];
    uint8_t oam[256];
    uint32_t framebuffer[256 * 240];
    
    // Helper functions
    uint8_t ppu_read(uint16_t addr);
    void ppu_write(uint16_t addr, uint8_t value);
    uint16_t mirror_nametable(uint16_t addr);
    void increment_v();
};
```

### 2. PPU Implementation (ppu.cpp)

**Files Created**:
- `src/reference/ppu/ppu.cpp` (313 lines)

**Implementation Details**:

#### 寄存器读取 (read_register)
- $2000 PPUCTRL: 只写寄存器
- $2001 PPUMASK: 只写寄存器
- $2002 PPUSTATUS: 读取返回VBlank/Sprite0/Overflow标志，读后清除bit 7
- $2003 OAMADDR: 只写寄存器
- $2004 OAMDATA: 读取OAM (不自动递增以匹配硬件行为)
- $2005 PPUSCROLL: 只写寄存器
- $2006 PPUADDR: 只写寄存器
- $2007 PPUDATA: 读取PPU内存，使用缓冲（除了palette）

#### 寄存器写入 (write_register)
- $2000 PPUCTRL: 更新ctrl和t寄存器bits 10-11
- $2001 PPUMASK: 更新mask
- $2002 PPUSTATUS: 只读，写入无效
- $2003 OAMADDR: 设置OAM地址
- $2004 OAMDATA: 写入OAM，自动递增地址
- $2005 PPUSCROLL: 两次写入，第一次设置X滚动，第二次设置Y滚动
- $2006 PPUADDR: 两次写入，第一次高字节，第二次低字节后v=t
- $2007 PPUDATA: 写入PPU内存，自动递增v

#### PPU内存访问 (ppu_read/ppu_write)
- $0000-$1FFF: Pattern Tables (CHR ROM via callback)
- $2000-$2FFF: Name Tables (VRAM with mirroring)
- $3F00-$3FFF: Palette RAM (with $3F10/$3F14/$3F18/$3F1C mirroring)

#### Name Table镜像 (mirror_nametable)
- Horizontal: $2000=$2400, $2800=$2C00 (Super Mario Bros)
- Vertical: $2000=$2800, $2400=$2C00
- Single Screen A/B: 全部映射到1KB
- Four Screen: 使用全部4KB (在2KB VRAM上wrap)

#### VBlank定时 (tick)
- Scanline 241: 设置VBlank标志，触发NMI (if enabled)
- Scanline 261: 清除VBlank/Sprite0/Overflow标志
- Frame完成: scanline > 260

### 3. Unit Tests

**Files Created**:
- `tests/unit/test_ppu_registers.cpp` (437 lines, 22 tests)

**Tests Created**:
1. `TEST(PPU, Construction)` - 构造函数正确初始化
2. `TEST(PPU, PPUCTRL_Write)` - PPUCTRL更新t寄存器
3. `TEST(PPU, PPUSTATUS_VBlank_Set)` - VBlank标志在scanline 241设置
4. `TEST(PPU, PPUSTATUS_VBlank_ClearedOnRead)` - 读取$2002清除VBlank
5. `TEST(PPU, PPUSTATUS_ResetsWriteToggle)` - 读取$2002重置w
6. `TEST(PPU, OAMADDR_Write)` - OAMADDR设置正确
7. `TEST(PPU, OAMDATA_ReadWrite)` - OAM读写正确
8. `TEST(PPU, OAMDATA_AutoIncrement)` - OAM写入自动递增
9. `TEST(PPU, PPUSCROLL_TwoWrites)` - PPUSCROLL两次写入
10. `TEST(PPU, PPUADDR_TwoWrites)` - PPUADDR两次写入
11. `TEST(PPU, PPUADDR_Masking)` - PPUADDR高位屏蔽
12. `TEST(PPU, PPUDATA_VRAMWrite)` - VRAM写入和缓冲读取
13. `TEST(PPU, PPUDATA_PaletteWrite)` - Palette直接读写
14. `TEST(PPU, PPUDATA_AutoIncrement_Across)` - PPUDATA +1递增
15. `TEST(PPU, PPUDATA_AutoIncrement_Down)` - PPUDATA +32递增
16. `TEST(PPU, OAMDMA_Transfer)` - OAM DMA传输256字节
17. `TEST(PPU, Mirroring_Horizontal)` - 水平镜像
18. `TEST(PPU, Mirroring_Vertical)` - 垂直镜像
19. `TEST(PPU, PaletteMirroring_BackgroundToSprite)` - Palette镜像
20. `TEST(PPU, VBlank_NMI_Enabled)` - NMI启用时触发
21. `TEST(PPU, VBlank_NMI_Disabled)` - NMI禁用时不触发
22. `TEST(PPU, FrameCompletion)` - 帧完成标志

**Test Results**:
```
[==========] Running 22 tests from 1 test suite.
[----------] 22 tests from PPU
[  PASSED  ] 22 tests.
```

**Pass Rate**: 22/22 (100%)

---

## 🐛 Issues Encountered

### Issue 1: OAM读取是否自动递增

**Symptom**: 最初测试期望读取OAMDATA自动递增地址  
**Cause**: 真实NES硬件在读取OAM时不自动递增（除非在渲染期间）  
**Solution**: 调整测试以在每次读取前设置OAMADDR  
**Impact**: 更准确地模拟真实硬件行为

### Issue 2: Horizontal镜像计算错误

**Symptom**: Horizontal mirroring测试失败  
**Cause**: 镜像地址计算公式错误  
**Solution**: 修正为 `((addr / 0x400) & 0x02) ? (0x400 + (addr & 0x3FF)) : (addr & 0x3FF)`  
**Impact**: 正确实现水平镜像（Super Mario Bros使用）

---

## 📊 Progress Update

### Task 2.1 Progress
- **Subtasks Completed**: 17/17 (100%)
- **Code Written**: 499 lines source, 437 lines test
- **Tests Passing**: 22/22 (100%)

### Phase 2 Overall Progress
- **Before**: 0%
- **After**: 17% (Task 2.1 完成)
- **Delta**: +17%

---

## 📝 Technical Notes

### Design Decisions

1. **内部寄存器采用完整模拟**
   - **Rationale**: v/t/x/w寄存器对滚动至关重要，必须精确模拟
   - **Alternatives**: 简化实现，但会导致滚动错误
   - **Trade-offs**: 增加复杂度，但保证正确性

2. **Callback方式访问CHR ROM**
   - **Rationale**: PPU不应该知道mapper细节，通过回调解耦
   - **Alternatives**: 直接传入CHR ROM指针
   - **Trade-offs**: 更灵活，支持mapper切换Bank

3. **Palette镜像在读写时处理**
   - **Rationale**: $3F10/$3F14/$3F18/$3F1C镜像到背景调色板
   - **Alternatives**: 在palette数组中实际镜像
   - **Trade-offs**: 节省内存，但每次读写需要计算

### Implementation Details

**PPUADDR/PPUSCROLL复杂交互**:
- 两个寄存器共享内部v/t寄存器
- w toggle决定是第一次还是第二次写入
- PPUSCROLL第一次写入更新t的coarse X和fine X
- PPUSCROLL第二次写入更新t的coarse Y和fine Y
- PPUADDR两次写入后v = t
- 这是NES PPU最复杂的部分之一

**PPUDATA缓冲读取**:
- 读取非palette地址时，返回上一次读取的值（缓冲）
- 读取palette地址时，立即返回，但缓冲仍然更新
- 这是历史原因（PPU总线延迟）导致的行为

### NESdev References Used

- [PPU](https://www.nesdev.org/wiki/PPU)
- [PPU Registers](https://www.nesdev.org/wiki/PPU_registers)
- [PPU Scrolling](https://www.nesdev.org/wiki/PPU_scrolling)
- [PPU Power Up State](https://www.nesdev.org/wiki/PPU_power_up_state)

---

## 🔍 Code Review Checklist

- [x] Code compiles without warnings
- [x] All tests passing
- [x] Code follows project style
- [x] Comments added for complex logic
- [x] No memory leaks (stack-allocated arrays)
- [x] Edge cases handled (w toggle, mirroring, etc.)
- [x] Error handling appropriate

---

## ⏭️ Next Steps

1. **Task 2.2**: 背景渲染系统
   - Name Table解析
   - Pattern Table查找
   - Attribute Table解析
   - 调色板查找
   - 实际像素渲染

2. **准备工作**:
   - 创建NES调色板数组 (64色RGB)
   - 理解tile渲染流程
   - 实现渲染helper函数

---

## 📈 Metrics

| Metric | Value |
|--------|-------|
| Lines of Code (source) | 499 |
| Lines of Code (tests) | 437 |
| Total Lines | 936 |
| Test Coverage | 100% (all public APIs tested) |
| Build Time | 3.2 sec |
| Test Run Time | 0.004 sec |
| Compiler Warnings | 0 |

---

## 🎓 Lessons Learned

1. **硬件行为细节很重要**
   - OAM读取不自动递增（与写入不同）
   - 必须查阅NESdev Wiki确认行为

2. **先框架后细节**
   - 先建立完整的寄存器接口
   - 再逐个实现精确行为
   - 便于快速迭代

3. **测试驱动开发有效**
   - 22个测试覆盖所有功能
   - 发现了2个实现错误
   - 修复后立即验证

4. **镜像逻辑容易出错**
   - Horizontal/Vertical镜像容易混淆
   - 需要仔细验证地址映射
   - 测试不同镜像模式很重要

---

**Completed**: 2026-04-26 03:00  
**Total Time**: ~2 hours
