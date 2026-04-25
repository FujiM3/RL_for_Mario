# PPU API集成指南

**文档版本**: 1.0  
**创建日期**: 2024-04-25  
**适用PPU版本**: Phase 2完整实现

---

## 📋 概述

本文档详细说明如何将PPU集成到完整的NES模拟器中，包括CPU同步、内存映射、Mapper连接等。

### 目标读者

- NES模拟器开发者
- GPU移植实现者
- 系统集成工程师

### 前置知识

- NES硬件架构基础
- CPU 6502指令集
- C++面向对象编程

---

## 🏗️ PPU类架构

### 核心类定义

```cpp
class PPU {
public:
    // ===== 构造和初始化 =====
    PPU();
    ~PPU();
    void reset();
    
    // ===== 时钟驱动 =====
    void tick();                    // 执行1个PPU cycle
    
    // ===== CPU接口（寄存器访问） =====
    uint8_t read_register(uint16_t addr);   // $2000-$3FFF
    void write_register(uint16_t addr, uint8_t value);
    
    // ===== CHR ROM/RAM访问（需Mapper实现） =====
    std::function<uint8_t(uint16_t)> chr_read;   // Callback
    std::function<void(uint16_t, uint8_t)> chr_write;
    
    // ===== Mirroring配置 =====
    enum MirroringMode {
        HORIZONTAL,     // 垂直滚动游戏（Super Mario Bros）
        VERTICAL,       // 水平滚动游戏
        SINGLE_A,       // 单屏幕A
        SINGLE_B        // 单屏幕B
    };
    void set_mirroring(MirroringMode mode);
    
    // ===== NMI和Frame状态 =====
    bool get_nmi_flag() const;       // NMI pending？
    void clear_nmi_flag();           // 清除NMI标志
    bool is_frame_ready() const;     // Frame完成？
    void clear_frame_ready();        // 清除frame标志
    
    // ===== 渲染输出 =====
    const uint32_t* get_framebuffer() const;  // 256×240 RGBA
    
    // ===== 内存访问（调试/测试） =====
    uint8_t read_oam(uint8_t addr);
    void write_oam(uint8_t addr, uint8_t value);
    uint8_t ppu_read(uint16_t addr);
    void ppu_write(uint16_t addr, uint8_t value);
    
private:
    // 内部实现...
};
```

---

## 🔌 集成步骤

### Step 1: 创建PPU实例

```cpp
#include "ppu/ppu.h"

// 创建PPU
nes::PPU ppu;

// Reset到初始状态
ppu.reset();
```

### Step 2: 配置Mirroring

```cpp
// 从ROM header或Mapper获取mirroring模式
bool is_vertical = rom.is_vertical_mirroring();

if (is_vertical) {
    ppu.set_mirroring(nes::PPU::VERTICAL);
} else {
    ppu.set_mirroring(nes::PPU::HORIZONTAL);
}
```

**Mirroring说明**:
- **HORIZONTAL**: Nametable 0/1水平镜像，2/3水平镜像（垂直滚动）
- **VERTICAL**: Nametable 0/2垂直镜像，1/3垂直镜像（水平滚动）
- **SINGLE_A/B**: 所有nametable映射到同一块（无滚动）

### Step 3: 连接Mapper CHR访问

```cpp
// 假设已有Mapper实例
Mapper0 mapper(prg_rom, chr_rom);

// 连接CHR read回调
ppu.chr_read = [&mapper](uint16_t addr) -> uint8_t {
    return mapper.read_chr(addr);
};

// 连接CHR write回调（如果是CHR RAM）
ppu.chr_write = [&mapper](uint16_t addr, uint8_t value) {
    mapper.write_chr(addr, value);
};
```

**CHR地址空间**: $0000-$1FFF (8KB)
- $0000-$0FFF: Pattern table 0
- $1000-$1FFF: Pattern table 1

### Step 4: 连接CPU内存映射

```cpp
uint8_t cpu_read(uint16_t addr) {
    // PPU寄存器: $2000-$3FFF (每8字节镜像)
    if (addr >= 0x2000 && addr < 0x4000) {
        return ppu.read_register(addr);
    }
    
    // 其他内存区域...
    return 0;
}

void cpu_write(uint16_t addr, uint8_t value) {
    // PPU寄存器: $2000-$3FFF (每8字节镜像)
    if (addr >= 0x2000 && addr < 0x4000) {
        ppu.write_register(addr, value);
        return;
    }
    
    // 其他内存区域...
}
```

**寄存器映射**:
```
$2000 = PPUCTRL    (写)
$2001 = PPUMASK    (写)
$2002 = PPUSTATUS  (读)
$2003 = OAMADDR    (写)
$2004 = OAMDATA    (读/写)
$2005 = PPUSCROLL  (写×2)
$2006 = PPUADDR    (写×2)
$2007 = PPUDATA    (读/写)

$2008-$3FFF = 镜像
```

---

## ⏱️ CPU-PPU时钟同步

### 时钟关系

**NES时钟频率**:
- CPU: 1.789773 MHz (~559 ns/cycle)
- PPU: 5.369318 MHz (~186 ns/cycle)
- **比例**: PPU = CPU × 3

**Frame timing**:
- PPU: 262 scanlines × 341 cycles = 89,342 cycles/frame
- CPU: 89,342 ÷ 3 = 29,780.67 cycles/frame
- 60.0988 FPS (NTSC)

### 同步方案1: 严格同步

```cpp
void run_one_instruction() {
    // 1. CPU执行一条指令
    int cpu_cycles = cpu.step();
    
    // 2. PPU执行对应的cycles（3倍）
    for (int i = 0; i < cpu_cycles * 3; i++) {
        ppu.tick();
        
        // 3. 检查NMI（VBlank中断）
        if (ppu.get_nmi_flag()) {
            cpu.trigger_nmi();
            ppu.clear_nmi_flag();
        }
    }
    
    // 4. 检查Frame完成
    if (ppu.is_frame_ready()) {
        render_frame();
        ppu.clear_frame_ready();
    }
}
```

**优点**: 精确模拟，适合调试  
**缺点**: 性能较低（每条指令都要同步）

### 同步方案2: Scanline同步

```cpp
void run_until_scanline(int target_scanline) {
    while (ppu.get_scanline() < target_scanline) {
        int cpu_cycles = cpu.step();
        
        for (int i = 0; i < cpu_cycles * 3; i++) {
            ppu.tick();
        }
        
        // 检查NMI
        if (ppu.get_nmi_flag()) {
            cpu.trigger_nmi();
            ppu.clear_nmi_flag();
        }
    }
}

void run_one_frame() {
    for (int scanline = 0; scanline < 262; scanline++) {
        run_until_scanline(scanline);
    }
    
    if (ppu.is_frame_ready()) {
        render_frame();
        ppu.clear_frame_ready();
    }
}
```

**优点**: 平衡性能和精度  
**缺点**: 需要PPU暴露scanline状态

### 同步方案3: Frame同步（推荐用于AI训练）

```cpp
void run_one_frame() {
    int ppu_cycles_per_frame = 89342;
    int cpu_cycles_per_frame = ppu_cycles_per_frame / 3;
    
    int cpu_cycles_executed = 0;
    bool nmi_triggered = false;
    
    while (cpu_cycles_executed < cpu_cycles_per_frame) {
        int cycles = cpu.step();
        cpu_cycles_executed += cycles;
        
        // PPU tick
        for (int i = 0; i < cycles * 3; i++) {
            ppu.tick();
        }
        
        // NMI只触发一次
        if (ppu.get_nmi_flag() && !nmi_triggered) {
            cpu.trigger_nmi();
            ppu.clear_nmi_flag();
            nmi_triggered = true;
        }
    }
    
    // Frame完成
    if (ppu.is_frame_ready()) {
        render_frame();
        ppu.clear_frame_ready();
    }
}
```

**优点**: 最高性能，适合批量训练  
**缺点**: 可能轻微不精确（累积误差）

---

## 🎮 NMI处理

### NMI触发条件

```
NMI触发 = VBlank标志 AND PPUCTRL.bit7

VBlank标志设置时机: Scanline 241, Cycle 1
VBlank标志清除时机:
  - PPUSTATUS读取
  - Scanline 261, Cycle 1（Pre-render）
```

### NMI处理流程

```cpp
// PPU端
void PPU::tick() {
    // ... 其他逻辑
    
    // VBlank开始 (Scanline 241, Cycle 1)
    if (scanline == 241 && cycle == 1) {
        status |= 0x80;  // 设置VBlank标志
        
        if (ctrl & 0x80) {  // NMI enabled?
            nmi_pending = true;
        }
    }
    
    // VBlank结束 (Scanline 261, Cycle 1)
    if (scanline == 261 && cycle == 1) {
        status &= ~0x80;  // 清除VBlank标志
        nmi_pending = false;
    }
}

// CPU端
void CPU::trigger_nmi() {
    // Push PC and status to stack
    push((pc >> 8) & 0xFF);
    push(pc & 0xFF);
    push(status | 0x20);  // B flag = 0 for NMI
    
    // Set I flag
    status |= 0x04;
    
    // Jump to NMI vector
    uint16_t vector_addr = 0xFFFA;
    uint8_t low = read(vector_addr);
    uint8_t high = read(vector_addr + 1);
    pc = (high << 8) | low;
}
```

### 典型游戏NMI Handler

```assembly
; Super Mario Bros NMI Handler示例
NMI_Handler:
    PHA                 ; 保存A
    TXA
    PHA                 ; 保存X
    TYA
    PHA                 ; 保存Y
    
    ; 更新PPU
    LDA scroll_x
    STA $2005          ; PPUSCROLL X
    LDA scroll_y
    STA $2005          ; PPUSCROLL Y
    
    ; OAM DMA传输
    LDA #$00
    STA $2003          ; OAMADDR = 0
    LDA #$02
    STA $4014          ; OAMDMA from $0200-$02FF
    
    ; 恢复寄存器
    PLA
    TAY
    PLA
    TAX
    PLA
    
    RTI                ; 返回
```

---

## 🖼️ Frame渲染

### Framebuffer格式

```cpp
// PPU内部framebuffer
private:
    uint32_t framebuffer[256 * 240];  // RGBA8888
```

**格式**: 32-bit RGBA
- Byte 0: Red (0-255)
- Byte 1: Green (0-255)
- Byte 2: Blue (0-255)
- Byte 3: Alpha (固定255)

**分辨率**: 256×240像素

### 获取和显示Frame

```cpp
void render_frame() {
    // 获取framebuffer指针
    const uint32_t* pixels = ppu.get_framebuffer();
    
    // 方法1: SDL显示
    SDL_UpdateTexture(texture, nullptr, pixels, 256 * sizeof(uint32_t));
    SDL_RenderCopy(renderer, texture, nullptr, nullptr);
    SDL_RenderPresent(renderer);
    
    // 方法2: OpenGL显示
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 256, 240,
                    GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    
    // 方法3: 保存为PPM文件（调试）
    save_ppm("frame.ppm", pixels, 256, 240);
    
    // 方法4: 转为灰度给AI（强化学习）
    float* grayscale = rgb_to_grayscale(pixels, 256, 240);
}
```

### PPM保存函数（调试用）

```cpp
void save_ppm(const char* filename, const uint32_t* pixels, int width, int height) {
    FILE* f = fopen(filename, "wb");
    fprintf(f, "P6\n%d %d\n255\n", width, height);
    
    for (int i = 0; i < width * height; i++) {
        uint32_t rgba = pixels[i];
        uint8_t rgb[3] = {
            (rgba >> 0) & 0xFF,   // R
            (rgba >> 8) & 0xFF,   // G
            (rgba >> 16) & 0xFF   // B
        };
        fwrite(rgb, 1, 3, f);
    }
    
    fclose(f);
}
```

---

## 🗺️ Mapper集成

### Mapper接口

```cpp
class MapperInterface {
public:
    virtual ~MapperInterface() = default;
    
    // PRG ROM读写（CPU $8000-$FFFF）
    virtual uint8_t read_prg(uint16_t addr) = 0;
    virtual void write_prg(uint16_t addr, uint8_t value) = 0;
    
    // CHR ROM/RAM读写（PPU $0000-$1FFF）
    virtual uint8_t read_chr(uint16_t addr) = 0;
    virtual void write_chr(uint16_t addr, uint8_t value) = 0;
    
    // Mirroring模式（某些Mapper可动态改变）
    virtual MirroringMode get_mirroring() = 0;
    
    // IRQ支持（某些Mapper有）
    virtual bool has_irq_pending() { return false; }
    virtual void clear_irq() {}
};
```

### Mapper 0 (NROM)示例

```cpp
class Mapper0 : public MapperInterface {
public:
    Mapper0(const std::vector<uint8_t>& prg, const std::vector<uint8_t>& chr,
            MirroringMode mirror)
        : prg_rom(prg), chr_rom(chr), mirroring(mirror) {
        // PRG: 16KB镜像或32KB
        is_32kb = (prg_rom.size() == 32 * 1024);
    }
    
    uint8_t read_prg(uint16_t addr) override {
        addr -= 0x8000;  // $8000-$FFFF → 0-$7FFF
        
        if (is_32kb) {
            return prg_rom[addr];
        } else {
            // 16KB镜像
            return prg_rom[addr & 0x3FFF];
        }
    }
    
    void write_prg(uint16_t addr, uint8_t value) override {
        // NROM无PRG写入（某些游戏用作RAM）
    }
    
    uint8_t read_chr(uint16_t addr) override {
        // CHR ROM: $0000-$1FFF
        if (addr < chr_rom.size()) {
            return chr_rom[addr];
        }
        return 0;
    }
    
    void write_chr(uint16_t addr, uint8_t value) override {
        // CHR RAM支持
        if (is_chr_ram && addr < chr_rom.size()) {
            chr_rom[addr] = value;
        }
    }
    
    MirroringMode get_mirroring() override {
        return mirroring;
    }
    
private:
    std::vector<uint8_t> prg_rom;
    std::vector<uint8_t> chr_rom;
    MirroringMode mirroring;
    bool is_32kb;
    bool is_chr_ram = false;
};
```

### PPU与Mapper连接

```cpp
// 创建Mapper
auto mapper = std::make_shared<Mapper0>(prg_rom, chr_rom, mirroring);

// 连接PPU
ppu.chr_read = [mapper](uint16_t addr) {
    return mapper->read_chr(addr);
};

ppu.chr_write = [mapper](uint16_t addr, uint8_t value) {
    mapper->write_chr(addr, value);
};

ppu.set_mirroring(mapper->get_mirroring());
```

---

## 🧪 测试和验证

### 单元测试示例

```cpp
#include "ppu/ppu.h"
#include <gtest/gtest.h>

TEST(PPUIntegration, BasicSetup) {
    nes::PPU ppu;
    
    // 配置CHR callback
    std::vector<uint8_t> chr_rom(8192, 0);
    ppu.chr_read = [&chr_rom](uint16_t addr) {
        return chr_rom[addr];
    };
    
    // 设置mirroring
    ppu.set_mirroring(nes::PPU::HORIZONTAL);
    
    // 写入PPUCTRL
    ppu.write_register(0x2000, 0x80);  // Enable NMI
    
    // Tick到VBlank
    for (int i = 0; i < 241 * 341; i++) {
        ppu.tick();
    }
    
    // 应该触发NMI
    EXPECT_TRUE(ppu.get_nmi_flag());
}

TEST(PPUIntegration, FrameRendering) {
    nes::PPU ppu;
    
    // Setup CHR
    std::vector<uint8_t> chr_rom(8192, 0xFF);  // 全1 pattern
    ppu.chr_read = [&chr_rom](uint16_t addr) {
        return chr_rom[addr];
    };
    
    // 启用渲染
    ppu.write_register(0x2001, 0x1E);  // Show BG+Sprites
    
    // 运行一帧
    for (int i = 0; i < 89342; i++) {
        ppu.tick();
    }
    
    // 检查frame完成
    EXPECT_TRUE(ppu.is_frame_ready());
    
    // 检查framebuffer非空
    const uint32_t* fb = ppu.get_framebuffer();
    EXPECT_NE(fb, nullptr);
}
```

### 集成测试清单

- [ ] PPU reset正确初始化所有寄存器
- [ ] PPUCTRL/PPUMASK写入正确设置标志
- [ ] PPUSTATUS读取正确返回VBlank/sprite0
- [ ] PPUSCROLL双写入正确设置滚动
- [ ] PPUADDR双写入正确设置VRAM地址
- [ ] PPUDATA读写正确访问VRAM
- [ ] OAM读写正确
- [ ] VBlank在正确时刻触发NMI
- [ ] Frame在262 scanlines后完成
- [ ] CHR回调正确调用
- [ ] Mirroring正确映射nametable

---

## 🚀 性能优化建议

### 1. 减少tick()调用开销

```cpp
// 不推荐: 每个PPU cycle都检查NMI
for (int i = 0; i < ppu_cycles; i++) {
    ppu.tick();
    if (ppu.get_nmi_flag()) {
        // ...
    }
}

// 推荐: 只在可能的时刻检查
for (int i = 0; i < ppu_cycles; i++) {
    ppu.tick();
}
// VBlank只在scanline 241发生
if (ppu.get_scanline() == 241 && ppu.get_nmi_flag()) {
    cpu.trigger_nmi();
    ppu.clear_nmi_flag();
}
```

### 2. Batch rendering

```cpp
// 不推荐: 每帧都渲染到屏幕
if (ppu.is_frame_ready()) {
    render_to_screen(ppu.get_framebuffer());
}

// 推荐: 批量处理（AI训练）
if (frame_count % 4 == 0) {  // 每4帧显示1帧
    render_to_screen(ppu.get_framebuffer());
}
```

### 3. 预分配内存

```cpp
// CPU memory map预分配
class NESMemory {
    std::array<uint8_t, 0x10000> ram;  // 预分配64KB
    
    uint8_t read(uint16_t addr) {
        // 直接数组访问，无动态分配
        if (addr < 0x2000) {
            return ram[addr & 0x7FF];  // 2KB镜像
        }
        // ...
    }
};
```

---

## 🐛 常见问题

### Q1: NMI触发了但CPU没响应

**检查**:
1. CPU的NMI vector ($FFFA-$FFFB)是否正确
2. PPUCTRL bit 7是否设置（0x80）
3. CPU的I flag是否阻止了中断（NMI不应被阻止）

**调试**:
```cpp
if (ppu.get_nmi_flag()) {
    printf("NMI pending at scanline %d, cycle %d\n", 
           ppu.get_scanline(), ppu.get_cycle());
    
    uint8_t ctrl = ppu.read_register(0x2000);
    printf("PPUCTRL = 0x%02X (NMI %s)\n", 
           ctrl, (ctrl & 0x80) ? "enabled" : "disabled");
}
```

### Q2: 画面全黑

**检查**:
1. PPUMASK是否启用渲染（bit 3/4）
2. CHR ROM是否正确加载
3. Palette是否正确设置（$3F00-$3F1F）

**调试**:
```cpp
uint8_t mask = ppu.read_register(0x2001);
printf("PPUMASK = 0x%02X (BG:%d, Sprites:%d)\n",
       mask, (mask & 0x08) ? 1 : 0, (mask & 0x10) ? 1 : 0);

// 检查palette
for (int i = 0; i < 32; i++) {
    uint8_t color = ppu.ppu_read(0x3F00 + i);
    printf("Palette[%d] = 0x%02X\n", i, color);
}
```

### Q3: 滚动不正确

**检查**:
1. PPUSCROLL是否按X, Y顺序双写入
2. Mirroring模式是否正确（H/V）
3. PPUADDR写入是否影响滚动（共用t寄存器）

**调试**:
```cpp
// 在写入PPUSCROLL时记录
void write_ppuscroll(uint8_t value) {
    static int write_count = 0;
    printf("PPUSCROLL write #%d = 0x%02X\n", write_count++, value);
    ppu.write_register(0x2005, value);
}
```

### Q4: 性能太慢

**优化方向**:
1. 使用Frame同步而非指令同步
2. 减少不必要的framebuffer拷贝
3. 使用硬件加速显示（OpenGL/Vulkan）
4. Profile找到真正的热点

**Profiling**:
```cpp
auto start = std::chrono::high_resolution_clock::now();

for (int i = 0; i < 1000; i++) {
    run_one_frame();
}

auto end = std::chrono::high_resolution_clock::now();
auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);

printf("1000 frames in %lld ms (%.2f FPS)\n", 
       duration.count(), 1000000.0 / duration.count());
```

---

## 📚 参考资料

### NES技术文档

- [NESDev Wiki](https://wiki.nesdev.com/)
- [PPU Registers](https://wiki.nesdev.com/w/index.php/PPU_registers)
- [PPU Scrolling](https://wiki.nesdev.com/w/index.php/PPU_scrolling)
- [PPU Rendering](https://wiki.nesdev.com/w/index.php/PPU_rendering)

### 测试ROM

- `tests/integration/nes-test-roms/` - 各种测试ROM
- [Blargg's test ROMs](http://blargg.8bitalley.com/parodius/nes-tests/)

### 示例游戏（Mapper 0）

- Super Mario Bros (需MMC1, 不是Mapper 0)
- Donkey Kong (NROM)
- Ice Climber (NROM)
- Balloon Fight (NROM)

---

## 🎯 完整集成示例

```cpp
#include "cpu/cpu.h"
#include "ppu/ppu.h"
#include "common/mapper0.h"

class NES {
public:
    NES(const std::vector<uint8_t>& rom_data) {
        // 解析ROM (iNES格式)
        parse_ines_rom(rom_data);
        
        // 创建Mapper
        mapper = std::make_shared<Mapper0>(prg_rom, chr_rom, mirroring);
        
        // 配置PPU
        ppu.chr_read = [this](uint16_t addr) {
            return mapper->read_chr(addr);
        };
        ppu.set_mirroring(mapper->get_mirroring());
        
        // 配置CPU内存
        cpu.read_callback = [this](uint16_t addr) {
            return this->cpu_read(addr);
        };
        cpu.write_callback = [this](uint16_t addr, uint8_t value) {
            this->cpu_write(addr, value);
        };
        
        // Reset
        cpu.reset();
        ppu.reset();
    }
    
    void run_one_frame() {
        int ppu_cycles_per_frame = 89342;
        int cpu_cycles = 0;
        bool nmi_triggered = false;
        
        while (cpu_cycles < ppu_cycles_per_frame / 3) {
            int cycles = cpu.step();
            cpu_cycles += cycles;
            
            // PPU tick
            for (int i = 0; i < cycles * 3; i++) {
                ppu.tick();
            }
            
            // NMI
            if (ppu.get_nmi_flag() && !nmi_triggered) {
                cpu.trigger_nmi();
                ppu.clear_nmi_flag();
                nmi_triggered = true;
            }
        }
    }
    
    const uint32_t* get_frame() {
        return ppu.get_framebuffer();
    }
    
private:
    CPU6502 cpu;
    nes::PPU ppu;
    std::shared_ptr<Mapper0> mapper;
    
    std::vector<uint8_t> prg_rom;
    std::vector<uint8_t> chr_rom;
    nes::PPU::MirroringMode mirroring;
    std::array<uint8_t, 0x800> ram;  // 2KB CPU RAM
    
    uint8_t cpu_read(uint16_t addr) {
        if (addr < 0x2000) {
            return ram[addr & 0x7FF];
        } else if (addr < 0x4000) {
            return ppu.read_register(addr);
        } else if (addr >= 0x8000) {
            return mapper->read_prg(addr);
        }
        return 0;
    }
    
    void cpu_write(uint16_t addr, uint8_t value) {
        if (addr < 0x2000) {
            ram[addr & 0x7FF] = value;
        } else if (addr < 0x4000) {
            ppu.write_register(addr, value);
        } else if (addr >= 0x8000) {
            mapper->write_prg(addr, value);
        }
    }
    
    void parse_ines_rom(const std::vector<uint8_t>& data) {
        // iNES header: 16 bytes
        // "NES\x1A" magic
        int prg_banks = data[4];  // 16KB units
        int chr_banks = data[5];  // 8KB units
        
        // Flags
        bool vertical = (data[6] & 0x01);
        mirroring = vertical ? nes::PPU::VERTICAL : nes::PPU::HORIZONTAL;
        
        // Copy PRG ROM
        size_t prg_size = prg_banks * 16384;
        prg_rom.resize(prg_size);
        std::memcpy(prg_rom.data(), &data[16], prg_size);
        
        // Copy CHR ROM
        size_t chr_size = chr_banks * 8192;
        chr_rom.resize(chr_size);
        std::memcpy(chr_rom.data(), &data[16 + prg_size], chr_size);
    }
};

// 使用示例
int main() {
    // 加载ROM
    std::vector<uint8_t> rom = load_file("game.nes");
    
    // 创建NES
    NES nes(rom);
    
    // 运行
    for (int frame = 0; frame < 1000; frame++) {
        nes.run_one_frame();
        
        // 显示
        display_frame(nes.get_frame());
    }
    
    return 0;
}
```

---

## ✅ 集成清单

完成以下清单确保集成正确：

### 初始化
- [ ] 创建PPU实例
- [ ] 调用ppu.reset()
- [ ] 设置mirroring模式
- [ ] 连接CHR read/write回调
- [ ] 配置CPU内存映射（$2000-$3FFF）

### 时钟同步
- [ ] CPU step返回cycles
- [ ] PPU tick() 执行CPU_cycles×3次
- [ ] NMI检查和触发
- [ ] Frame完成检测

### 渲染
- [ ] 获取framebuffer
- [ ] 显示到屏幕
- [ ] 清除frame_ready标志

### 测试
- [ ] 寄存器读写正确
- [ ] VBlank/NMI触发正确
- [ ] Frame timing正确（89,342 cycles）
- [ ] 画面显示正确（不全黑/全白）

---

**文档版本**: 1.0  
**最后更新**: 2024-04-25  
**反馈**: 请报告问题到项目issue tracker
