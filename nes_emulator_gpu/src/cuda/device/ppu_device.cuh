#pragma once

/*
 * PPU Device Functions - Phase 3 GPU Port
 *
 * Ports the reference PPU (src/reference/ppu/ppu.cpp) to CUDA __device__ functions.
 *
 * Key changes from reference:
 *   - std::function<uint8_t(uint16_t)> chr_read  ->  const uint8_t* chr_rom
 *   - Class member functions  ->  free __device__ functions taking NESPPUState*
 *   - No exceptions, no virtual dispatch
 *   - NES_PALETTE stored in __constant__ memory (fast broadcast read)
 *
 * All Phase 2 optimizations are preserved:
 *   - Tile-based background rendering (8 pixels per CHR fetch)
 *   - Sprite pattern pre-fetch (avoid CHR reads during rendering hot path)
 *   - 256-entry palette array (no masking on lookup)
 */

#include "nes_state.h"

// ---------------------------------------------------------------------------
// NES Palette in CUDA constant memory
// 256 entries (64 real + 192 mirrored) eliminates per-lookup masking.
// ---------------------------------------------------------------------------
__constant__ uint32_t NES_PALETTE_CONST[256] = {
    // $00-$0F
    0xFF666666u, 0xFF002A88u, 0xFF1412A7u, 0xFF3B00A4u,
    0xFF5C007Eu, 0xFF6E0040u, 0xFF6C0600u, 0xFF561D00u,
    0xFF333500u, 0xFF0B4800u, 0xFF005200u, 0xFF004F08u,
    0xFF00404Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    // $10-$1F
    0xFFADADADu, 0xFF155FD9u, 0xFF4240FFu, 0xFF7527FEu,
    0xFFA01ACCu, 0xFFB71E7Bu, 0xFFB53120u, 0xFF994E00u,
    0xFF6B6D00u, 0xFF388700u, 0xFF0C9300u, 0xFF008F32u,
    0xFF007C8Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    // $20-$2F
    0xFFFFFEFFu, 0xFF64B0FFu, 0xFF9290FFu, 0xFFC676FFu,
    0xFFF36AFFu, 0xFFFE6ECCu, 0xFFFE8170u, 0xFFEA9E22u,
    0xFFBCBE00u, 0xFF88D800u, 0xFF5CE430u, 0xFF45E082u,
    0xFF48CDDEu, 0xFF4F4F4Fu, 0xFF000000u, 0xFF000000u,
    // $30-$3F
    0xFFFFFEFFu, 0xFFC0DFFFu, 0xFFD3D2FFu, 0xFFE8C8FFu,
    0xFFFBC2FFu, 0xFFFEC4EAu, 0xFFFECCC5u, 0xFFF7D8A5u,
    0xFFE4E594u, 0xFFCFEF96u, 0xFFBDF4ABu, 0xFFB3F3CCu,
    0xFFB5EBF2u, 0xFFB8B8B8u, 0xFF000000u, 0xFF000000u,
    // $40-$7F mirror of $00-$3F
    0xFF666666u, 0xFF002A88u, 0xFF1412A7u, 0xFF3B00A4u,
    0xFF5C007Eu, 0xFF6E0040u, 0xFF6C0600u, 0xFF561D00u,
    0xFF333500u, 0xFF0B4800u, 0xFF005200u, 0xFF004F08u,
    0xFF00404Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFADADADu, 0xFF155FD9u, 0xFF4240FFu, 0xFF7527FEu,
    0xFFA01ACCu, 0xFFB71E7Bu, 0xFFB53120u, 0xFF994E00u,
    0xFF6B6D00u, 0xFF388700u, 0xFF0C9300u, 0xFF008F32u,
    0xFF007C8Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFF64B0FFu, 0xFF9290FFu, 0xFFC676FFu,
    0xFFF36AFFu, 0xFFFE6ECCu, 0xFFFE8170u, 0xFFEA9E22u,
    0xFFBCBE00u, 0xFF88D800u, 0xFF5CE430u, 0xFF45E082u,
    0xFF48CDDEu, 0xFF4F4F4Fu, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFFC0DFFFu, 0xFFD3D2FFu, 0xFFE8C8FFu,
    0xFFFBC2FFu, 0xFFFEC4EAu, 0xFFFECCC5u, 0xFFF7D8A5u,
    0xFFE4E594u, 0xFFCFEF96u, 0xFFBDF4ABu, 0xFFB3F3CCu,
    0xFFB5EBF2u, 0xFFB8B8B8u, 0xFF000000u, 0xFF000000u,
    // $80-$BF mirror
    0xFF666666u, 0xFF002A88u, 0xFF1412A7u, 0xFF3B00A4u,
    0xFF5C007Eu, 0xFF6E0040u, 0xFF6C0600u, 0xFF561D00u,
    0xFF333500u, 0xFF0B4800u, 0xFF005200u, 0xFF004F08u,
    0xFF00404Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFADADADu, 0xFF155FD9u, 0xFF4240FFu, 0xFF7527FEu,
    0xFFA01ACCu, 0xFFB71E7Bu, 0xFFB53120u, 0xFF994E00u,
    0xFF6B6D00u, 0xFF388700u, 0xFF0C9300u, 0xFF008F32u,
    0xFF007C8Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFF64B0FFu, 0xFF9290FFu, 0xFFC676FFu,
    0xFFF36AFFu, 0xFFFE6ECCu, 0xFFFE8170u, 0xFFEA9E22u,
    0xFFBCBE00u, 0xFF88D800u, 0xFF5CE430u, 0xFF45E082u,
    0xFF48CDDEu, 0xFF4F4F4Fu, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFFC0DFFFu, 0xFFD3D2FFu, 0xFFE8C8FFu,
    0xFFFBC2FFu, 0xFFFEC4EAu, 0xFFFECCC5u, 0xFFF7D8A5u,
    0xFFE4E594u, 0xFFCFEF96u, 0xFFBDF4ABu, 0xFFB3F3CCu,
    0xFFB5EBF2u, 0xFFB8B8B8u, 0xFF000000u, 0xFF000000u,
    // $C0-$FF mirror
    0xFF666666u, 0xFF002A88u, 0xFF1412A7u, 0xFF3B00A4u,
    0xFF5C007Eu, 0xFF6E0040u, 0xFF6C0600u, 0xFF561D00u,
    0xFF333500u, 0xFF0B4800u, 0xFF005200u, 0xFF004F08u,
    0xFF00404Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFADADADu, 0xFF155FD9u, 0xFF4240FFu, 0xFF7527FEu,
    0xFFA01ACCu, 0xFFB71E7Bu, 0xFFB53120u, 0xFF994E00u,
    0xFF6B6D00u, 0xFF388700u, 0xFF0C9300u, 0xFF008F32u,
    0xFF007C8Du, 0xFF000000u, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFF64B0FFu, 0xFF9290FFu, 0xFFC676FFu,
    0xFFF36AFFu, 0xFFFE6ECCu, 0xFFFE8170u, 0xFFEA9E22u,
    0xFFBCBE00u, 0xFF88D800u, 0xFF5CE430u, 0xFF45E082u,
    0xFF48CDDEu, 0xFF4F4F4Fu, 0xFF000000u, 0xFF000000u,
    0xFFFFFEFFu, 0xFFC0DFFFu, 0xFFD3D2FFu, 0xFFE8C8FFu,
    0xFFFBC2FFu, 0xFFFEC4EAu, 0xFFFECCC5u, 0xFFF7D8A5u,
    0xFFE4E594u, 0xFFCFEF96u, 0xFFBDF4ABu, 0xFFB3F3CCu,
    0xFFB5EBF2u, 0xFFB8B8B8u, 0xFF000000u, 0xFF000000u,
};

// ---------------------------------------------------------------------------
// Palette lookup (direct, no masking thanks to 256-entry table)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint32_t ppu_get_palette_color(uint8_t index) {
    return NES_PALETTE_CONST[index];
}

// ---------------------------------------------------------------------------
// Nametable mirroring
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint16_t ppu_mirror_nametable(const NESPPUState* ppu, uint16_t addr) {
    addr = (addr - 0x2000u) & 0x0FFFu;
    switch (ppu->mirroring) {
        case MIRROR_HORIZONTAL:
            return ((addr / 0x400u) & 0x02u) ? (0x400u + (addr & 0x3FFu)) : (addr & 0x3FFu);
        case MIRROR_VERTICAL:
            return addr & 0x7FFu;
        case MIRROR_SINGLE_A:
            return addr & 0x3FFu;
        case MIRROR_SINGLE_B:
            return 0x400u | (addr & 0x3FFu);
        default:
            return addr & 0x7FFu;
    }
}

// ---------------------------------------------------------------------------
// PPU address-space read
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_mem_read(const NESPPUState* ppu,
                                                  const uint8_t* chr_rom,
                                                  uint16_t addr) {
    addr &= 0x3FFFu;
    if (addr < 0x2000u) {
        return chr_rom ? __ldg(&chr_rom[addr]) : 0u;
    } else if (addr < 0x3F00u) {
        return ppu->vram[ppu_mirror_nametable(ppu, addr)];
    } else {
        uint8_t palette_addr = (uint8_t)((addr - 0x3F00u) & 0x1Fu);
        if ((palette_addr & 0x13u) == 0x10u) palette_addr &= 0x0Fu;
        return ppu->palette[palette_addr];
    }
}

// ---------------------------------------------------------------------------
// PPU address-space write
// ---------------------------------------------------------------------------
__device__ __forceinline__ void ppu_mem_write(NESPPUState* ppu, uint16_t addr, uint8_t value) {
    addr &= 0x3FFFu;
    if (addr < 0x2000u) {
        // CHR ROM writes ignored (no CHR RAM support in Phase 3)
    } else if (addr < 0x3F00u) {
        ppu->vram[ppu_mirror_nametable(ppu, addr)] = value;
    } else {
        uint8_t palette_addr = (uint8_t)((addr - 0x3F00u) & 0x1Fu);
        if ((palette_addr & 0x13u) == 0x10u) palette_addr &= 0x0Fu;
        ppu->palette[palette_addr] = value;
    }
}

// ---------------------------------------------------------------------------
// VRAM increment (PPUCTRL bit 2: 0 = +1 across, 1 = +32 down)
// ---------------------------------------------------------------------------
__device__ __forceinline__ void ppu_increment_v(NESPPUState* ppu) {
    ppu->v += (ppu->ctrl & 0x04u) ? 32u : 1u;
    ppu->v &= 0x7FFFu;
}

// ---------------------------------------------------------------------------
// CPU register interface: read ($2000-$2007)
// ---------------------------------------------------------------------------
__device__ uint8_t ppu_read_register(NESPPUState* ppu, const uint8_t* chr_rom, uint16_t addr) {
    addr = 0x2000u + (addr & 0x0007u);
    uint8_t result = 0;
    switch (addr) {
        case 0x2002: // PPUSTATUS
            result = (ppu->status & 0xE0u) | (ppu->read_buffer & 0x1Fu);
            ppu->status &= ~0x80u;  // Clear VBlank flag on read
            ppu->w = 0;
            break;
        case 0x2004: // OAMDATA
            result = ppu->oam[ppu->oam_addr];
            break;
        case 0x2007: // PPUDATA
            result = ppu_mem_read(ppu, chr_rom, ppu->v);
            if ((ppu->v & 0x3F00u) == 0x3F00u) {
                ppu->read_buffer = ppu_mem_read(ppu, chr_rom, ppu->v & 0x2FFFu);
            } else {
                uint8_t temp = ppu->read_buffer;
                ppu->read_buffer = result;
                result = temp;
            }
            ppu_increment_v(ppu);
            break;
        default:
            result = 0;
            break;
    }
    return result;
}

// ---------------------------------------------------------------------------
// CPU register interface: write ($2000-$2007)
// ---------------------------------------------------------------------------
__device__ void ppu_write_register(NESPPUState* ppu, uint16_t addr, uint8_t value) {
    addr = 0x2000u + (addr & 0x0007u);
    switch (addr) {
        case 0x2000: // PPUCTRL
            ppu->ctrl = value;
            ppu->t = (ppu->t & 0xF3FFu) | (uint16_t)((value & 0x03u) << 10);
            break;
        case 0x2001: // PPUMASK
            ppu->mask = value;
            break;
        case 0x2002: // PPUSTATUS (read-only, writes ignored)
            break;
        case 0x2003: // OAMADDR
            ppu->oam_addr = value;
            break;
        case 0x2004: // OAMDATA
            ppu->oam[ppu->oam_addr++] = value;
            break;
        case 0x2005: // PPUSCROLL (two writes: X then Y)
            if (!ppu->w) {
                ppu->t = (ppu->t & 0xFFE0u) | (value >> 3);
                ppu->fine_x = value & 0x07u;
                ppu->w = 1;
            } else {
                ppu->t = (ppu->t & 0x8FFFu) | (uint16_t)((value & 0x07u) << 12);
                ppu->t = (ppu->t & 0xFC1Fu) | (uint16_t)((value & 0xF8u) << 2);
                ppu->w = 0;
            }
            break;
        case 0x2006: // PPUADDR (two writes: high then low byte)
            if (!ppu->w) {
                ppu->t = (ppu->t & 0x80FFu) | (uint16_t)((value & 0x3Fu) << 8);
                ppu->w = 1;
            } else {
                ppu->t = (ppu->t & 0xFF00u) | value;
                ppu->v = ppu->t;
                ppu->w = 0;
            }
            break;
        case 0x2007: // PPUDATA
            ppu_mem_write(ppu, ppu->v, value);
            ppu_increment_v(ppu);
            break;
    }
}

// ---------------------------------------------------------------------------
// OAM DMA: copy 256 bytes from CPU RAM page into OAM
// ---------------------------------------------------------------------------
__device__ __forceinline__ void ppu_oam_dma(NESPPUState* ppu, const uint8_t* cpu_ram, uint8_t page) {
    uint16_t start = (uint16_t)page * 0x100u;
    for (int i = 0; i < 256; i++) {
        ppu->oam[(ppu->oam_addr + i) & 0xFFu] = cpu_ram[start + i];
    }
}

// ---------------------------------------------------------------------------
// Fast nametable read (addr already in $2000-$3EFF range)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_read_nametable_fast(const NESPPUState* ppu, uint16_t addr) {
    return ppu->vram[ppu_mirror_nametable(ppu, addr)];
}

// ---------------------------------------------------------------------------
// Fast palette read by raw index 0-31
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_read_palette_fast(const NESPPUState* ppu, uint8_t index) {
    index &= 0x1Fu;
    if ((index & 0x13u) == 0x10u) index &= 0x0Fu;
    return ppu->palette[index];
}

// ---------------------------------------------------------------------------
// Background: get nametable tile at (nt_x, nt_y)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_get_nametable_tile(const NESPPUState* ppu, int nt_x, int nt_y) {
    uint16_t nt_base = 0x2000u | ((uint16_t)(ppu->ctrl & 0x03u) << 10);
    uint16_t addr = nt_base + (uint16_t)(nt_y * 32 + nt_x);
    return ppu_read_nametable_fast(ppu, addr);
}

// ---------------------------------------------------------------------------
// Background: get attribute palette index for tile (nt_x, nt_y)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_get_attribute_palette(const NESPPUState* ppu, int nt_x, int nt_y) {
    uint16_t nt_base = 0x2000u | ((uint16_t)(ppu->ctrl & 0x03u) << 10);
    uint16_t attr_addr = nt_base + 0x3C0u + (uint16_t)((nt_y / 4) * 8 + (nt_x / 4));
    uint8_t attr_byte = ppu_read_nametable_fast(ppu, attr_addr);
    int qx = (nt_x % 4) / 2;
    int qy = (nt_y % 4) / 2;
    int shift = (qy * 2 + qx) * 2;
    return (attr_byte >> shift) & 0x03u;
}

// ---------------------------------------------------------------------------
// Background: fetch pattern tile row (lo and hi planes)
// ---------------------------------------------------------------------------
__device__ __forceinline__ void ppu_get_pattern_tile(const NESPPUState* ppu,
                                                      const uint8_t* chr_rom,
                                                      uint8_t tile_index,
                                                      uint8_t fine_y,
                                                      uint8_t* lo_out,
                                                      uint8_t* hi_out) {
    uint16_t pattern_base = (ppu->ctrl & 0x10u) ? 0x1000u : 0x0000u;
    uint16_t tile_addr = pattern_base + (uint16_t)(tile_index * 16);
    *lo_out = chr_rom ? __ldg(&chr_rom[tile_addr + fine_y])     : 0u;
    *hi_out = chr_rom ? __ldg(&chr_rom[tile_addr + fine_y + 8]) : 0u;
}

// ---------------------------------------------------------------------------
// Background: get final pixel color (palette_idx 0-3, pixel 0-3)
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Background color as palette index (stored in framebuffer for compact storage)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint8_t ppu_get_background_palette_index(const NESPPUState* ppu,
                                                                      uint8_t palette_idx,
                                                                      uint8_t pixel) {
    if (pixel == 0) return ppu->palette[0];
    return ppu->palette[palette_idx * 4 + pixel];
}

// Legacy full-color lookup (used in nes_get_framebuffer output only)
__device__ __forceinline__ uint32_t ppu_get_background_color(const NESPPUState* ppu,
                                                               uint8_t palette_idx,
                                                               uint8_t pixel) {
    if (pixel == 0) return ppu_get_palette_color(ppu->palette[0]);
    return ppu_get_palette_color(ppu->palette[palette_idx * 4 + pixel]);
}

// ---------------------------------------------------------------------------
// Background: OPTIMIZED tile renderer (8 pixels per tile, Phase 2 optimization)
// ---------------------------------------------------------------------------
__device__ void ppu_render_background_tile(NESPPUState* ppu,
                                            const uint8_t* chr_rom,
                                            int tile_x, int y) {
    int base_x = tile_x * 8;

    if (!(ppu->mask & 0x08u)) {
        // Background disabled: fill with backdrop palette index
        uint8_t backdrop = ppu->palette[0];
        for (int px = 0; px < 8; px++) {
            ppu->framebuffer[y * 256 + base_x + px] = backdrop;
        }
        return;
    }

    int tile_y = y / 8;
    int fine_y = y % 8;

    // Fetch tile data ONCE for all 8 pixels (Phase 2 optimization)
    uint8_t tile_index = ppu_get_nametable_tile(ppu, tile_x, tile_y);
    uint8_t palette_idx = ppu_get_attribute_palette(ppu, tile_x, tile_y);
    uint8_t lo, hi;
    ppu_get_pattern_tile(ppu, chr_rom, tile_index, (uint8_t)fine_y, &lo, &hi);

    for (int px = 0; px < 8; px++) {
        uint8_t shift = (uint8_t)(7 - px);
        uint8_t pixel = (uint8_t)(((hi >> shift) & 1u) << 1 | ((lo >> shift) & 1u));
        ppu->framebuffer[y * 256 + base_x + px] =
            ppu_get_background_palette_index(ppu, palette_idx, pixel);
    }
}

// ---------------------------------------------------------------------------
// Sprite: get sprite pattern data with vertical-flip support
// Returns packed 16-bit: lo plane in high byte, hi plane in low byte
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint16_t ppu_get_sprite_pattern(const NESPPUState* ppu,
                                                             const uint8_t* chr_rom,
                                                             uint8_t tile,
                                                             int fine_y,
                                                             bool vflip) {
    if (vflip) fine_y = 7 - fine_y;
    uint16_t base = (ppu->ctrl & 0x08u) ? 0x1000u : 0x0000u;
    uint16_t addr = base + (uint16_t)(tile * 16 + fine_y);
    uint8_t lo = chr_rom ? __ldg(&chr_rom[addr])     : 0u;
    uint8_t hi = chr_rom ? __ldg(&chr_rom[addr + 8]) : 0u;
    return (uint16_t)((lo << 8) | hi);
}

// ---------------------------------------------------------------------------
// Sprite: evaluate sprites visible on current scanline (Phase 2: pre-fetch patterns)
// ---------------------------------------------------------------------------
__device__ void ppu_evaluate_sprites(NESPPUState* ppu, const uint8_t* chr_rom) {
    ppu->active_sprite_count = 0;

    for (int i = 0; i < 64; i++) {
        uint8_t spr_y = ppu->oam[i * 4];
        int row = ppu->scanline - (int)(spr_y + 1);

        if (row >= 0 && row < 8) {
            if (ppu->active_sprite_count < NES_MAX_SPRITES) {
                ActiveSpriteGPU* s = &ppu->active_sprites[ppu->active_sprite_count];
                s->x = ppu->oam[i * 4 + 3];
                s->y = spr_y;
                s->tile = ppu->oam[i * 4 + 1];
                s->attr = ppu->oam[i * 4 + 2];
                s->oam_index = (uint8_t)i;
                bool vflip = (s->attr & 0x80u) != 0;
                s->pattern = ppu_get_sprite_pattern(ppu, chr_rom, s->tile, row, vflip);
                ppu->active_sprite_count++;
            } else {
                ppu->status |= 0x20u;  // Sprite overflow
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Sprite: get sprite color from sprite palette ($3F10-$3F1F)
// ---------------------------------------------------------------------------
__device__ __forceinline__ uint32_t ppu_get_sprite_color(const NESPPUState* ppu,
                                                           uint8_t palette_idx,
                                                           uint8_t pixel) {
    uint8_t offset = (uint8_t)(0x10u + palette_idx * 4 + pixel);
    uint8_t color_index = ppu_read_palette_fast(ppu, offset);
    return ppu_get_palette_color(color_index);
}

// ---------------------------------------------------------------------------
// Sprite: render one sprite pixel at (x, y)
// ---------------------------------------------------------------------------
__device__ void ppu_render_sprite_pixel(NESPPUState* ppu, int x, int y) {
    if (!(ppu->mask & 0x10u)) return;

    for (int i = 0; i < ppu->active_sprite_count; i++) {
        const ActiveSpriteGPU* spr = &ppu->active_sprites[i];
        int dx = x - (int)spr->x;
        if (dx < 0 || dx >= 8) continue;

        bool hflip = (spr->attr & 0x40u) != 0;
        if (hflip) dx = 7 - dx;

        uint16_t pattern = spr->pattern;
        uint8_t lo_bit = (uint8_t)((pattern >> (15 - dx)) & 1u);
        uint8_t hi_bit = (uint8_t)((pattern >> (7  - dx)) & 1u);
        uint8_t pixel  = (uint8_t)((hi_bit << 1) | lo_bit);

        if (pixel == 0) continue;

        uint8_t pal_idx = spr->attr & 0x03u;
        // Get sprite palette index (stored compactly in framebuffer)
        uint8_t offset = (uint8_t)(0x10u + pal_idx * 4 + pixel);
        uint8_t color_index = ppu_read_palette_fast(ppu, offset);

        bool behind_bg = (spr->attr & 0x20u) != 0;
        if (behind_bg) {
            uint8_t bg_idx = ppu->framebuffer[y * 256 + x];
            if (bg_idx != ppu->palette[0]) continue;  // Behind opaque background
        }

        ppu->framebuffer[y * 256 + x] = color_index;
        return;  // First non-transparent sprite wins
    }
}

// ---------------------------------------------------------------------------
// Scrolling helpers
// ---------------------------------------------------------------------------
__device__ __forceinline__ void ppu_copy_horizontal_bits(NESPPUState* ppu) {
    ppu->v = (ppu->v & 0xFBE0u) | (ppu->t & 0x041Fu);
}

__device__ __forceinline__ void ppu_copy_vertical_bits(NESPPUState* ppu) {
    ppu->v = (ppu->v & 0x841Fu) | (ppu->t & 0x7BE0u);
}

// ---------------------------------------------------------------------------
// PPU tick: advance one PPU cycle
//
// Timing:
//   cycle++  at start (matches Phase 2 fix: cycle is the CURRENT executing cycle)
//   Scanlines 0-239: visible, render pixels
//   Scanline 240:    post-render idle
//   Scanline 241:    VBlank start (set flag + NMI at cycle 1)
//   Scanline 261:    pre-render (clear flags at cycle 1, copy vert bits 280-304)
//   Frame ready set when entering scanline 261
// ---------------------------------------------------------------------------
__device__ void ppu_tick(NESPPUState* ppu, const uint8_t* chr_rom) {
    // Advance counters (at START of tick, per Phase 2 fix)
    ppu->cycle++;
    if (ppu->cycle > 340) {
        ppu->cycle = 0;
        ppu->scanline++;
        if (ppu->scanline > 261) {
            ppu->scanline = 0;
        }
        if (ppu->scanline == 261) {
            ppu->frame_ready = 1;
        }
    }

    // Fast path: visible scanlines (0-239) ~85% of all ticks
    if (ppu->scanline < 240) {
        if (ppu->cycle == 0) {
            ppu_evaluate_sprites(ppu, chr_rom);
            return;
        }
        if (ppu->cycle <= 256) {
            int x = ppu->cycle - 1;
            if ((x & 7) == 0) {
                ppu_render_background_tile(ppu, chr_rom, x >> 3, ppu->scanline);
            }
            ppu_render_sprite_pixel(ppu, x, ppu->scanline);
        }
        return;
    }

    // Special scanlines
    if (ppu->scanline == 241 && ppu->cycle == 1) {
        ppu->status |= 0x80u;  // VBlank flag
        if (ppu->ctrl & 0x80u) {
            ppu->nmi_flag = 1;  // NMI if enabled
        }
        return;
    }

    if (ppu->scanline == 261) {
        if (ppu->cycle == 1) {
            ppu->status &= ~0xE0u;  // Clear VBlank, sprite 0 hit, overflow
            ppu->nmi_flag = 0;
        } else if (ppu->cycle >= 280 && ppu->cycle <= 304) {
            if (ppu->mask & 0x18u) {
                ppu_copy_vertical_bits(ppu);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Reset PPU to power-on state
// ---------------------------------------------------------------------------
__device__ void ppu_reset(NESPPUState* ppu) {
    ppu->ctrl        = 0;
    ppu->mask        = 0;
    ppu->status      = 0;
    ppu->oam_addr    = 0;
    ppu->v           = 0;
    ppu->t           = 0;
    ppu->fine_x      = 0;
    ppu->w           = 0;
    ppu->read_buffer = 0;
    ppu->scanline    = 0;
    ppu->cycle       = 0;
    ppu->frame_ready = 0;
    ppu->nmi_flag    = 0;
    ppu->active_sprite_count = 0;

    for (int i = 0; i < NES_VRAM_SIZE; i++) ppu->vram[i] = 0;
    for (int i = 0; i < NES_PALETTE_SIZE; i++) ppu->palette[i] = 0;
    for (int i = 0; i < NES_OAM_SIZE; i++) ppu->oam[i] = 0;
    // framebuffer is a pointer to an external buffer; cleared by the frame kernel.
    ppu->framebuffer = nullptr;
}
