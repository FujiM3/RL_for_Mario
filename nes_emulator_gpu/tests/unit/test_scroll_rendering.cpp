#include <gtest/gtest.h>
#include "ppu/ppu.h"
#include "ppu/palette.h"
#include <cstring>

using namespace nes;

class ScrollingRendering : public ::testing::Test {
protected:
    PPU ppu;
    
    void SetUp() override {
        // Initialize PPU
        ppu.write_register(0x2000, 0x00);  // PPUCTRL = 0 (nametable 0)
        ppu.write_register(0x2001, 0x0E);  // Enable background + sprites
        
        // Set up CHR callback with simple pattern
        ppu.set_chr_callback([](uint16_t addr) -> uint8_t {
            // Simple pattern: all 0xFF for testing
            return 0xFF;
        });
        
        // Fill nametable with test data
        ppu.write_register(0x2006, 0x20);  // PPUADDR high
        ppu.write_register(0x2006, 0x00);  // PPUADDR low
        
        // Fill with tile indices 0-255
        for (int i = 0; i < 0x3C0; i++) {
            ppu.write_register(0x2007, i & 0xFF);
        }
        
        // Set up palette
        ppu.write_register(0x2006, 0x3F);
        ppu.write_register(0x2006, 0x00);
        ppu.write_register(0x2007, 0x0F);  // Backdrop
        ppu.write_register(0x2007, 0x30);  // Color 1
        ppu.write_register(0x2007, 0x20);  // Color 2
        ppu.write_register(0x2007, 0x10);  // Color 3
    }
};

TEST_F(ScrollingRendering, BasicScrolledRendering) {
    // Set scroll position (16, 8)
    ppu.write_register(0x2005, 0x10);  // X = 16
    ppu.write_register(0x2005, 0x08);  // Y = 8
    
    // Render a frame
    for (int i = 0; i < 261 * 341; i++) {
        ppu.tick();
    }
    
    // Check that frame was rendered
    EXPECT_TRUE(ppu.is_frame_ready());
    
    // Get framebuffer
    const uint32_t* fb = ppu.get_framebuffer();
    EXPECT_NE(fb, nullptr);
    
    // Frame should have some non-backdrop pixels
    uint32_t backdrop = nes::get_palette_color(0x0F);
    bool has_content = false;
    for (int i = 0; i < 256 * 240; i++) {
        if (fb[i] != backdrop) {
            has_content = true;
            break;
        }
    }
    
    EXPECT_TRUE(has_content) << "Scrolled rendering should produce content";
}

TEST_F(ScrollingRendering, ScrollAcrossNametables) {
    // Set horizontal mirroring
    ppu.set_mirroring(PPU::HORIZONTAL);
    
    // Scroll to edge of nametable (248, 0) - near horizontal boundary
    ppu.write_register(0x2005, 0xF8);  // X = 248
    ppu.write_register(0x2005, 0x00);  // Y = 0
    
    // Render a frame
    for (int i = 0; i < 261 * 341; i++) {
        ppu.tick();
    }
    
    EXPECT_TRUE(ppu.is_frame_ready());
}

TEST_F(ScrollingRendering, ScrollVerticalBoundary) {
    // Scroll to vertical edge (0, 232) - near bottom
    ppu.write_register(0x2005, 0x00);  // X = 0
    ppu.write_register(0x2005, 0xE8);  // Y = 232
    
    // Render a frame
    for (int i = 0; i < 261 * 341; i++) {
        ppu.tick();
    }
    
    EXPECT_TRUE(ppu.is_frame_ready());
}

TEST_F(ScrollingRendering, NoScrollNoV) {
    // No scroll, should still work with old rendering
    ppu.write_register(0x2005, 0x00);  // X = 0
    ppu.write_register(0x2005, 0x00);  // Y = 0
    
    // Render multiple frames
    // A full frame is 262 scanlines (0-261) × 341 cycles = 89342 ticks
    for (int frame = 0; frame < 3; frame++) {
        ppu.clear_frame_ready();
        for (int i = 0; i < 262 * 341; i++) {
            ppu.tick();
        }
        EXPECT_TRUE(ppu.is_frame_ready()) << "Frame " << frame << " should complete";
    }
}

TEST_F(ScrollingRendering, MirroringWithScroll) {
    // Test horizontal mirroring with scroll
    ppu.set_mirroring(PPU::HORIZONTAL);
    
    // Write different data to nametable 0 and 2
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0xAA);
    
    ppu.write_register(0x2006, 0x28);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0xBB);
    
    // Scroll and render
    ppu.write_register(0x2005, 0x10);
    ppu.write_register(0x2005, 0x10);
    
    for (int i = 0; i < 261 * 341; i++) {
        ppu.tick();
    }
    
    EXPECT_TRUE(ppu.is_frame_ready());
}
