#ifndef NES_PALETTE_H
#define NES_PALETTE_H

#include <cstdint>

namespace nes {

/**
 * Standard NES Palette (64 colors)
 * 
 * The NES has a fixed palette of 64 colors (indexed 0-63).
 * These RGB values are approximate, as different TVs displayed them differently.
 * 
 * This palette is based on the commonly-used "2C02" palette.
 * 
 * Usage:
 *   uint8_t palette_index = 0x0F; // White
 *   uint32_t rgb_color = NES_PALETTE[palette_index];
 */
const uint32_t NES_PALETTE[64] = {
    // $0x00-$0x0F
    0xFF666666, 0xFF002A88, 0xFF1412A7, 0xFF3B00A4,
    0xFF5C007E, 0xFF6E0040, 0xFF6C0600, 0xFF561D00,
    0xFF333500, 0xFF0B4800, 0xFF005200, 0xFF004F08,
    0xFF00404D, 0xFF000000, 0xFF000000, 0xFF000000,
    
    // $0x10-$0x1F
    0xFFADADAD, 0xFF155FD9, 0xFF4240FF, 0xFF7527FE,
    0xFFA01ACC, 0xFFB71E7B, 0xFFB53120, 0xFF994E00,
    0xFF6B6D00, 0xFF388700, 0xFF0C9300, 0xFF008F32,
    0xFF007C8D, 0xFF000000, 0xFF000000, 0xFF000000,
    
    // $0x20-$0x2F
    0xFFFFFEFF, 0xFF64B0FF, 0xFF9290FF, 0xFFC676FF,
    0xFFF36AFF, 0xFFFE6ECC, 0xFFFE8170, 0xFFEA9E22,
    0xFFBCBE00, 0xFF88D800, 0xFF5CE430, 0xFF45E082,
    0xFF48CDDE, 0xFF4F4F4F, 0xFF000000, 0xFF000000,
    
    // $0x30-$0x3F
    0xFFFFFEFF, 0xFFC0DFFF, 0xFFD3D2FF, 0xFFE8C8FF,
    0xFFFBC2FF, 0xFFFEC4EA, 0xFFFECCC5, 0xFFF7D8A5,
    0xFFE4E594, 0xFFCFEF96, 0xFFBDF4AB, 0xFFB3F3CC,
    0xFFB5EBF2, 0xFFB8B8B8, 0xFF000000, 0xFF000000,
};

/**
 * Get RGB color from NES palette index
 * 
 * @param index Palette index (0-63), automatically masked to 6 bits
 * @return 32-bit RGBA color (0xAARRGGBB format, alpha always 0xFF)
 */
inline uint32_t get_palette_color(uint8_t index) {
    return NES_PALETTE[index & 0x3F];
}

} // namespace nes

#endif // NES_PALETTE_H
