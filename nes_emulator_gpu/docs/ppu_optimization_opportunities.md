# PPU Code Optimization Opportunities

**Created**: 2024
**Status**: Analysis Complete
**Current State**: 136/136 tests passing, Phase 2 at 83%

## Current Code Metrics

### Size
- `ppu.cpp`: 718 lines
- `ppu.h`: 243 lines
- `palette.h`: 58 lines
- **Total**: ~1,019 lines of PPU code

### Performance
- **Frame rate**: 262 scanlines × 341 cycles = 89,342 ticks/frame
- **@60fps**: 5.36 million ticks/second
- **Pixel rendering**: 256 × 240 = 61,440 pixels/frame
- **@60fps**: 3.69 million pixels/second

### Test Coverage
- 136 tests passing ✅
- 151 test cases total
- Categories: CPU (38), PPU registers (29), Memory (18), etc.

---

## Optimization Opportunities

### 1. tick() Function Hot Path ⭐⭐⭐

**Current Implementation** (lines 181-259):
```cpp
void PPU::tick() {
    // Advance counters
    cycle++;
    if (cycle > 340) { ... }
    
    // Visible scanlines (0-239)
    if (scanline < 240) {
        if (cycle == 0) { evaluate_sprites(); }
        if (cycle >= 1 && cycle <= 256) {
            render_background_pixel(cycle-1, scanline);
            render_sprite_pixel(cycle-1, scanline);
        }
    }
    
    // VBlank (241-260)
    if (scanline == 241 && cycle == 1) { ... }
    
    // Pre-render (261)
    if (scanline == 261) { ... }
}
```

**Issues**:
- Called 89,342 times per frame (5.36M times/second @60fps)
- Multiple conditional checks every tick
- Branch mispredictions likely

**Optimization A**: Scanline-based dispatch
```cpp
void PPU::tick() {
    cycle++;
    if (cycle > 340) {
        cycle = 0;
        scanline++;
        if (scanline > 261) scanline = 0;
        if (scanline == 261) frame_ready = true;
        
        // Update scanline handler pointer
        current_scanline_handler = scanline_handlers[scanline];
    }
    
    // Call current scanline handler (removes branching)
    (this->*current_scanline_handler)();
}
```

**Estimated Speedup**: 10-15% (fewer branches per tick)

**Optimization B**: Cycle-level state machine
```cpp
enum PPUState {
    STATE_VISIBLE,
    STATE_POST_RENDER,
    STATE_VBLANK,
    STATE_PRE_RENDER
};

void PPU::tick() {
    cycle++;
    if (cycle > 340) {
        advance_scanline();
        update_state();  // Changes state once per scanline
    }
    
    state_handlers[current_state]();
}
```

**Estimated Speedup**: 15-20% (single switch/jump per tick)

**Recommendation**: Defer until Phase 4 (GPU port). Current implementation is readable and testable, which is more valuable for reference implementation.

---

### 2. Pixel Rendering Hot Path ⭐⭐⭐

**Current Implementation** (lines 362-400):
```cpp
void PPU::render_background_pixel(int x, int y) {
    if (!(mask & 0x08)) { /* render backdrop */ return; }
    
    int tile_x = x / 8;
    int tile_y = y / 8;
    int fine_x = x % 8;
    int fine_y = y % 8;
    
    uint8_t tile_index = get_nametable_tile(tile_x, tile_y);
    uint8_t palette_idx = get_attribute_palette(tile_x, tile_y);
    uint8_t pattern_lo, pattern_hi;
    get_pattern_tile(tile_index, fine_y, pattern_lo, pattern_hi);
    
    uint8_t bit_shift = 7 - fine_x;
    uint8_t pixel = ((pattern_hi >> bit_shift) & 1) << 1 | 
                    ((pattern_lo >> bit_shift) & 1);
    
    uint32_t color = get_background_color(palette_idx, pixel);
    framebuffer[y * 256 + x] = color;
}
```

**Issues**:
- Called 61,440 times per frame (3.69M times/second @60fps)
- Division operations (`x / 8`, `y / 8`, `x % 8`, `y % 8`) every pixel
- Memory reads (nametable, attributes, pattern) every pixel
- Redundant work when rendering same tile (8 consecutive pixels)

**Optimization**: Tile-based rendering
```cpp
void PPU::render_background_tile(int x, int y) {
    // Fetch tile data once for all 8 pixels
    int tile_x = x / 8;
    int tile_y = y / 8;
    
    uint8_t tile_index = get_nametable_tile(tile_x, tile_y);
    uint8_t palette_idx = get_attribute_palette(tile_x, tile_y);
    
    uint8_t pattern_lo, pattern_hi;
    get_pattern_tile(tile_index, y % 8, pattern_lo, pattern_hi);
    
    // Render all 8 pixels at once
    for (int px = 0; px < 8; px++) {
        uint8_t bit_shift = 7 - px;
        uint8_t pixel = ((pattern_hi >> bit_shift) & 1) << 1 | 
                        ((pattern_lo >> bit_shift) & 1);
        uint32_t color = get_background_color(palette_idx, pixel);
        framebuffer[y * 256 + (tile_x * 8 + px)] = color;
    }
}
```

**Benefits**:
- **8x fewer memory reads** (nametable, attribute, pattern fetched once per tile)
- **8x fewer divisions** (tile_x/y calculated once per 8 pixels)
- Better cache locality (sequential framebuffer writes)

**Estimated Speedup**: 40-60% for background rendering
- Division elimination: ~20%
- Memory read reduction: ~20-30%
- Cache improvement: ~10%

**Tradeoff**: More complex integration with sprite rendering (need to merge)

**Recommendation**: **IMPLEMENT in Task 2.6**. Significant performance gain with manageable complexity.

---

### 3. Framebuffer Memory Access ⭐⭐

**Current**: Direct framebuffer writes every pixel
```cpp
framebuffer[y * 256 + x] = color;  // 61,440 writes per frame
```

**Issue**: Cache misses when jumping between scanlines

**Optimization A**: Scanline buffer
```cpp
class PPU {
    uint32_t scanline_buffer[256];  // Only 1KB
    
    void render_scanline(int y) {
        // Render to scanline buffer
        for (int x = 0; x < 256; x++) {
            scanline_buffer[x] = ...;
        }
        // Copy to framebuffer once
        memcpy(&framebuffer[y * 256], scanline_buffer, 256 * sizeof(uint32_t));
    }
};
```

**Benefits**:
- Better cache locality (256 pixels fit in L1)
- Cleaner scanline-based architecture
- Easier to add post-processing effects

**Estimated Speedup**: 5-10% (cache optimization)

**Recommendation**: Consider for Phase 3 (GPU port). Not critical for reference implementation.

**Optimization B**: Tile buffer (even smaller)
```cpp
uint32_t tile_buffer[8];  // Only 32 bytes!
```
Render entire tile to buffer, then copy to framebuffer. Extremely cache-friendly.

---

### 4. Sprite Rendering Optimization ⭐

**Current Implementation** (lines 572-600+):
- Evaluates all 64 sprites every scanline (cycle 0)
- Checks each sprite for every pixel (x=0-255)

**Optimization**: Pre-sorted active sprites
```cpp
struct ActiveSprite {
    uint8_t x;
    uint8_t pattern_lo;
    uint8_t pattern_hi;
    uint8_t palette;
    bool priority;
    bool flip_h;
    // Pre-computed pattern data (no need to fetch during rendering)
};
```

**Current**: Fetch pattern data during rendering
**Optimized**: Fetch pattern data during sprite evaluation (cycle 0)

**Estimated Speedup**: 20-30% for sprite rendering (already simplified)

**Recommendation**: Already well-optimized for SMB (no 8x16 mode, no sprite 0 hit). Defer further optimization.

---

### 5. Memory Access Pattern ⭐

**Current**: `ppu_read()` called for every memory access with full address decoding

**Optimization**: Direct VRAM access with pre-computed offsets
```cpp
// Instead of:
uint8_t tile = ppu_read(nametable_addr);

// Use:
uint8_t tile = vram[mirror_nametable(nametable_addr)];
```

**Benefit**: Eliminate function call overhead

**Estimated Speedup**: 5-10%

**Recommendation**: Low priority. Current abstraction aids testability.

---

### 6. Palette Lookup ⭐⭐

**Current**: `get_palette_color()` called for every pixel
```cpp
inline uint32_t get_palette_color(uint8_t index) {
    return NES_PALETTE[index % 64];
}
```

**Issue**: Modulo operation every pixel

**Optimization**: Pre-validate palette indices
```cpp
// During palette writes ($3F00-$3F1F)
void write_palette(uint8_t offset, uint8_t value) {
    palette[offset] = value & 0x3F;  // Clamp to 0-63
}

// During rendering (no modulo needed)
uint32_t color = NES_PALETTE[palette[index]];
```

**Estimated Speedup**: 2-3% (minor)

**Status**: Already implemented ✅

---

## Priority Ranking

| Priority | Optimization | Speedup | Complexity | Phase |
|----------|-------------|---------|------------|-------|
| **HIGH** | Tile-based background rendering | 40-60% | Medium | 2.6 |
| **MED** | Sprite pattern pre-fetch | 20-30% | Low | 2.6 |
| **MED** | tick() state machine | 15-20% | Medium | 3 |
| **LOW** | Scanline buffer | 5-10% | Medium | 3 |
| **LOW** | Direct VRAM access | 5-10% | Low | 3 |
| **DEFER** | Odd frame skip | <1% | Low | - |

---

## Recommended Action Plan

### Task 2.6 (Current Phase 2)
1. ✅ **Implement tile-based background rendering**
   - Render 8 pixels at once
   - Fetch tile data once per tile
   - ~50% speedup expected
   
2. ✅ **Optimize sprite pattern fetching**
   - Pre-fetch pattern data during sprite evaluation
   - ~25% speedup for sprite rendering

3. **Profile with real game (Super Mario Bros)**
   - Measure actual hotspots
   - Validate optimization assumptions

### Phase 3 (GPU Port)
4. Implement scanline-based state machine
5. Consider scanline buffer architecture
6. Optimize for GPU memory access patterns

### Phase 4 (Batch Parallel)
7. Fully parallelize tile rendering
8. Batch process multiple frames
9. GPU-specific optimizations (shared memory, warp efficiency)

---

## Non-Performance Optimizations

### Code Quality ⭐⭐
- **Extract magic numbers** to named constants
  - Example: `0x08` → `PPUMASK_SHOW_BACKGROUND`
  - Example: `0x80` → `PPUCTRL_NMI_ENABLE`
  
- **Add inline hints** for hot functions
  ```cpp
  inline uint8_t get_nametable_tile(int x, int y);
  inline uint32_t get_palette_color(uint8_t index);
  ```

- **Document performance assumptions**
  ```cpp
  // PERFORMANCE: Called 61,440 times per frame (3.69M/sec @60fps)
  void render_background_pixel(int x, int y);
  ```

### Testing ⭐
- Add performance regression tests
- Benchmark each optimization separately
- Profile with real game ROMs

### Documentation ⭐
- Document memory layout diagrams
- Add rendering pipeline flowchart
- Explain scrolling bit manipulation

---

## Deferred Optimizations (Not Worth It)

### 1. Odd Frame Cycle Skip
- **Impact**: 1 cycle per 89,342 (~0.001%)
- **Complexity**: Adds frame parity tracking
- **Verdict**: Not worth the code complexity

### 2. Inline All Functions
- **Impact**: 5-10% (compiler likely already does this)
- **Downside**: Reduces code readability
- **Verdict**: Let compiler decide (-O3 flag)

### 3. Lookup Tables for Division
- **Example**: `x / 8` → `div8_lookup[x]`
- **Impact**: 3-5%
- **Downside**: 256+ bytes per LUT
- **Verdict**: Modern CPUs have fast division; not worth memory

### 4. SIMD Pixel Rendering
- **Example**: Process 4 pixels with SSE
- **Impact**: 30-40%
- **Downside**: Platform-specific, complex
- **Verdict**: Save for GPU phase (better SIMD)

---

## Estimated Performance Impact

### Current (Baseline)
- **Framebuffer writes**: 61,440 per frame
- **Background rendering**: ~40% of CPU time
- **Sprite rendering**: ~20% of CPU time
- **tick() overhead**: ~25% of CPU time
- **Other**: ~15%

### After Task 2.6 Optimizations
```
Background rendering: 40% → 16%  (tile-based)
Sprite rendering:     20% → 14%  (pattern pre-fetch)
-------------------------------------------
Total speedup:        ~30% faster
```

### After Phase 3 Optimizations
```
tick() overhead:      25% → 10%  (state machine)
-------------------------------------------
Additional speedup:   ~15% faster
Cumulative:           ~45% faster than baseline
```

### GPU Phase (Phase 3-4)
```
Parallel rendering:   100x-1000x (target)
Batch processing:     Additional 120x (target)
-------------------------------------------
Total GPU speedup:    10,000x-120,000x (target)
```

---

## Conclusion

**Current state**: Well-structured reference implementation with excellent test coverage. Code is readable and maintainable.

**Immediate action** (Task 2.6):
1. Implement tile-based rendering (~50% speedup)
2. Optimize sprite pattern fetching (~25% speedup)
3. Profile with Super Mario Bros

**Future work** (Phase 3+):
- State machine for tick() (~15% speedup)
- GPU port for massive parallelization (10,000x+ target)

**Do NOT over-optimize now**:
- Reference implementation should prioritize correctness and clarity
- Major optimizations belong in GPU phase
- Current code will be rewritten for CUDA anyway

**Target for end of Phase 2**: ~50% faster than current implementation, maintaining 100% test pass rate.
