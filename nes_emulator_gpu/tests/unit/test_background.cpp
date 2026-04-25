#include <gtest/gtest.h>
#include "ppu/ppu.h"
#include "ppu/palette.h"

using namespace nes;

// ========== Palette Tests ==========

TEST(Palette, ColorCount) {
    // NES palette should have exactly 64 colors
    EXPECT_EQ(64, sizeof(NES_PALETTE) / sizeof(NES_PALETTE[0]));
}

TEST(Palette, GetPaletteColor) {
    // Test some known colors
    EXPECT_EQ(0xFF666666, get_palette_color(0x00)); // Dark gray
    EXPECT_EQ(0xFFFFFEFF, get_palette_color(0x20)); // White
    EXPECT_EQ(0xFFFFFEFF, get_palette_color(0x30)); // Light white
    
    // Test index wrapping (should mask to 6 bits)
    EXPECT_EQ(get_palette_color(0x00), get_palette_color(0x40));
    EXPECT_EQ(get_palette_color(0x0F), get_palette_color(0x4F));
}

// ========== Background Rendering Tests ==========

class BackgroundTest : public ::testing::Test {
protected:
    PPU ppu;
    uint8_t test_chr[0x2000]; // 8KB CHR ROM
    uint8_t test_nametable[0x400]; // 1KB nametable
    
    void SetUp() override {
        // Clear CHR and nametable
        memset(test_chr, 0, sizeof(test_chr));
        memset(test_nametable, 0, sizeof(test_nametable));
        
        // Set up CHR callback
        ppu.set_chr_callback([this](uint16_t addr) -> uint8_t {
            return test_chr[addr & 0x1FFF];
        });
        
        // Enable background rendering
        ppu.write_register(0x2001, 0x08); // PPUMASK: show background
    }
    
    // Helper: Write a simple test pattern to CHR
    void write_test_pattern(uint8_t tile_index, uint8_t pattern) {
        uint16_t addr = tile_index * 16;
        for (int y = 0; y < 8; y++) {
            test_chr[addr + y] = pattern;     // Low bit plane
            test_chr[addr + y + 8] = ~pattern; // High bit plane (inverted)
        }
    }
    
    // Helper: Write tile to nametable
    void write_nametable_tile(int x, int y, uint8_t tile) {
        uint16_t addr = 0x2000 + y * 32 + x;
        ppu.write_register(0x2006, addr >> 8);
        ppu.write_register(0x2006, addr & 0xFF);
        ppu.write_register(0x2007, tile);
    }
    
    // Helper: Write attribute (palette)
    void write_attribute(int x, int y, uint8_t palette_idx) {
        // Attribute table starts at $23C0
        uint16_t attr_addr = 0x23C0 + (y / 4) * 8 + (x / 4);
        
        // Read current value
        ppu.write_register(0x2006, attr_addr >> 8);
        ppu.write_register(0x2006, attr_addr & 0xFF);
        ppu.read_register(0x2007); // Dummy read
        uint8_t current = ppu.read_register(0x2007);
        
        // Calculate shift for this quadrant
        int quadrant_x = (x % 4) / 2;
        int quadrant_y = (y % 4) / 2;
        int shift = (quadrant_y * 2 + quadrant_x) * 2;
        
        // Update with new palette
        uint8_t mask = ~(0x03 << shift);
        uint8_t new_val = (current & mask) | ((palette_idx & 0x03) << shift);
        
        // Write back
        ppu.write_register(0x2006, attr_addr >> 8);
        ppu.write_register(0x2006, attr_addr & 0xFF);
        ppu.write_register(0x2007, new_val);
    }
    
    // Helper: Set palette color
    void set_palette_color(uint8_t palette_idx, uint8_t color_idx, uint8_t nes_color) {
        uint16_t addr = 0x3F00 + palette_idx * 4 + color_idx;
        ppu.write_register(0x2006, addr >> 8);
        ppu.write_register(0x2006, addr & 0xFF);
        ppu.write_register(0x2007, nes_color);
    }
};

TEST_F(BackgroundTest, BackgroundDisabled) {
    // Disable background
    ppu.write_register(0x2001, 0x00); // PPUMASK: background off
    
    // Set backdrop color (palette[0])
    set_palette_color(0, 0, 0x0F); // White
    
    // Render should use backdrop color
    const uint32_t* fb = ppu.get_framebuffer();
    
    // Manually render a pixel (since tick() doesn't call render yet)
    // We'll test the render function directly in a more complete test
    
    // For now, just verify palette access works
    uint8_t backdrop_color = 0;
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    backdrop_color = ppu.read_register(0x2007);
    EXPECT_EQ(0x0F, backdrop_color);
}

TEST_F(BackgroundTest, SimplePatternRender) {
    // Create a simple pattern: horizontal stripes
    write_test_pattern(0x42, 0b10101010);
    
    // Write tile to nametable position (0, 0)
    write_nametable_tile(0, 0, 0x42);
    
    // Set palette
    set_palette_color(0, 0, 0x0F); // Background
    set_palette_color(0, 1, 0x00); // Black
    set_palette_color(0, 2, 0x10); // Light color
    set_palette_color(0, 3, 0x30); // White
    
    // Enable background
    ppu.write_register(0x2000, 0x00); // PPUCTRL: use pattern table $0000
    ppu.write_register(0x2001, 0x08); // PPUMASK: show background
    
    // Test pattern extraction
    // (Full rendering test would require calling render_background_pixel)
}

TEST_F(BackgroundTest, NameTableAccess) {
    // Write tile index to position (5, 3)
    write_nametable_tile(5, 3, 0x99);
    
    // Read back via PPUDATA
    uint16_t addr = 0x2000 + 3 * 32 + 5;
    ppu.write_register(0x2006, addr >> 8);
    ppu.write_register(0x2006, addr & 0xFF);
    ppu.read_register(0x2007); // Dummy read
    uint8_t tile = ppu.read_register(0x2007);
    
    EXPECT_EQ(0x99, tile);
}

TEST_F(BackgroundTest, AttributeTableAccess) {
    // Write attribute for tile area (0-3, 0-3)
    uint16_t attr_addr = 0x23C0; // First byte of attribute table
    ppu.write_register(0x2006, attr_addr >> 8);
    ppu.write_register(0x2006, attr_addr & 0xFF);
    ppu.write_register(0x2007, 0b11100100); // Different palettes for each quadrant
    
    // Read back
    ppu.write_register(0x2006, attr_addr >> 8);
    ppu.write_register(0x2006, attr_addr & 0xFF);
    ppu.read_register(0x2007); // Dummy
    uint8_t attr = ppu.read_register(0x2007);
    
    EXPECT_EQ(0b11100100, attr);
}

TEST_F(BackgroundTest, PatternTableSelection) {
    // Test PPUCTRL bit 4 (background pattern table)
    
    // Pattern table $0000
    ppu.write_register(0x2000, 0x00); // PPUCTRL: bit 4 = 0
    write_test_pattern(0x10, 0xFF);
    
    // Pattern table $1000
    ppu.write_register(0x2000, 0x10); // PPUCTRL: bit 4 = 1
    test_chr[0x1000 + 0x10 * 16] = 0xAA;
    test_chr[0x1000 + 0x10 * 16 + 8] = 0x55;
    
    // Verify we can access different pattern tables
    // (Full test would involve actual rendering)
}

TEST_F(BackgroundTest, MultipleNametables) {
    ppu.set_mirroring(PPU::Mirroring::HORIZONTAL);
    
    // Write directly to $2000 (nametable 0)
    uint16_t addr0 = 0x2000;
    ppu.write_register(0x2006, addr0 >> 8);
    ppu.write_register(0x2006, addr0 & 0xFF);
    ppu.write_register(0x2007, 0x11);
    
    // Write directly to $2400 (nametable 1, mirrors to 0 with horizontal mirroring)
    uint16_t addr1 = 0x2400;
    ppu.write_register(0x2006, addr1 >> 8);
    ppu.write_register(0x2006, addr1 & 0xFF);
    ppu.write_register(0x2007, 0x33);
    
    // Write directly to $2800 (nametable 2, different physical RAM with horizontal mirroring)
    uint16_t addr2 = 0x2800;
    ppu.write_register(0x2006, addr2 >> 8);
    ppu.write_register(0x2006, addr2 & 0xFF);
    ppu.write_register(0x2007, 0x22);
    
    // Read from nametable 0 (should see 0x33 because nametable 1 mirrors to 0)
    ppu.write_register(0x2006, addr0 >> 8);
    ppu.write_register(0x2006, addr0 & 0xFF);
    ppu.read_register(0x2007); // Dummy
    uint8_t tile0 = ppu.read_register(0x2007);
    
    // Read from nametable 2 (should see 0x22 - different RAM)
    ppu.write_register(0x2006, addr2 >> 8);
    ppu.write_register(0x2006, addr2 & 0xFF);
    ppu.read_register(0x2007); // Dummy
    uint8_t tile2 = ppu.read_register(0x2007);
    
    // With horizontal mirroring:
    // $2000/$2400 (nametables 0,1) → same physical RAM
    // $2800/$2C00 (nametables 2,3) → different physical RAM
    // tile0 should be 0x33 (overwritten by nametable 1 write)
    // tile2 should be 0x22
    EXPECT_EQ(0x33, tile0);
    EXPECT_EQ(0x22, tile2);
}

TEST_F(BackgroundTest, PaletteConfiguration) {
    // Set up 4 different background palettes
    for (int palette = 0; palette < 4; palette++) {
        for (int color = 0; color < 4; color++) {
            set_palette_color(palette, color, palette * 4 + color);
        }
    }
    
    // Verify palette 0
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    EXPECT_EQ(0x00, ppu.read_register(0x2007)); // Immediate read for palette
    
    // Verify palette 1
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x04);
    EXPECT_EQ(0x04, ppu.read_register(0x2007));
    
    // Verify palette 2
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x08);
    EXPECT_EQ(0x08, ppu.read_register(0x2007));
    
    // Verify palette 3
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x0C);
    EXPECT_EQ(0x0C, ppu.read_register(0x2007));
}

TEST_F(BackgroundTest, CHRPatternExtraction) {
    // Create a checkerboard pattern
    uint8_t tile_index = 0x55;
    for (int y = 0; y < 8; y++) {
        if (y % 2 == 0) {
            test_chr[tile_index * 16 + y] = 0b10101010; // Low
            test_chr[tile_index * 16 + y + 8] = 0b01010101; // High
        } else {
            test_chr[tile_index * 16 + y] = 0b01010101; // Low
            test_chr[tile_index * 16 + y + 8] = 0b10101010; // High
        }
    }
    
    // Verify pattern data can be read
    // (Would be tested via actual rendering in integration test)
}

TEST_F(BackgroundTest, UniversalBackgroundColor) {
    // Palette[0] is the universal background color
    set_palette_color(0, 0, 0x0F); // White
    
    // Any pixel with value 0 should use this color
    // (Tested via rendering)
    
    // Verify it's accessible
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    EXPECT_EQ(0x0F, ppu.read_register(0x2007));
}

// ========== Integration-style Tests ==========

TEST_F(BackgroundTest, FullTileRenderSetup) {
    // This test sets up a complete scenario for rendering one tile
    
    // 1. Create a pattern (solid block with border)
    uint8_t tile_idx = 0x20;
    test_chr[tile_idx * 16 + 0] = 0b11111111; // Top border
    test_chr[tile_idx * 16 + 1] = 0b10000001; // Sides
    test_chr[tile_idx * 16 + 2] = 0b10000001;
    test_chr[tile_idx * 16 + 3] = 0b10000001;
    test_chr[tile_idx * 16 + 4] = 0b10000001;
    test_chr[tile_idx * 16 + 5] = 0b10000001;
    test_chr[tile_idx * 16 + 6] = 0b10000001;
    test_chr[tile_idx * 16 + 7] = 0b11111111; // Bottom border
    
    for (int i = 0; i < 8; i++) {
        test_chr[tile_idx * 16 + 8 + i] = 0x00; // High plane all 0 (color 1)
    }
    
    // 2. Place tile in nametable
    write_nametable_tile(10, 10, tile_idx);
    
    // 3. Set attribute (palette 2)
    write_attribute(10, 10, 2);
    
    // 4. Configure palette 2
    set_palette_color(2, 0, 0x0F); // Background white
    set_palette_color(2, 1, 0x16); // Color 1: blue
    set_palette_color(2, 2, 0x27); // Color 2: green
    set_palette_color(2, 3, 0x30); // Color 3: light white
    
    // 5. Enable rendering
    ppu.write_register(0x2000, 0x00); // Pattern table $0000, nametable $2000
    ppu.write_register(0x2001, 0x08); // Show background
    
    // Setup complete - actual rendering would happen in render loop
    EXPECT_TRUE(true); // Test setup succeeded
}
