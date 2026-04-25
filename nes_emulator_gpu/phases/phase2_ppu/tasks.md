# Phase 2 Tasks - Detailed Checklist

**Project**: NES GPU Emulator  
**Phase**: Phase 2 - PPU Implementation  
**Total Tasks**: 6 major, ~80 subtasks

---

## Task 2.1: PPU Registers & Memory [估计: 3-4天]

### Subtasks

#### 2.1.1 PPU基础架构
- [ ] 创建 `src/reference/ppu/ppu.h`
- [ ] 创建 `src/reference/ppu/ppu.cpp`
- [ ] 定义PPU类主结构
- [ ] 添加framebuffer (256×240 uint32_t数组)
- [ ] 添加构造/析构函数

#### 2.1.2 PPU寄存器实现
- [ ] 实现 $2000 PPUCTRL 写入
- [ ] 实现 $2001 PPUMASK 写入
- [ ] 实现 $2002 PPUSTATUS 读取 (读清除VBlank)
- [ ] 实现 $2003 OAMADDR 写入
- [ ] 实现 $2004 OAMDATA 读写
- [ ] 实现 $2005 PPUSCROLL 写入 (两次写入)
- [ ] 实现 $2006 PPUADDR 写入 (两次写入)
- [ ] 实现 $2007 PPUDATA 读写 (自动递增)
- [ ] 实现寄存器镜像 ($2008-$3FFF)

#### 2.1.3 内部寄存器
- [ ] 实现 v 寄存器 (当前VRAM地址, 15位)
- [ ] 实现 t 寄存器 (临时VRAM地址, 15位)
- [ ] 实现 x 寄存器 (fine X scroll, 3位)
- [ ] 实现 w 寄存器 (写入toggle, 1位)
- [ ] 实现地址递增逻辑 (PPUCTRL bit 2: +1 或 +32)

#### 2.1.4 PPU内存系统
- [ ] 实现CHR ROM读取 (通过mapper)
- [ ] 实现VRAM读写 (2KB, name tables)
- [ ] 实现调色板RAM (32字节)
- [ ] 实现调色板镜像 ($3F10, $3F14, $3F18, $3F1C)
- [ ] 实现PPU内存读取函数
- [ ] 实现PPU内存写入函数

#### 2.1.5 OAM (Object Attribute Memory)
- [ ] 实现OAM数组 (256字节)
- [ ] 实现OAMADDR读写
- [ ] 实现OAMDATA读写
- [ ] 实现OAM DMA ($4014寄存器)
- [ ] OAM DMA暂停CPU 513/514周期

#### 2.1.6 单元测试
- [ ] 创建 `tests/unit/test_ppu_registers.cpp`
- [ ] 测试PPUCTRL写入
- [ ] 测试PPUMASK写入
- [ ] 测试PPUSTATUS读取清除VBlank
- [ ] 测试PPUSCROLL两次写入
- [ ] 测试PPUADDR两次写入
- [ ] 测试PPUDATA读写
- [ ] 测试PPUDATA递增 (+1 vs +32)
- [ ] 测试v/t/w寄存器交互
- [ ] 测试OAM读写
- [ ] 测试OAM DMA
- [ ] 测试寄存器镜像
- [ ] 测试VRAM镜像
- [ ] 测试调色板镜像

#### 2.1.7 集成
- [ ] 修改Memory类添加PPU回调
- [ ] 在CPU read/write中调用PPU
- [ ] 更新CMakeLists.txt
- [ ] 编译通过
- [ ] 所有测试通过

**预计产出**:
- ppu.h: ~100 lines
- ppu.cpp: ~200 lines
- test_ppu_registers.cpp: ~250 lines

---

## Task 2.2: Background Rendering [估计: 5-7天]

### Subtasks

#### 2.2.1 调色板系统
- [ ] 创建 `src/reference/ppu/palette.h`
- [ ] 定义标准NES调色板 (64色RGB值)
- [ ] 实现调色板查找函数
- [ ] 测试所有64色正确性

#### 2.2.2 Name Table解析
- [ ] 实现name table地址计算
- [ ] 读取32×30 tile索引
- [ ] 处理4个name table ($2000, $2400, $2800, $2C00)
- [ ] Name table边界检查

#### 2.2.3 Attribute Table解析
- [ ] 实现attribute table地址计算 ($23C0, $27C0, ...)
- [ ] 读取2位调色板索引
- [ ] 计算4×4 tile块内偏移
- [ ] 正确的位移和掩码

#### 2.2.4 Pattern Table查找
- [ ] 从CHR ROM读取tile数据
- [ ] 支持两个pattern table ($0000 vs $1000)
- [ ] 解析8×8 tile (16字节)
- [ ] 组合low/high bit planes
- [ ] 生成2位像素值

#### 2.2.5 背景渲染流水线
- [ ] 实现 `render_background_pixel(x, y)`
- [ ] Coarse X scroll
- [ ] Coarse Y scroll
- [ ] Fine X scroll (0-7像素)
- [ ] Fine Y scroll (tile内偏移)
- [ ] 正确的颜色查找
- [ ] 写入framebuffer

#### 2.2.6 Scrolling支持
- [ ] 实现PPUSCROLL第一次写入 (X scroll)
- [ ] 实现PPUSCROLL第二次写入 (Y scroll)
- [ ] Fine X更新
- [ ] v/t寄存器更新
- [ ] 跨name table滚动

#### 2.2.7 渲染优化
- [ ] Scanline级别渲染
- [ ] Tile预取
- [ ] 避免重复计算

#### 2.2.8 单元测试
- [ ] 创建 `tests/unit/test_background.cpp`
- [ ] 测试name table读取
- [ ] 测试attribute table解析
- [ ] 测试pattern table查找
- [ ] 测试调色板查找
- [ ] 测试单个像素渲染
- [ ] 测试滚动 (X/Y)
- [ ] 测试跨name table渲染
- [ ] 测试边界情况

**预计产出**:
- palette.h: ~80 lines
- background.cpp: ~250 lines
- test_background.cpp: ~180 lines

---

## Task 2.3: Sprite Rendering [估计: 5-7天]

### Subtasks

#### 2.3.1 OAM结构
- [ ] 定义Sprite结构体 (Y, tile, attr, X)
- [ ] 解析64个精灵
- [ ] 理解属性字节 (调色板、优先级、翻转)

#### 2.3.2 Sprite评估
- [ ] 实现 `evaluate_sprites()`
- [ ] 找到当前scanline上的精灵
- [ ] Secondary OAM (最多8个精灵)
- [ ] 精灵溢出检测
- [ ] 设置PPUSTATUS bit 5

#### 2.3.3 Sprite渲染
- [ ] 实现8×8精灵渲染
- [ ] 实现8×16精灵渲染
- [ ] 从正确的pattern table读取
- [ ] 8×16模式的tile索引计算

#### 2.3.4 Sprite翻转
- [ ] 水平翻转 (attribute bit 6)
- [ ] 垂直翻转 (attribute bit 7)
- [ ] 正确的像素位反转

#### 2.3.5 Sprite调色板
- [ ] 使用精灵调色板 ($3F10-$3F1F)
- [ ] 4个精灵调色板 (attribute bits 0-1)
- [ ] 透明色处理 (颜色0)

#### 2.3.6 Sprite优先级
- [ ] 前景精灵 (遮挡背景)
- [ ] 后景精灵 (背景优先, attribute bit 5)
- [ ] 精灵间优先级 (OAM索引)

#### 2.3.7 Sprite 0 Hit检测
- [ ] 检测sprite 0与背景碰撞
- [ ] 仅检测不透明像素
- [ ] 设置PPUSTATUS bit 6
- [ ] 正确的时序 (在像素渲染时)

#### 2.3.8 集成到渲染流水线
- [ ] 每scanline调用sprite评估
- [ ] 渲染精灵像素
- [ ] 背景/精灵合成
- [ ] Z-order正确性

#### 2.3.9 单元测试
- [ ] 创建 `tests/unit/test_sprites.cpp`
- [ ] 测试sprite评估
- [ ] 测试8×8渲染
- [ ] 测试8×16渲染
- [ ] 测试水平翻转
- [ ] 测试垂直翻转
- [ ] 测试调色板
- [ ] 测试优先级
- [ ] 测试sprite 0 hit
- [ ] 测试精灵溢出
- [ ] 测试边界情况 (Y=0xFF等)

**预计产出**:
- sprites.cpp: ~300 lines
- test_sprites.cpp: ~200 lines

---

## Task 2.4: Mirroring & Scrolling [估计: 2-3天]

### Subtasks

#### 2.4.1 Name Table镜像
- [ ] 实现Horizontal镜像 (Super Mario Bros)
- [ ] 实现Vertical镜像
- [ ] 实现Single Screen镜像
- [ ] 实现Four Screen镜像 (需要额外VRAM)
- [ ] 从Mapper获取镜像模式

#### 2.4.2 镜像地址转换
- [ ] 实现 `mirror_nametable_address()`
- [ ] Horizontal: $2000=$2400, $2800=$2C00
- [ ] Vertical: $2000=$2800, $2400=$2C00
- [ ] 正确映射到2KB物理VRAM

#### 2.4.3 PPUSCROLL实现细节
- [ ] 第一次写入: t的coarse X + fine X
- [ ] 第二次写入: t的coarse Y + fine Y
- [ ] w toggle翻转
- [ ] v/t寄存器交互

#### 2.4.4 PPUADDR实现细节
- [ ] 第一次写入: t的高6位
- [ ] 第二次写入: t的低8位
- [ ] w toggle翻转
- [ ] 写入后v = t

#### 2.4.5 滚动寄存器位布局
- [ ] v寄存器各位定义:
  - bits 0-4: coarse X
  - bits 5-9: coarse Y
  - bits 10-11: nametable select
  - bits 12-14: fine Y
- [ ] 理解和实现所有位操作

#### 2.4.6 Rendering时的滚动
- [ ] 每8像素递增coarse X
- [ ] Coarse X溢出时切换水平nametable
- [ ] Scanline结束时递增Y
- [ ] Y溢出时切换垂直nametable

#### 2.4.7 单元测试
- [ ] 创建 `tests/unit/test_scrolling.cpp`
- [ ] 测试水平镜像
- [ ] 测试垂直镜像
- [ ] 测试PPUSCROLL写入
- [ ] 测试PPUADDR写入
- [ ] 测试v/t/w交互
- [ ] 测试滚动渲染
- [ ] 测试跨nametable滚动

**预计产出**:
- 修改ppu.cpp: +120 lines
- test_scrolling.cpp: ~140 lines

---

## Task 2.5: Scanline Timing [估计: 4-5天]

### Subtasks

#### 2.5.1 Scanline结构
- [ ] 定义scanline/cycle计数器
- [ ] 261 scanlines (0-260)
- [ ] 341 cycles per scanline (0-340)
- [ ] 实现 `tick()` 函数

#### 2.5.2 可见Scanlines (0-239)
- [ ] Cycle 0: Idle
- [ ] Cycle 1-256: Render pixels
- [ ] Cycle 257-320: Sprite fetch (next scanline)
- [ ] Cycle 321-336: Background fetch (next scanline)
- [ ] Cycle 337-340: Unknown fetches

#### 2.5.3 Post-render Scanline (240)
- [ ] Idle scanline
- [ ] 无渲染

#### 2.5.4 VBlank Scanlines (241-260)
- [ ] Scanline 241, cycle 1: 设置VBlank标志
- [ ] 触发NMI (如果PPUCTRL bit 7)
- [ ] VBlank期间PPU idle

#### 2.5.5 Pre-render Scanline (261)
- [ ] Cycle 1: 清除VBlank/sprite0/overflow标志
- [ ] Cycle 280-304: Y scroll reset
- [ ] 其余同可见scanline (为下一帧准备)

#### 2.5.6 VBlank时序
- [ ] NMI触发: scanline 241, cycle 1
- [ ] PPUSTATUS读取清除VBlank
- [ ] 读取竞态: scanline 241, cycle 0-1附近
- [ ] NMI抑制窗口

#### 2.5.7 Sprite 0 Hit时序
- [ ] 在像素渲染时检测
- [ ] 设置PPUSTATUS bit 6
- [ ] Pre-render时清除

#### 2.5.8 PPU-CPU同步
- [ ] PPU tick 3次 = CPU tick 1次
- [ ] 或: CPU tick后, PPU tick 3次
- [ ] NMI回调到CPU

#### 2.5.9 Frame完成检测
- [ ] Scanline 261结束 = 1帧完成
- [ ] 设置frame_complete标志
- [ ] Framebuffer准备好读取

#### 2.5.10 单元测试
- [ ] 创建 `tests/unit/test_timing.cpp`
- [ ] 测试VBlank标志设置
- [ ] 测试NMI触发
- [ ] 测试PPUSTATUS读取清除VBlank
- [ ] 测试Pre-render清除标志
- [ ] 测试scanline/cycle计数
- [ ] 测试frame完成
- [ ] 测试PPU-CPU同步

**预计产出**:
- 修改ppu.cpp: +180 lines
- test_timing.cpp: ~120 lines

---

## Task 2.6: Testing & Integration [估计: 3-4天]

### Subtasks

#### 2.6.1 单元测试完善
- [ ] 确保所有test文件编译通过
- [ ] 补充边缘情况测试
- [ ] 代码覆盖率分析
- [ ] 达到80%+覆盖率

#### 2.6.2 PPU测试ROM
- [ ] 下载/准备测试ROM
- [ ] 实现ROM加载器
- [ ] 运行 `sprite_hit_tests_2005.10.05/`
- [ ] 运行 `vbl_nmi_timing/`
- [ ] 运行 `ppu_vbl_nmi/`
- [ ] 分析失败原因并修复

#### 2.6.3 Super Mario Bros集成
- [ ] 创建完整的NES模拟器类
- [ ] 集成CPU + PPU + Memory + Mapper
- [ ] 加载Super Mario Bros ROM
- [ ] 模拟启动和第一帧
- [ ] 保存framebuffer为图片
- [ ] 视觉验证渲染正确性

#### 2.6.4 CPU-PPU交互
- [ ] PPU寄存器读写通过Memory
- [ ] VBlank NMI触发CPU
- [ ] OAM DMA暂停CPU
- [ ] 正确的时序同步

#### 2.6.5 性能测试
- [ ] 单帧渲染时间 (debug build)
- [ ] 60fps可达性 (release build)
- [ ] 内存使用分析
- [ ] Valgrind内存泄漏检查

#### 2.6.6 文档完善
- [ ] 创建 `PHASE2_SUMMARY.md`
- [ ] 记录所有实现细节
- [ ] 统计代码行数
- [ ] 列出测试结果
- [ ] 记录经验教训

#### 2.6.7 更新项目状态
- [ ] 更新 `CURRENT_STATUS.md`
- [ ] Phase 2进度 → 100%
- [ ] 总体进度更新
- [ ] 记录实际耗时

#### 2.6.8 代码审查
- [ ] 检查代码风格一致性
- [ ] 添加必要注释
- [ ] 移除调试代码
- [ ] 清理临时文件

**预计产出**:
- test_integration.cpp: ~200 lines
- PHASE2_SUMMARY.md: ~400 lines
- 更新CURRENT_STATUS.md

---

## 📊 Total Task Summary

| Category | Tasks | Subtasks | Est. Lines |
|----------|-------|----------|------------|
| Registers & Memory | 1 | 17 | 550 |
| Background | 1 | 18 | 510 |
| Sprites | 1 | 19 | 500 |
| Mirroring & Scroll | 1 | 14 | 260 |
| Timing | 1 | 10 | 300 |
| Testing | 1 | 16 | 600 |
| **Total** | **6** | **94** | **~2720** |

---

## ✅ Completion Criteria

**Phase 2 is complete when**:
- [ ] All 6 major tasks completed
- [ ] All ~94 subtasks completed
- [ ] All unit tests passing (60+ tests)
- [ ] At least 2 PPU test ROMs passing
- [ ] Super Mario Bros renders correctly
- [ ] Code coverage > 80%
- [ ] No memory leaks (valgrind clean)
- [ ] Documentation complete
- [ ] PHASE2_SUMMARY.md created

---

**Start Date**: TBD  
**Target Completion**: TBD  
**Actual Completion**: TBD  
**Status**: ⏳ Not Started
