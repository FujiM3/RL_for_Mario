# Task 2.3 简化版：精灵渲染系统

**版本**: 简化版 (去除非必要功能)  
**目标**: 实现足够Super Mario Bros运行的精灵系统  
**预计时间**: 2-3天 (原计划5-7天)  

---

## 🎯 保留功能 (核心RL训练必需)

### ✅ 1. 基本精灵渲染
- 64个精灵的OAM数据结构
- 8×8 精灵模式 (最常用)
- 每scanline最多8个精灵
- Sprite pattern查找
- 基本前景/背景优先级

### ✅ 2. 精灵翻转
- 水平翻转 (attribute bit 6)
- 垂直翻转 (attribute bit 7)
- SMB中Mario的翻转动画需要

### ✅ 3. 精灵评估
- 找出当前scanline上的8个sprite
- 基本的sprite overflow检测 (设置flag即可)

---

## ❌ 删除功能 (RL训练不需要)

### ❌ 1. Sprite 0 Hit检测
**原因**: 
- Super Mario Bros **不使用** Sprite 0 Hit
- 这个特性主要用于分屏效果
- SMB用简单的VBlank timing即可

**节省**: ~50行代码 + 1天调试

### ❌ 2. 8×16 精灵模式
**原因**:
- Super Mario Bros **只用8×8模式**
- PPUCTRL bit 5 = 0 (固定)
- 8×16主要用于大型boss等

**节省**: ~30行代码 + 0.5天实现

### ❌ 3. 精确的Sprite Overflow算法
**原因**:
- 硬件bug的精确模拟
- RL训练不依赖这个bug
- 简单版本: 超过8个就设flag

**节省**: ~40行代码 + 1天调试

### ❌ 4. Secondary OAM模拟
**原因**:
- 硬件层面的内部buffer
- 可以用简单数组代替
- 不影响最终渲染结果

**节省**: ~20行代码

---

## 📋 简化实现计划

### Day 1: 精灵数据结构与评估 (4-6小时)

#### 1.1 Sprite数据结构
```cpp
// ppu.h中已有OAM[256]，无需修改

struct SpriteData {
    uint8_t y;        // Y position - 1
    uint8_t tile;     // Tile index
    uint8_t attr;     // Attributes
    uint8_t x;        // X position
};
```

#### 1.2 精灵评估 (简化版)
```cpp
// ppu.cpp
struct ActiveSprite {
    uint8_t x, y, tile, attr;
    uint8_t oam_index;  // 用于优先级
};

void PPU::evaluate_sprites() {
    // 当前scanline的可见sprites
    active_sprite_count = 0;
    
    for (int i = 0; i < 64; i++) {
        uint8_t y = oam[i * 4];
        int row = scanline - (y + 1);  // Y位置偏移1
        
        // 检查是否在当前scanline
        if (row >= 0 && row < 8) {  // 仅8×8模式
            if (active_sprite_count < 8) {
                active_sprites[active_sprite_count++] = {
                    oam[i*4+3],  // x
                    y,           // y
                    oam[i*4+1],  // tile
                    oam[i*4+2],  // attr
                    (uint8_t)i   // index
                };
            } else {
                // 简化: 仅设置overflow flag
                status |= 0x20;
            }
        }
    }
}
```

**测试**: 验证每scanline找到正确sprites

---

### Day 2: 精灵渲染实现 (6-8小时)

#### 2.1 Pattern查找 (支持翻转)
```cpp
uint8_t PPU::get_sprite_pattern(uint8_t tile, int fine_y, bool vflip) {
    // 垂直翻转
    if (vflip) fine_y = 7 - fine_y;
    
    // Sprite pattern table固定在$1000 (PPUCTRL bit 3)
    uint16_t base = (ctrl & 0x08) ? 0x1000 : 0x0000;
    uint16_t addr = base + tile * 16 + fine_y;
    
    uint8_t lo = chr_callback ? chr_callback(addr) : 0;
    uint8_t hi = chr_callback ? chr_callback(addr + 8) : 0;
    
    return (lo << 8) | hi;  // 返回16位 (8像素)
}
```

#### 2.2 精灵像素渲染
```cpp
void PPU::render_sprite_pixel(int x, int y) {
    if (!(mask & 0x10)) return;  // Sprite disabled
    
    // 遍历active sprites (已按优先级排序)
    for (int i = 0; i < active_sprite_count; i++) {
        ActiveSprite& spr = active_sprites[i];
        
        // 检查X范围
        int dx = x - spr.x;
        if (dx < 0 || dx >= 8) continue;
        
        // 水平翻转
        if (spr.attr & 0x40) dx = 7 - dx;
        
        // 垂直翻转
        bool vflip = spr.attr & 0x80;
        int dy = y - (spr.y + 1);
        
        // 获取pattern
        uint16_t pattern = get_sprite_pattern(spr.tile, dy, vflip);
        uint8_t lo_bit = (pattern >> (15 - dx)) & 1;
        uint8_t hi_bit = (pattern >> (7 - dx)) & 1;
        uint8_t pixel = (hi_bit << 1) | lo_bit;
        
        if (pixel == 0) continue;  // 透明
        
        // 获取颜色
        uint8_t palette = (spr.attr & 0x03) + 4;  // Sprite palette $10-$1F
        uint32_t color = get_sprite_color(palette, pixel);
        
        // 优先级检查 (简化版)
        bool behind_bg = spr.attr & 0x20;
        uint32_t bg_color = framebuffer[y * 256 + x];
        
        if (!behind_bg || bg_color == get_palette_color(palette_ram[0])) {
            // 前景sprite 或 背景透明
            framebuffer[y * 256 + x] = color;
            return;  // 第一个非透明sprite优先
        }
    }
}
```

**测试**: 渲染单个sprite, 验证翻转和颜色正确

---

### Day 3: 集成与测试 (4-6小时)

#### 3.1 集成到tick()
```cpp
void PPU::tick() {
    // 在每个scanline开始时评估sprites
    if (cycle == 0 && scanline < 240) {
        evaluate_sprites();
    }
    
    // 渲染
    if (scanline < 240 && cycle < 256) {
        render_background_pixel(cycle, scanline);  // 先背景
        render_sprite_pixel(cycle, scanline);       // 后精灵
    }
    
    // ... VBlank等逻辑
}
```

#### 3.2 测试用例
```cpp
// test_sprites.cpp (简化版, ~120行)

TEST(SpriteRendering, BasicSpriteEvaluation) {
    // 测试8个sprite/scanline限制
}

TEST(SpriteRendering, SpriteRenderWithFlip) {
    // 测试水平/垂直翻转
}

TEST(SpriteRendering, SpritePriority) {
    // 测试前景/背景优先级
}

TEST(SpriteRendering, SpriteOverflow) {
    // 测试>8个sprite设置flag
}

TEST(SpriteRendering, SpritePalette) {
    // 测试sprite调色板 ($10-$1F)
}

// 总计: ~5个测试 (不需要Sprite 0 Hit测试)
```

---

## 📊 简化版 vs 完整版对比

| 特性 | 完整版 | 简化版 | 节省 |
|------|--------|--------|------|
| 8×8 sprite | ✅ | ✅ | - |
| 8×16 sprite | ✅ | ❌ | 0.5天 |
| Sprite 0 Hit | ✅ | ❌ | 1天 |
| 精确overflow | ✅ | ❌ | 1天 |
| Secondary OAM | ✅ | ❌ | 0.5天 |
| **总时间** | 5-7天 | **2-3天** | **3-4天** |
| **代码量** | ~300行 | **~150行** | 50% |
| **测试数** | ~12个 | **~5个** | - |

---

## ✅ 验收标准 (简化版)

### 功能性
- [x] 64个sprite的OAM读写 (Task 2.1已完成)
- [ ] 每scanline最多8个sprite
- [ ] 8×8 sprite渲染
- [ ] 水平/垂直翻转
- [ ] Sprite调色板 ($10-$1F)
- [ ] 前景/背景优先级

### 性能
- [ ] 5个sprite测试全部通过
- [ ] 与背景合成正确
- [ ] 帧率不低于60fps

### 兼容性
- [ ] Super Mario Bros sprites显示正确
- [ ] Mario翻转动画正常
- [ ] 敌人sprite正确

---

## 🎯 实施计划

### 今天-明天
1. **实现sprite评估** (~150行)
2. **实现sprite渲染** (~100行)
3. **集成到tick()** (~10行)

### 后天
4. **创建5个测试** (~120行)
5. **调试+验证** 
6. **更新work_log_003.md**

**总计**: 2-3天, ~260行代码 (vs 完整版500行)

---

## 🚫 明确不实现的内容

记录下来避免scope creep:

1. ❌ Sprite 0 Hit检测
2. ❌ 8×16精灵模式
3. ❌ 精确的sprite overflow硬件bug
4. ❌ Secondary OAM的周期级模拟
5. ❌ Sprite评估的timing精确性
6. ❌ OAM corruption bug

**如果将来需要** (极不可能):
- 可以在GPU版本时再考虑
- 或者在CPU参考实现v2.0时添加

---

## 📝 下一步

准备好开始实现简化版Task 2.3了吗？

**预期成果** (2-3天后):
- ✅ Super Mario Bros完整显示 (背景+精灵)
- ✅ ~117个测试通过
- ✅ Phase 2进度: 35% → 50%
- ✅ 代码规模: ~850行PPU + ~1040行测试
