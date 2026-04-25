# Phase 2: NES PPU (Picture Processing Unit) Implementation

**Project**: NES GPU Emulator for RL Training  
**Phase**: Phase 2 - PPU Reference Implementation  
**Status**: ⏳ 待开始  
**Depends on**: Phase 1 (CPU) ✅ 完成  
**Estimated Time**: 3-4 weeks  
**Actual Time**: TBD

---

## 🎯 Phase Overview

### Goal
实现完整的NES PPU (Picture Processing Unit) 模拟器，使模拟器能够正确渲染Super Mario Bros画面。

### Success Criteria
- [ ] 完整的PPU寄存器实现 ($2000-$2007)
- [ ] 背景渲染 (256×240 分辨率)
- [ ] 精灵渲染 (最多64个精灵)
- [ ] 正确的滚动/镜像
- [ ] Scanline精确定时
- [ ] Super Mario Bros完整画面渲染正确
- [ ] 通过PPU测试ROM (sprite_hit, vbl_nmi等)
- [ ] 单元测试覆盖率 > 70%

---

## 📊 Task Breakdown

**Total: 6 Major Tasks**

| Task | Content | Est. Time | Priority | Status |
|------|---------|-----------|----------|--------|
| **2.1** | PPU寄存器和内存 | 3-4天 | 🔥 Critical | ⏳ Pending |
| **2.2** | 背景渲染系统 | 5-7天 | 🔥 Critical | ⏳ Pending |
| **2.3** | 精灵渲染系统 | 5-7天 | 🔥 Critical | ⏳ Pending |
| **2.4** | 镜像和滚动 | 2-3天 | 🟡 High | ⏳ Pending |
| **2.5** | Scanline定时 | 4-5天 | 🟡 High | ⏳ Pending |
| **2.6** | PPU测试验证 | 3-4天 | 🟢 Medium | ⏳ Pending |

**Total Estimated Time**: 22-30 days

---

## 🏗️ Architecture Design

### PPU Components

```
┌──────────────────────────────────────────────┐
│             NES PPU Architecture              │
├──────────────────────────────────────────────┤
│                                              │
│  ┌──────────────┐     ┌─────────────────┐  │
│  │ PPU Registers│◄───►│   CPU Interface │  │
│  │  ($2000-$2007)│     │  (via Memory)   │  │
│  └──────────────┘     └─────────────────┘  │
│         │                                    │
│         ▼                                    │
│  ┌──────────────────────────────────────┐  │
│  │        PPU Internal Memory            │  │
│  │  - Pattern Tables (8KB CHR)           │  │
│  │  - Name Tables (2KB VRAM)             │  │
│  │  - Palette (32 bytes)                 │  │
│  │  - OAM (256 bytes, 64 sprites)        │  │
│  └──────────────────────────────────────┘  │
│         │                    │              │
│         ▼                    ▼              │
│  ┌─────────────┐      ┌──────────────┐    │
│  │ Background  │      │   Sprites    │    │
│  │  Renderer   │      │   Renderer   │    │
│  └─────────────┘      └──────────────┘    │
│         │                    │              │
│         └────────┬───────────┘              │
│                  ▼                          │
│           ┌────────────┐                    │
│           │   Frame    │                    │
│           │  Buffer    │                    │
│           │ (256×240)  │                    │
│           └────────────┘                    │
│                                              │
└──────────────────────────────────────────────┘
```

### Key Data Structures

```cpp
// PPU主类
class PPU {
    // Registers (CPU可见)
    uint8_t ctrl;      // $2000 PPUCTRL
    uint8_t mask;      // $2001 PPUMASK
    uint8_t status;    // $2002 PPUSTATUS
    uint8_t oam_addr;  // $2003 OAMADDR
    
    // Internal memory
    uint8_t vram[2048];      // Name tables
    uint8_t palette[32];     // Palette RAM
    uint8_t oam[256];        // Sprite OAM
    
    // CHR (from mapper)
    const uint8_t* chr_rom;
    
    // Frame buffer
    uint32_t framebuffer[256 * 240];
    
    // Scanline/cycle counters
    int scanline;
    int cycle;
    
    // 渲染函数
    void render_background_scanline();
    void render_sprites_scanline();
    void evaluate_sprites();
};
```

---

## 📋 Detailed Task List

### Task 2.1: PPU Registers & Memory (3-4 days)

**Goal**: 实现PPU寄存器接口和内存系统

**Subtasks**:
1. 创建 `ppu.h/cpp` - PPU主类框架
2. 实现8个PPU寄存器:
   - $2000 PPUCTRL (控制)
   - $2001 PPUMASK (掩码)
   - $2002 PPUSTATUS (状态，读清除)
   - $2003 OAMADDR (OAM地址)
   - $2004 OAMDATA (OAM数据)
   - $2005 PPUSCROLL (滚动)
   - $2006 PPUADDR (VRAM地址)
   - $2007 PPUDATA (VRAM数据)
3. 实现内部寄存器:
   - v (当前VRAM地址)
   - t (临时VRAM地址)
   - x (fine X scroll)
   - w (写入开关)
4. PPU内存映射:
   - Pattern Tables ($0000-$1FFF, 来自CHR ROM)
   - Name Tables ($2000-$2FFF, VRAM + 镜像)
   - Palette ($3F00-$3FFF)
5. OAM (Object Attribute Memory):
   - 256字节 (64精灵 × 4字节)
   - OAM DMA ($4014寄存器)
6. 创建 `test_ppu_registers.cpp` (20+测试)

**Deliverables**:
- `src/reference/ppu/ppu.h` (~80 lines)
- `src/reference/ppu/ppu.cpp` (~150 lines)
- `tests/unit/test_ppu_registers.cpp` (~200 lines)

---

### Task 2.2: Background Rendering (5-7 days)

**Goal**: 实现NES背景渲染系统

**Subtasks**:
1. Name Table解析:
   - 读取32×30 tile索引
   - 处理4个name table镜像
2. Pattern Table查找:
   - 从CHR ROM获取8×8 tile图案
   - 支持2位颜色深度
3. Attribute Table解析:
   - 每4×4 tile的调色板选择
   - 2位调色板索引
4. 调色板查找:
   - 从palette RAM获取RGB颜色
   - 背景使用palette $00-$0F
5. 实现Fine X Scroll
6. Scanline渲染优化
7. 创建 `test_background.cpp`

**Deliverables**:
- `src/reference/ppu/background.cpp` (~200 lines)
- `tests/unit/test_background.cpp` (~150 lines)

**Key Algorithm**:
```cpp
void PPU::render_background_pixel(int x) {
    // 1. 获取tile索引
    uint16_t nt_addr = 0x2000 | (v & 0x0FFF);
    uint8_t tile_idx = vram_read(nt_addr);
    
    // 2. 获取tile图案
    uint16_t pattern_addr = (ctrl & 0x10) ? 0x1000 : 0x0000;
    pattern_addr += tile_idx * 16 + fine_y;
    uint8_t lo = chr_read(pattern_addr);
    uint8_t hi = chr_read(pattern_addr + 8);
    
    // 3. 获取调色板索引
    uint16_t at_addr = 0x23C0 | (v & 0x0C00) | ...;
    uint8_t palette_idx = (vram_read(at_addr) >> shift) & 0x03;
    
    // 4. 组合颜色
    uint8_t pixel = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1);
    uint8_t color_idx = palette[palette_idx * 4 + pixel];
    
    // 5. 写入framebuffer
    framebuffer[scanline * 256 + x] = NES_PALETTE[color_idx];
}
```

---

### Task 2.3: Sprite Rendering (5-7 days)

**Goal**: 实现NES精灵系统

**Subtasks**:
1. OAM解析:
   - 64个精灵 (Y, tile, attributes, X)
   - Sprite 0 特殊处理
2. Sprite评估:
   - Scanline最多8个精灵
   - 精灵溢出标志
3. 8×8 和 8×16 精灵模式
4. 精灵翻转 (水平/垂直)
5. 精灵优先级:
   - 前景/背景优先
   - OAM索引决定覆盖顺序
6. Sprite 0 Hit检测
7. 创建 `test_sprites.cpp`

**Deliverables**:
- `src/reference/ppu/sprites.cpp` (~250 lines)
- `tests/unit/test_sprites.cpp` (~180 lines)

**Key Features**:
```cpp
struct Sprite {
    uint8_t y;          // Y位置 - 1
    uint8_t tile;       // Tile索引
    uint8_t attr;       // 属性 (调色板、优先级、翻转)
    uint8_t x;          // X位置
};

void PPU::evaluate_sprites() {
    // 查找当前scanline上的精灵
    sprite_count = 0;
    for (int i = 0; i < 64 && sprite_count < 8; i++) {
        Sprite* spr = (Sprite*)&oam[i * 4];
        int row = scanline - spr->y;
        if (row >= 0 && row < sprite_height) {
            secondary_oam[sprite_count++] = *spr;
        }
    }
    if (sprite_count == 8 && /* 还有更多精灵 */) {
        status |= 0x20;  // 设置溢出标志
    }
}
```

---

### Task 2.4: Mirroring & Scrolling (2-3 days)

**Goal**: 实现镜像和滚动系统

**Subtasks**:
1. Name Table镜像模式:
   - Horizontal (Super Mario Bros)
   - Vertical
   - Single Screen
   - Four Screen
2. PPUSCROLL ($2005) 写入处理
3. PPUADDR ($2006) 与滚动交互
4. Coarse X/Y scroll
5. Fine Y scroll
6. 跨Name Table滚动
7. 创建 `test_scrolling.cpp`

**Deliverables**:
- 修改 `ppu.cpp` (+100 lines)
- `tests/unit/test_scrolling.cpp` (~120 lines)

**Mirroring Logic**:
```cpp
uint16_t PPU::mirror_address(uint16_t addr) {
    addr = (addr - 0x2000) & 0x0FFF;  // $2000-$2FFF
    switch (mirroring) {
        case HORIZONTAL:  // SMB使用
            return (addr / 2) & 0x3FF | (addr & 0x0400);
        case VERTICAL:
            return addr & 0x7FF;
        // ...
    }
}
```

---

### Task 2.5: Scanline Timing (4-5 days)

**Goal**: 实现周期精确的PPU定时

**Subtasks**:
1. 261 scanlines / frame:
   - Scanline 0-239: 可见
   - Scanline 240: Post-render
   - Scanline 241-260: VBlank
   - Scanline 261: Pre-render
2. 341 cycles / scanline
3. VBlank NMI触发:
   - Scanline 241, cycle 1
   - 检查 PPUCTRL bit 7
4. PPUSTATUS读取竞态:
   - 读取清除VBlank标志
   - NMI抑制窗口
5. Sprite 0 Hit定时
6. PPU-CPU同步:
   - PPU 3个周期 = CPU 1个周期
7. 创建 `test_timing.cpp`

**Deliverables**:
- 修改 `ppu.cpp` (+150 lines)
- `tests/unit/test_timing.cpp` (~100 lines)

**Timing Structure**:
```cpp
void PPU::tick() {
    if (scanline >= 0 && scanline <= 239) {
        // 可见scanline
        if (cycle >= 1 && cycle <= 256) {
            render_pixel(cycle - 1, scanline);
        }
        else if (cycle >= 257 && cycle <= 320) {
            // Sprite fetching for next scanline
        }
        else if (cycle >= 321 && cycle <= 336) {
            // Next tile prefetch
        }
    }
    else if (scanline == 241 && cycle == 1) {
        // 进入VBlank
        status |= 0x80;  // Set VBlank flag
        if (ctrl & 0x80) {
            trigger_nmi();  // 触发CPU NMI
        }
    }
    else if (scanline == 261) {
        // Pre-render scanline
        if (cycle == 1) {
            status &= ~0xE0;  // Clear VBlank, sprite0, overflow
        }
    }
    
    // 前进
    cycle++;
    if (cycle > 340) {
        cycle = 0;
        scanline++;
        if (scanline > 260) {
            scanline = 0;
            frame_complete = true;
        }
    }
}
```

---

### Task 2.6: Testing & Integration (3-4 days)

**Goal**: 全面测试和ROM验证

**Subtasks**:
1. 单元测试补全 (target 80%+ coverage)
2. PPU测试ROM:
   - `sprite_hit_tests_2005.10.05/`
   - `vbl_nmi_timing/`
   - `ppu_vbl_nmi/`
3. 集成测试:
   - 加载Super Mario Bros
   - 渲染第一帧
   - 验证画面正确性
4. 与CPU集成:
   - 正确的CPU-PPU同步
   - NMI中断触发
   - OAM DMA
5. 性能验证:
   - 单帧渲染时间 < 100ms (debug)
   - 无内存泄漏 (valgrind)
6. 文档完善

**Deliverables**:
- `tests/integration/test_smb_rendering.cpp` (~150 lines)
- `phases/phase2_ppu/PHASE2_SUMMARY.md`
- 更新 `CURRENT_STATUS.md`

---

## 🎨 NES Color Palette

需要定义标准NES调色板 (64色):

```cpp
// src/reference/ppu/palette.h
const uint32_t NES_PALETTE[64] = {
    0x666666, 0x002A88, 0x1412A7, 0x3B00A4, // $00-$03
    0x5C007E, 0x6E0040, 0x6C0600, 0x561D00, // $04-$07
    // ... (64 colors total)
};
```

---

## 📚 Reference Materials

### NESdev Wiki
- [PPU](https://www.nesdev.org/wiki/PPU)
- [PPU Registers](https://www.nesdev.org/wiki/PPU_registers)
- [PPU Rendering](https://www.nesdev.org/wiki/PPU_rendering)
- [PPU Scrolling](https://www.nesdev.org/wiki/PPU_scrolling)
- [PPU OAM](https://www.nesdev.org/wiki/PPU_OAM)

### Test ROMs
- [ppu_vbl_nmi](https://github.com/christopherpow/nes-test-roms/tree/master/ppu_vbl_nmi)
- [sprite_hit_tests](https://github.com/christopherpow/nes-test-roms/tree/master/sprite_hit_tests_2005.10.05)
- [scroll_test](https://github.com/christopherpow/nes-test-roms/tree/master/scroll_test)

### Source Code References
- [quickerNES Ppu.cpp](https://github.com/SergioMartin86/quickerNES/blob/main/source/quickerNES/core/Ppu.cpp)
- [FCEUX PPU](https://github.com/TASEmulators/fceux/blob/master/src/ppu.cpp)

---

## 📊 Expected Metrics

### Code Statistics (Estimate)
- **Source Code**: ~1200 lines
  - ppu.cpp: ~500 lines
  - background.cpp: ~250 lines
  - sprites.cpp: ~300 lines
  - palette.h: ~80 lines
  - Other: ~70 lines

- **Test Code**: ~800 lines
  - test_ppu_registers.cpp: ~200 lines
  - test_background.cpp: ~150 lines
  - test_sprites.cpp: ~180 lines
  - test_scrolling.cpp: ~120 lines
  - test_timing.cpp: ~100 lines
  - test_integration.cpp: ~50 lines

- **Total**: ~2000 lines

### Test Coverage
- Target: 80%+ coverage
- Unit tests: 50-60 tests
- Integration tests: 5-8 ROM tests

### Performance (Reference Impl)
- Single frame render: < 100ms (debug)
- 60 fps achievable in release build
- Memory footprint: < 2MB per instance

---

## 🔗 Integration Points

### With Phase 1 (CPU)
```cpp
// CPU调用PPU
ppu.write_register(addr, value);  // $2000-$2007
uint8_t status = ppu.read_register(addr);

// PPU触发CPU中断
if (ppu.nmi_triggered()) {
    cpu.execute_nmi();
}

// CPU执行OAM DMA
ppu.oam_dma(cpu.memory, start_addr);
```

### With Phase 3 (CUDA)
- 所有数据结构设计考虑GPU友好:
  - SoA (Structure of Arrays) 布局
  - 避免指针/虚函数
  - 固定大小数组
- 清晰的函数分离 (便于kernel化)

---

## ⚠️ Known Challenges

1. **PPUADDR/PPUSCROLL复杂性**:
   - 共享内部寄存器 v/t
   - 写入顺序影响行为
   - 需要精确模拟

2. **Sprite 0 Hit**:
   - 时序敏感
   - 多种边缘情况
   - Super Mario Bros依赖此功能

3. **镜像模式**:
   - 不同游戏使用不同镜像
   - 需要从mapper获取信息

4. **性能优化**:
   - Reference实现注重正确性
   - GPU版本才关注极致性能

---

## 📝 Progress Tracking

- **Daily Updates**: `phases/phase2_ppu/progress.md`
- **Work Logs**: `phases/phase2_ppu/work_log_*.md`
- **SQL Database**: Track tasks in `todos` table

---

**Phase 2 Start Date**: TBD  
**Phase 2 Target Completion**: TBD  
**Phase 2 Actual Completion**: TBD

**Phase Owner**: GitHub Copilot + User  
**Last Updated**: 2026-04-26
