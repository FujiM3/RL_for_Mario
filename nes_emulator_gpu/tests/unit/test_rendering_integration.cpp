#include <gtest/gtest.h>
#include "ppu/ppu.h"
#include "ppu/palette.h"
#include <cstring>

using namespace nes;

// Integration test for rendering with tick()
TEST(RenderingIntegration, BasicFrameRendering) {
    PPU ppu;
    
    // Set up a simple CHR pattern
    uint8_t test_chr[0x2000];
    memset(test_chr, 0, sizeof(test_chr));
    
    // Create a simple pattern: solid block (tile 0x01)
    for (int y = 0; y < 8; y++) {
        test_chr[0x01 * 16 + y] = 0xFF;       // All pixels set (low bit)
        test_chr[0x01 * 16 + y + 8] = 0x00;   // No high bits
    }
    
    ppu.set_chr_callback([&test_chr](uint16_t addr) -> uint8_t {
        return test_chr[addr & 0x1FFF];
    });
    
    // Fill nametable with tile 0x01
    ppu.write_register(0x2006, 0x20); // PPUADDR high
    ppu.write_register(0x2006, 0x00); // PPUADDR low
    for (int i = 0; i < 32 * 30; i++) {
        ppu.write_register(0x2007, 0x01); // Write tile 0x01
    }
    
    // Set palette colors
    ppu.write_register(0x2006, 0x3F); // Palette address
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x0F); // Universal background: white
    ppu.write_register(0x2007, 0x16); // Color 1: blue
    ppu.write_register(0x2007, 0x27); // Color 2: green
    ppu.write_register(0x2007, 0x30); // Color 3: light white
    
    // Enable background rendering
    ppu.write_register(0x2000, 0x00); // PPUCTRL: use pattern table $0000
    ppu.write_register(0x2001, 0x08); // PPUMASK: show background
    
    // Simulate one frame (341 cycles × 262 scanlines)
    int total_cycles = 341 * 262;
    for (int i = 0; i < total_cycles; i++) {
        ppu.tick();
    }
    
    // Check that frame is ready
    EXPECT_TRUE(ppu.is_frame_ready());
    
    // Get framebuffer
    const uint32_t* fb = ppu.get_framebuffer();
    
    // Verify some pixels are rendered (non-zero)
    // Since we filled with tile 0x01 (all pixels set), expect color 1 (blue)
    uint32_t expected_color = get_palette_color(0x16); // Blue
    
    // Check a few pixels in the visible area
    EXPECT_EQ(expected_color, fb[0]);           // Top-left
    EXPECT_EQ(expected_color, fb[255]);         // Top-right
    EXPECT_EQ(expected_color, fb[239 * 256]);   // Bottom-left
    EXPECT_EQ(expected_color, fb[239 * 256 + 255]); // Bottom-right
    EXPECT_EQ(expected_color, fb[120 * 256 + 128]); // Center
}

TEST(RenderingIntegration, BackgroundDisabledUsesBackdrop) {
    PPU ppu;
    
    // Set backdrop color
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x0F); // White
    
    // Disable background rendering
    ppu.write_register(0x2001, 0x00); // PPUMASK: background off
    
    // Simulate one frame
    for (int i = 0; i < 341 * 262; i++) {
        ppu.tick();
    }
    
    // Get framebuffer
    const uint32_t* fb = ppu.get_framebuffer();
    uint32_t expected_backdrop = get_palette_color(0x0F); // White
    
    // All pixels should be backdrop color
    EXPECT_EQ(expected_backdrop, fb[0]);
    EXPECT_EQ(expected_backdrop, fb[100 * 256 + 100]);
    EXPECT_EQ(expected_backdrop, fb[200 * 256 + 200]);
}

TEST(RenderingIntegration, FrameReadyFlag) {
    PPU ppu;
    
    EXPECT_FALSE(ppu.is_frame_ready());
    
    // Simulate one frame (scanline 261 sets frame_ready)
    for (int i = 0; i < 341 * 262; i++) {
        ppu.tick();
    }
    
    EXPECT_TRUE(ppu.is_frame_ready());
    
    // Acknowledge frame
    ppu.get_framebuffer();
    // Note: PPU doesn't auto-clear frame_ready, need to check if that's desired behavior
}

TEST(RenderingIntegration, MultipleFrames) {
    PPU ppu;
    
    // Set up simple rendering
    ppu.write_register(0x2001, 0x08); // Enable background
    
    // Render 3 frames
    for (int frame = 0; frame < 3; frame++) {
        for (int i = 0; i < 341 * 262; i++) {
            ppu.tick();
        }
        EXPECT_TRUE(ppu.is_frame_ready());
    }
}

TEST(RenderingIntegration, VBlankDuringRendering) {
    PPU ppu;
    
    // Enable VBlank NMI
    ppu.write_register(0x2000, 0x80); // PPUCTRL: NMI enabled
    
    // Run to VBlank (scanline 241)
    for (int i = 0; i < 341 * 241 + 1; i++) {
        ppu.tick();
    }
    
    // Should have VBlank flag set
    uint8_t status = ppu.read_register(0x2002);
    // Reading clears VBlank, but we can check NMI was triggered
    EXPECT_TRUE(ppu.nmi_triggered());
}
