#include "ppu.h"
#include "palette.h"
#include <cstring>

namespace nes {

PPU::PPU()
    : ctrl(0), mask(0), status(0), oam_addr(0),
      v(0), t(0), x(0), w(false), read_buffer(0),
      chr_read(nullptr), mirroring(HORIZONTAL),
      scanline(0), cycle(0), frame_ready(false), nmi_flag(false)
{
    std::memset(vram, 0, sizeof(vram));
    std::memset(palette, 0, sizeof(palette));
    std::memset(oam, 0, sizeof(oam));
    std::memset(framebuffer, 0, sizeof(framebuffer));
}

// ========== CPU Register Interface ==========

uint8_t PPU::read_register(uint16_t addr) {
    // Registers mirror every 8 bytes: $2000-$2007 repeated at $2008-$3FFF
    addr = 0x2000 + (addr & 0x0007);
    
    uint8_t result = 0;
    
    switch (addr) {
        case 0x2000: // PPUCTRL (write-only)
            // Reading returns open bus (last value on bus)
            result = 0;
            break;
            
        case 0x2001: // PPUMASK (write-only)
            result = 0;
            break;
            
        case 0x2002: // PPUSTATUS
            // Bits 0-4: open bus (last PPU data value)
            // Bit 5: Sprite overflow
            // Bit 6: Sprite 0 Hit
            // Bit 7: VBlank started
            result = (status & 0xE0) | (read_buffer & 0x1F);
            
            // Reading $2002 clears bit 7 (VBlank flag)
            status &= ~0x80;
            
            // Reading $2002 also resets w toggle
            w = false;
            break;
            
        case 0x2003: // OAMADDR (write-only)
            result = 0;
            break;
            
        case 0x2004: // OAMDATA
            result = oam[oam_addr];
            // Reading OAMDATA also increments OAMADDR (though games rarely do this)
            // Note: Some sources say it doesn't increment on read, but let's follow hardware behavior
            // Actually, reading OAMDATA does NOT increment on real hardware during rendering
            // but DOES increment when not rendering. For simplicity, we increment always.
            break;
            
        case 0x2005: // PPUSCROLL (write-only)
            result = 0;
            break;
            
        case 0x2006: // PPUADDR (write-only)
            result = 0;
            break;
            
        case 0x2007: // PPUDATA
            result = ppu_read(v);
            
            // Palette reads are immediate, but still update buffer
            if ((v & 0x3F00) == 0x3F00) {
                // Reading palette: return value immediately
                // But buffer gets nametable data "under" the palette
                read_buffer = ppu_read(v & 0x2FFF);
            } else {
                // Non-palette: return buffered value
                uint8_t temp = read_buffer;
                read_buffer = result;
                result = temp;
            }
            
            increment_v();
            break;
    }
    
    return result;
}

void PPU::write_register(uint16_t addr, uint8_t value) {
    // Registers mirror every 8 bytes
    addr = 0x2000 + (addr & 0x0007);
    
    switch (addr) {
        case 0x2000: // PPUCTRL
            ctrl = value;
            // t: ...GH.. ........ <- d: ......GH
            // (bits 10-11 of t from bits 0-1 of data)
            t = (t & 0xF3FF) | ((value & 0x03) << 10);
            break;
            
        case 0x2001: // PPUMASK
            mask = value;
            break;
            
        case 0x2002: // PPUSTATUS (read-only)
            // Writing does nothing
            break;
            
        case 0x2003: // OAMADDR
            oam_addr = value;
            break;
            
        case 0x2004: // OAMDATA
            oam[oam_addr] = value;
            oam_addr++; // Auto-increment (wraps around at 256)
            break;
            
        case 0x2005: // PPUSCROLL (written twice: X then Y)
            if (!w) {
                // First write (X scroll)
                // t: ....... ...HGFED <- d: HGFED...
                // x:              CBA <- d: .....CBA
                // w:                  <- 1
                t = (t & 0xFFE0) | (value >> 3);
                x = value & 0x07;
                w = true;
            } else {
                // Second write (Y scroll)
                // t: CBA..HG FED..... <- d: HGFEDCBA
                // w:                  <- 0
                t = (t & 0x8FFF) | ((value & 0x07) << 12);
                t = (t & 0xFC1F) | ((value & 0xF8) << 2);
                w = false;
            }
            break;
            
        case 0x2006: // PPUADDR (written twice: high byte then low byte)
            if (!w) {
                // First write (high byte)
                // t: .CDEFGH ........ <- d: ..CDEFGH
                //        <unused>     <- d: AB......
                // t: Z...... ........ <- 0 (bit 14 is cleared)
                // w:                  <- 1
                t = (t & 0x80FF) | ((value & 0x3F) << 8);
                w = true;
            } else {
                // Second write (low byte)
                // t: ....... HGFEDCBA <- d: HGFEDCBA
                // v: <...all bits...> <- t: <...all bits...>
                // w:                  <- 0
                t = (t & 0xFF00) | value;
                v = t;
                w = false;
            }
            break;
            
        case 0x2007: // PPUDATA
            ppu_write(v, value);
            increment_v();
            break;
    }
}

// ========== OAM DMA ==========

void PPU::oam_dma(const uint8_t* cpu_memory, uint8_t page) {
    // Copy 256 bytes from CPU memory page to OAM
    uint16_t start_addr = page * 0x100;
    for (int i = 0; i < 256; i++) {
        oam[(oam_addr + i) & 0xFF] = cpu_memory[start_addr + i];
    }
    // OAM DMA takes 513 or 514 CPU cycles (not implemented here, handled by caller)
}

// ========== PPU Timing ==========

void PPU::tick() {
    // ========== Advance Counters ==========
    // Advance at start of tick, so cycle/scanline represent the current cycle being executed
    cycle++;
    
    if (cycle > 340) {
        cycle = 0;
        scanline++;
        
        if (scanline > 261) {
            // Wrap to scanline 0 (start of next frame)
            scanline = 0;
            
            // TODO: Odd frame skips cycle 0 of scanline 0 (when rendering enabled)
            // This makes odd frames 1 PPU cycle shorter (89341 vs 89342)
        }
        
        // Frame is ready when we complete scanline 260 and enter scanline 261 (pre-render)
        // Scanline 261 is preparation for the next frame
        if (scanline == 261) {
            frame_ready = true;
        }
    }
    
    // ========== Visible Scanlines (0-239) ==========
    if (scanline < 240) {
        // Sprite evaluation at cycle 0
        if (cycle == 0) {
            evaluate_sprites();
        }
        
        // Render pixels (cycle 1-256)
        if (cycle >= 1 && cycle <= 256) {
            int x = cycle - 1;
            int y = scanline;
            
            // OPTIMIZATION: Render background tile-by-tile (every 8th pixel)
            // This reduces memory reads by 8x
            if ((x % 8) == 0) {
                int tile_x = x / 8;
                render_background_tile(tile_x, y);
            }
            
            // Render sprite pixel (still per-pixel, but only where sprites exist)
            render_sprite_pixel(x, y);
        }
        
        // Cycles 257-320: Sprite fetches for next scanline
        // Cycles 321-336: Background fetches for next scanline
        // Cycles 337-340: Unknown fetches
        // (Not implemented in simplified version)
    }
    
    // ========== Post-render Scanline (240) ==========
    // Idle scanline, no rendering
    
    // ========== VBlank Scanlines (241-260) ==========
    if (scanline == 241 && cycle == 1) {
        // Set VBlank flag
        status |= 0x80;
        
        // Trigger NMI if enabled
        if (ctrl & 0x80) {
            nmi_flag = true;
        }
    }
    
    // ========== Pre-render Scanline (261) ==========
    if (scanline == 261) {
        if (cycle == 1) {
            // Clear VBlank, sprite 0 hit, sprite overflow flags
            status &= ~0xE0;
            nmi_flag = false;
        }
        
        // Cycles 280-304: Copy vertical bits from t to v (scroll reset)
        if (cycle >= 280 && cycle <= 304) {
            if (mask & 0x18) {  // If rendering enabled
                copy_vertical_bits();
            }
        }
    }
}

// ========== PPU Memory Access ==========

uint8_t PPU::ppu_read(uint16_t addr) {
    addr &= 0x3FFF; // 14-bit address space
    
    if (addr < 0x2000) {
        // Pattern Tables ($0000-$1FFF) - from CHR ROM
        if (chr_read) {
            return chr_read(addr);
        }
        return 0;
    }
    else if (addr < 0x3F00) {
        // Name Tables ($2000-$2FFF, mirrors to $3000-$3EFF)
        addr = mirror_nametable(addr);
        return vram[addr];
    }
    else {
        // Palette ($3F00-$3FFF)
        addr = (addr - 0x3F00) & 0x1F;
        
        // Palette mirroring: $3F10, $3F14, $3F18, $3F1C mirror to $3F00, $3F04, $3F08, $3F0C
        if ((addr & 0x13) == 0x10) {
            addr &= 0x0F;
        }
        
        return palette[addr];
    }
}

void PPU::ppu_write(uint16_t addr, uint8_t value) {
    addr &= 0x3FFF;
    
    if (addr < 0x2000) {
        // Pattern Tables - CHR ROM is usually read-only
        // (CHR RAM would be handled by mapper)
        // Ignore writes for now
    }
    else if (addr < 0x3F00) {
        // Name Tables
        addr = mirror_nametable(addr);
        vram[addr] = value;
    }
    else {
        // Palette
        addr = (addr - 0x3F00) & 0x1F;
        
        // Palette mirroring
        if ((addr & 0x13) == 0x10) {
            addr &= 0x0F;
        }
        
        palette[addr] = value;
    }
}

uint16_t PPU::mirror_nametable(uint16_t addr) {
    // Address is in range $2000-$2FFF (or $3000-$3EFF which mirrors)
    addr = (addr - 0x2000) & 0x0FFF; // Normalize to 0-$FFF
    
    switch (mirroring) {
        case HORIZONTAL:
            // $2000=$2400, $2800=$2C00
            // Physical VRAM layout: [A][A][B][B]
            // Nametables: 0 and 1 map to first 1KB, 2 and 3 map to second 1KB
            return ((addr / 0x400) & 0x02) ? (0x400 + (addr & 0x3FF)) : (addr & 0x3FF);
            
        case VERTICAL:
            // $2000=$2800, $2400=$2C00
            // Physical VRAM layout: [A][B][A][B]
            return addr & 0x7FF;
            
        case SINGLE_SCREEN_A:
            // All map to first 1KB
            return addr & 0x3FF;
            
        case SINGLE_SCREEN_B:
            // All map to second 1KB
            return 0x400 | (addr & 0x3FF);
            
        case FOUR_SCREEN:
            // All 4KB used (requires extra VRAM on cartridge)
            // For 2KB VRAM, wrap around
            return addr & 0x7FF;
    }
    
    return addr & 0x7FF; // Default to vertical
}

void PPU::increment_v() {
    // Increment v by 1 or 32 based on PPUCTRL bit 2
    if (ctrl & 0x04) {
        v += 32; // Down
    } else {
        v += 1;  // Across
    }
    v &= 0x7FFF; // Keep within 15 bits
}

// ========== Background Rendering ==========

void PPU::render_background_pixel(int x, int y) {
    // Check if background rendering is enabled
    if (!(mask & 0x08)) {
        // Background disabled, use backdrop color
        framebuffer[y * 256 + x] = get_palette_color(palette[0]);
        return;
    }
    
    // Calculate which tile we're in
    // The screen is 256x240, tiles are 8x8
    // Name table is 32x30 tiles
    int tile_x = x / 8;
    int tile_y = y / 8;
    
    // Fine position within the tile (0-7)
    int fine_x = x % 8;
    int fine_y = y % 8;
    
    // Get tile index from name table
    uint8_t tile_index = get_nametable_tile(tile_x, tile_y);
    
    // Get attribute (palette index)
    uint8_t palette_idx = get_attribute_palette(tile_x, tile_y);
    
    // Get pattern data for this row of the tile
    uint8_t pattern_lo, pattern_hi;
    get_pattern_tile(tile_index, fine_y, pattern_lo, pattern_hi);
    
    // Extract the 2-bit pixel value at fine_x position
    // Bits are stored MSB first, so we need to shift from the left
    uint8_t bit_shift = 7 - fine_x;
    uint8_t pixel = ((pattern_hi >> bit_shift) & 1) << 1 | ((pattern_lo >> bit_shift) & 1);
    
    // Get final RGB color
    uint32_t color = get_background_color(palette_idx, pixel);
    
    // Write to framebuffer
    framebuffer[y * 256 + x] = color;
}

// OPTIMIZED: Render an entire 8-pixel tile at once
// Reduces memory reads by 8x and divisions by 8x
void PPU::render_background_tile(int tile_x, int y) {
    // Check if background rendering is enabled
    if (!(mask & 0x08)) {
        // Background disabled, use backdrop color for all 8 pixels
        uint32_t backdrop = get_palette_color(palette[0]);
        int base_x = tile_x * 8;
        for (int px = 0; px < 8; px++) {
            framebuffer[y * 256 + base_x + px] = backdrop;
        }
        return;
    }
    
    int tile_y = y / 8;
    int fine_y = y % 8;
    
    // Fetch tile data ONCE for all 8 pixels
    uint8_t tile_index = get_nametable_tile(tile_x, tile_y);
    uint8_t palette_idx = get_attribute_palette(tile_x, tile_y);
    
    uint8_t pattern_lo, pattern_hi;
    get_pattern_tile(tile_index, fine_y, pattern_lo, pattern_hi);
    
    // Render all 8 pixels using the fetched data
    int base_x = tile_x * 8;
    for (int px = 0; px < 8; px++) {
        uint8_t bit_shift = 7 - px;
        uint8_t pixel = ((pattern_hi >> bit_shift) & 1) << 1 | 
                        ((pattern_lo >> bit_shift) & 1);
        
        uint32_t color = get_background_color(palette_idx, pixel);
        framebuffer[y * 256 + base_x + px] = color;
    }
}

uint8_t PPU::get_nametable_tile(int nt_x, int nt_y) {
    // Calculate nametable address
    // Each nametable is $400 bytes
    // First $3C0 bytes are tile indices (32x30 = 960 = $3C0)
    
    // Get base nametable from PPUCTRL bits 0-1
    uint16_t nt_base = 0x2000 | ((ctrl & 0x03) << 10);
    
    // Calculate address within nametable
    uint16_t addr = nt_base + (nt_y * 32) + nt_x;
    
    // Read from VRAM (with mirroring)
    return ppu_read(addr);
}

uint8_t PPU::get_attribute_palette(int nt_x, int nt_y) {
    // Attribute table starts at $23C0 (offset $3C0 from nametable base)
    // Each byte controls a 4x4 tile area (32x32 pixels)
    // The 4x4 area is divided into 4 2x2 quadrants
    
    // Get base nametable
    uint16_t nt_base = 0x2000 | ((ctrl & 0x03) << 10);
    
    // Attribute table address
    // Each attribute byte covers 4x4 tiles
    uint16_t attr_addr = nt_base + 0x3C0 + (nt_y / 4) * 8 + (nt_x / 4);
    
    // Read attribute byte
    uint8_t attr_byte = ppu_read(attr_addr);
    
    // Which quadrant within the 4x4 tile area?
    // Top-left: bits 0-1
    // Top-right: bits 2-3
    // Bottom-left: bits 4-5
    // Bottom-right: bits 6-7
    int quadrant_x = (nt_x % 4) / 2; // 0 or 1
    int quadrant_y = (nt_y % 4) / 2; // 0 or 1
    int shift = (quadrant_y * 2 + quadrant_x) * 2;
    
    // Extract 2-bit palette index
    return (attr_byte >> shift) & 0x03;
}

void PPU::get_pattern_tile(uint8_t tile_index, uint8_t fine_y, uint8_t& lo, uint8_t& hi) {
    // Pattern table address from PPUCTRL bit 4 (for background)
    uint16_t pattern_base = (ctrl & 0x10) ? 0x1000 : 0x0000;
    
    // Each tile is 16 bytes:
    // - Bytes 0-7: low bit plane
    // - Bytes 8-15: high bit plane
    uint16_t tile_addr = pattern_base + (tile_index * 16);
    
    // Read the specific row (fine_y) from both planes
    lo = chr_read ? chr_read(tile_addr + fine_y) : 0;
    hi = chr_read ? chr_read(tile_addr + fine_y + 8) : 0;
}

uint32_t PPU::get_background_color(uint8_t palette_idx, uint8_t pixel) {
    // Background palettes are at $3F00-$3F0F
    // Each palette is 4 bytes (4 colors)
    // pixel is 0-3 (2 bits)
    
    if (pixel == 0) {
        // Pixel 0 uses universal background color
        return get_palette_color(palette[0]);
    }
    
    // Calculate palette RAM address
    uint8_t palette_addr = palette_idx * 4 + pixel;
    
    // Read from palette RAM and convert to RGB
    return get_palette_color(palette[palette_addr]);
}

// ========== Scrolling-Aware Rendering ==========

uint8_t PPU::get_tile_from_v() {
    // Extract nametable address from v register
    // v bits: yyy NN YYYYY XXXXX
    // Nametable address: $2000 + (NN << 10) + (YYYYY << 5) + XXXXX
    uint16_t addr = 0x2000 | (v & 0x0FFF);
    return ppu_read(addr);
}

uint8_t PPU::get_attribute_from_v() {
    // Attribute table starts at $23C0 (offset $3C0 from nametable base)
    // v bits: yyy NN YYYYY XXXXX
    
    // Get nametable base
    uint16_t nt_base = 0x2000 | (v & 0x0C00);
    
    // Extract coarse X and Y
    int coarse_x = v & 0x001F;
    int coarse_y = (v >> 5) & 0x001F;
    
    // Attribute table address
    uint16_t attr_addr = nt_base + 0x3C0 + (coarse_y / 4) * 8 + (coarse_x / 4);
    
    // Read attribute byte
    uint8_t attr_byte = ppu_read(attr_addr);
    
    // Which quadrant within the 4x4 tile area?
    int quadrant_x = (coarse_x % 4) / 2;
    int quadrant_y = (coarse_y % 4) / 2;
    int shift = (quadrant_y * 2 + quadrant_x) * 2;
    
    // Extract 2-bit palette index
    return (attr_byte >> shift) & 0x03;
}

void PPU::render_pixel_from_v(int screen_x, int screen_y) {
    // Check if background rendering is enabled
    if (!(mask & 0x08)) {
        framebuffer[screen_y * 256 + screen_x] = get_palette_color(palette[0]);
        return;
    }
    
    // Get tile index from v register
    uint8_t tile_index = get_tile_from_v();
    
    // Get attribute (palette) from v register
    uint8_t palette_idx = get_attribute_from_v();
    
    // Get fine Y from v register (bits 12-14)
    uint8_t fine_y = (v >> 12) & 0x07;
    
    // Get pattern data for this row
    uint8_t pattern_lo, pattern_hi;
    get_pattern_tile(tile_index, fine_y, pattern_lo, pattern_hi);
    
    // Get fine X from x register (0-7)
    uint8_t fine_x_pos = x;  // Use fine X scroll register
    
    // Extract the 2-bit pixel value at fine_x position
    uint8_t bit_shift = 7 - fine_x_pos;
    uint8_t pixel = ((pattern_hi >> bit_shift) & 1) << 1 | 
                    ((pattern_lo >> bit_shift) & 1);
    
    // Get final RGB color
    uint32_t color = get_background_color(palette_idx, pixel);
    
    // Write to framebuffer
    framebuffer[screen_y * 256 + screen_x] = color;
}

// ========== Sprite Rendering ==========

void PPU::evaluate_sprites() {
    // Find sprites visible on current scanline
    active_sprite_count = 0;
    
    for (int i = 0; i < 64; i++) {
        uint8_t y = oam[i * 4];
        
        // Check if sprite is on current scanline
        // Y position is offset by 1
        int row = scanline - (y + 1);
        
        // Only 8×8 sprites (simplified version, no 8×16)
        if (row >= 0 && row < 8) {
            if (active_sprite_count < 8) {
                // Add to active sprites
                active_sprites[active_sprite_count].x = oam[i * 4 + 3];
                active_sprites[active_sprite_count].y = y;
                active_sprites[active_sprite_count].tile = oam[i * 4 + 1];
                active_sprites[active_sprite_count].attr = oam[i * 4 + 2];
                active_sprites[active_sprite_count].oam_index = i;
                active_sprite_count++;
            } else {
                // Sprite overflow (simplified - just set flag)
                status |= 0x20;
                break;  // Early exit to save cycles
            }
        }
    }
}

uint16_t PPU::get_sprite_pattern(uint8_t tile, int fine_y, bool vflip) {
    // Vertical flip
    if (vflip) {
        fine_y = 7 - fine_y;
    }
    
    // Sprite pattern table selected by PPUCTRL bit 3
    uint16_t base = (ctrl & 0x08) ? 0x1000 : 0x0000;
    uint16_t addr = base + tile * 16 + fine_y;
    
    // Read pattern data from CHR
    uint8_t lo = chr_read ? chr_read(addr) : 0;
    uint8_t hi = chr_read ? chr_read(addr + 8) : 0;
    
    // Return as 16-bit (lo in high byte, hi in low byte for easier bit extraction)
    return (lo << 8) | hi;
}

uint32_t PPU::get_sprite_color(uint8_t palette_idx, uint8_t pixel) {
    // Sprite palettes are at $3F10-$3F1F
    // palette_idx is 0-3, pixel is 1-3 (0 is transparent)
    uint16_t addr = 0x3F10 + palette_idx * 4 + pixel;
    uint8_t color_index = ppu_read(addr);
    return nes::get_palette_color(color_index);
}

void PPU::render_sprite_pixel(int x, int y) {
    // Check if sprite rendering is enabled
    if (!(mask & 0x10)) return;
    
    // Iterate through active sprites (already in priority order)
    for (int i = 0; i < active_sprite_count; i++) {
        ActiveSprite& spr = active_sprites[i];
        
        // Check if pixel is within sprite X range
        int dx = x - spr.x;
        if (dx < 0 || dx >= 8) continue;
        
        // Horizontal flip
        bool hflip = spr.attr & 0x40;
        if (hflip) {
            dx = 7 - dx;
        }
        
        // Vertical flip
        bool vflip = spr.attr & 0x80;
        int dy = y - (spr.y + 1);
        
        // Get pattern data
        uint16_t pattern = get_sprite_pattern(spr.tile, dy, vflip);
        
        // Extract pixel value (2 bits)
        uint8_t lo_bit = (pattern >> (15 - dx)) & 1;
        uint8_t hi_bit = (pattern >> (7 - dx)) & 1;
        uint8_t pixel = (hi_bit << 1) | lo_bit;
        
        // Pixel 0 is transparent
        if (pixel == 0) continue;
        
        // Get sprite palette index (bits 0-1 of attributes)
        uint8_t pal_idx = spr.attr & 0x03;
        uint32_t color = get_sprite_color(pal_idx, pixel);
        
        // Priority handling (simplified)
        // Bit 5 of attributes: 0=front, 1=behind background
        bool behind_bg = spr.attr & 0x20;
        
        if (behind_bg) {
            // Check if background pixel is non-zero
            uint32_t bg_color = framebuffer[y * 256 + x];
            uint32_t backdrop = nes::get_palette_color(palette[0]);
            
            if (bg_color != backdrop) {
                // Background is non-transparent, sprite is behind
                continue;
            }
        }
        
        // Render sprite pixel
        framebuffer[y * 256 + x] = color;
        
        // First non-transparent sprite wins (priority)
        return;
    }
}

// ========== Scrolling Helpers ==========

void PPU::increment_coarse_x() {
    // Increment coarse X scroll (bits 0-4 of v)
    if ((v & 0x001F) == 31) {
        // Wrap from 31 to 0 and switch horizontal nametable
        v &= ~0x001F;  // Clear coarse X
        v ^= 0x0400;   // Switch horizontal nametable
    } else {
        v++;  // Increment coarse X
    }
}

void PPU::increment_fine_y() {
    // Increment fine Y scroll (bits 12-14 of v)
    if ((v & 0x7000) != 0x7000) {
        // Fine Y < 7, just increment
        v += 0x1000;
    } else {
        // Fine Y = 7, wrap to 0 and increment coarse Y
        v &= ~0x7000;  // Clear fine Y
        int coarse_y = (v & 0x03E0) >> 5;
        
        if (coarse_y == 29) {
            // Row 29 is the last row of tiles, wrap and switch vertical nametable
            coarse_y = 0;
            v ^= 0x0800;  // Switch vertical nametable
        } else if (coarse_y == 31) {
            // Row 31 wraps to 0 without switching nametable (attribute overflow)
            coarse_y = 0;
        } else {
            coarse_y++;
        }
        
        // Update coarse Y
        v = (v & ~0x03E0) | (coarse_y << 5);
    }
}

void PPU::copy_horizontal_bits() {
    // Copy horizontal scroll bits from t to v
    // Bits 0-4 (coarse X) and bit 10 (horizontal nametable)
    v = (v & 0xFBE0) | (t & 0x041F);
}

void PPU::copy_vertical_bits() {
    // Copy vertical scroll bits from t to v
    // Bits 5-9 (coarse Y), bits 12-14 (fine Y), bit 11 (vertical nametable)
    v = (v & 0x841F) | (t & 0x7BE0);
}

} // namespace nes


