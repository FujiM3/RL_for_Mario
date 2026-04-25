#include <gtest/gtest.h>
#include "ppu/ppu.h"

using namespace nes;

// ========== Basic Construction ==========

TEST(PPU, Construction) {
    PPU ppu;
    
    // Initially no frame ready
    EXPECT_FALSE(ppu.is_frame_ready());
    
    // No NMI triggered
    EXPECT_FALSE(ppu.nmi_triggered());
    
    // Framebuffer should exist
    EXPECT_NE(nullptr, ppu.get_framebuffer());
}

// ========== PPUCTRL ($2000) Tests ==========

TEST(PPU, PPUCTRL_Write) {
    PPU ppu;
    
    // Write to PPUCTRL
    ppu.write_register(0x2000, 0x90); // Enable NMI (bit 7), set nametable 0
    
    // Writing PPUCTRL should update t register (bits 10-11)
    // We can't directly check t, but we can verify behavior through PPUADDR
    
    // Write PPUADDR twice to set v = t
    ppu.write_register(0x2006, 0x00); // High byte
    ppu.write_register(0x2006, 0x00); // Low byte
    
    // Now write PPUCTRL with nametable = 2 (bits 0-1 = 10b)
    ppu.write_register(0x2000, 0x02);
    
    // t should now have bits 10-11 set to 10b
    // (Can't directly test t, but future tests will verify scrolling behavior)
}

// ========== PPUSTATUS ($2002) Tests ==========

TEST(PPU, PPUSTATUS_VBlank_Set) {
    PPU ppu;
    
    // Initially, VBlank flag should be clear
    uint8_t status = ppu.read_register(0x2002);
    EXPECT_EQ(0, status & 0x80); // VBlank flag (bit 7) clear
    
    // Simulate entering VBlank (scanline 241)
    for (int i = 0; i < 241 * 341 + 1; i++) {
        ppu.tick();
    }
    
    // Now VBlank flag should be set
    status = ppu.read_register(0x2002);
    EXPECT_NE(0, status & 0x80); // VBlank flag set
}

TEST(PPU, PPUSTATUS_VBlank_ClearedOnRead) {
    PPU ppu;
    
    // Enter VBlank
    for (int i = 0; i < 241 * 341 + 1; i++) {
        ppu.tick();
    }
    
    // VBlank flag should be set
    uint8_t status1 = ppu.read_register(0x2002);
    EXPECT_NE(0, status1 & 0x80);
    
    // Reading again should return 0 (flag was cleared)
    uint8_t status2 = ppu.read_register(0x2002);
    EXPECT_EQ(0, status2 & 0x80);
}

TEST(PPU, PPUSTATUS_ResetsWriteToggle) {
    PPU ppu;
    
    // Write once to PPUSCROLL (sets w = true)
    ppu.write_register(0x2005, 0x12);
    
    // Read PPUSTATUS (should reset w = false)
    ppu.read_register(0x2002);
    
    // Write to PPUSCROLL again - should be treated as first write
    ppu.write_register(0x2005, 0x34);
    
    // If w was properly reset, the behavior is correct
    // (Can't directly test, but this verifies no crash/unexpected behavior)
}

// ========== OAMADDR / OAMDATA ($2003 / $2004) Tests ==========

TEST(PPU, OAMADDR_Write) {
    PPU ppu;
    
    ppu.write_register(0x2003, 0x42);
    
    // Can't directly read OAMADDR, but next OAMDATA write should go to address 0x42
    ppu.write_register(0x2004, 0x99);
    
    // Read back from OAMDATA
    ppu.write_register(0x2003, 0x42); // Reset address
    uint8_t value = ppu.read_register(0x2004);
    EXPECT_EQ(0x99, value);
}

TEST(PPU, OAMDATA_ReadWrite) {
    PPU ppu;
    
    // Set OAM address
    ppu.write_register(0x2003, 0x00);
    
    // Write 4 bytes (one sprite)
    ppu.write_register(0x2004, 0x10); // Y - writes increment oam_addr
    ppu.write_register(0x2004, 0x20); // Tile
    ppu.write_register(0x2004, 0x30); // Attributes
    ppu.write_register(0x2004, 0x40); // X
    
    // Read back - need to reset address before each read since reads don't auto-increment
    ppu.write_register(0x2003, 0x00);
    EXPECT_EQ(0x10, ppu.read_register(0x2004));
    ppu.write_register(0x2003, 0x01);
    EXPECT_EQ(0x20, ppu.read_register(0x2004));
    ppu.write_register(0x2003, 0x02);
    EXPECT_EQ(0x30, ppu.read_register(0x2004));
    ppu.write_register(0x2003, 0x03);
    EXPECT_EQ(0x40, ppu.read_register(0x2004));
}

TEST(PPU, OAMDATA_AutoIncrement) {
    PPU ppu;
    
    ppu.write_register(0x2003, 0xFE); // Near end of OAM
    
    ppu.write_register(0x2004, 0xAA);
    ppu.write_register(0x2004, 0xBB);
    ppu.write_register(0x2004, 0xCC); // Should wrap to 0x00
    
    // Verify wrap-around
    ppu.write_register(0x2003, 0xFE);
    EXPECT_EQ(0xAA, ppu.read_register(0x2004));
    
    ppu.write_register(0x2003, 0x00);
    EXPECT_EQ(0xCC, ppu.read_register(0x2004));
}

// ========== PPUSCROLL ($2005) Tests ==========

TEST(PPU, PPUSCROLL_TwoWrites) {
    PPU ppu;
    
    // First write (X scroll)
    ppu.write_register(0x2005, 0b11010101); // bits: HGFEDCBA
    
    // Second write (Y scroll)
    ppu.write_register(0x2005, 0b10110011);
    
    // w toggle should be reset
    // (Internal state can't be directly tested, but this verifies no crash)
}

// ========== PPUADDR ($2006) Tests ==========

TEST(PPU, PPUADDR_TwoWrites) {
    PPU ppu;
    
    // Write high byte
    ppu.write_register(0x2006, 0x23); // $23xx
    
    // Write low byte
    ppu.write_register(0x2006, 0xC0); // $23C0 (attribute table)
    
    // v should now be $23C0
    // Verify by reading from PPUDATA (which reads from v)
    // (Full test requires PPU memory implementation)
}

TEST(PPU, PPUADDR_Masking) {
    PPU ppu;
    
    // Write high byte with invalid bits set
    ppu.write_register(0x2006, 0xFF); // Only lower 6 bits should be used
    ppu.write_register(0x2006, 0xFF);
    
    // v should be $3FFF (not $FFFF)
    // (Can't directly test, but this verifies no invalid memory access)
}

// ========== PPUDATA ($2007) Tests ==========

TEST(PPU, PPUDATA_VRAMWrite) {
    PPU ppu;
    ppu.set_mirroring(PPU::Mirroring::HORIZONTAL);
    
    // Write to nametable
    ppu.write_register(0x2006, 0x20); // $2000
    ppu.write_register(0x2006, 0x00);
    
    ppu.write_register(0x2007, 0x42);
    
    // Read back
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    
    ppu.read_register(0x2007); // Dummy read (fills buffer)
    uint8_t value = ppu.read_register(0x2007); // Actual read
    EXPECT_EQ(0x42, value);
}

TEST(PPU, PPUDATA_PaletteWrite) {
    PPU ppu;
    
    // Write to palette
    ppu.write_register(0x2006, 0x3F); // $3F00
    ppu.write_register(0x2006, 0x00);
    
    ppu.write_register(0x2007, 0x0F); // White color
    
    // Read back (palette reads are not buffered)
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    
    uint8_t value = ppu.read_register(0x2007);
    EXPECT_EQ(0x0F, value);
}

TEST(PPU, PPUDATA_AutoIncrement_Across) {
    PPU ppu;
    ppu.set_mirroring(PPU::Mirroring::HORIZONTAL);
    
    // PPUCTRL bit 2 = 0 -> increment by 1 (across)
    ppu.write_register(0x2000, 0x00);
    
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    
    ppu.write_register(0x2007, 0x11);
    ppu.write_register(0x2007, 0x22);
    ppu.write_register(0x2007, 0x33);
    
    // Read back
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0x11, ppu.read_register(0x2007));
    EXPECT_EQ(0x22, ppu.read_register(0x2007));
    EXPECT_EQ(0x33, ppu.read_register(0x2007));
}

TEST(PPU, PPUDATA_AutoIncrement_Down) {
    PPU ppu;
    ppu.set_mirroring(PPU::Mirroring::HORIZONTAL);
    
    // PPUCTRL bit 2 = 1 -> increment by 32 (down)
    ppu.write_register(0x2000, 0x04);
    
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    
    ppu.write_register(0x2007, 0xAA);
    ppu.write_register(0x2007, 0xBB);
    
    // Addresses should be $2000, $2020
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x20); // $2020
    
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0xBB, ppu.read_register(0x2007));
}

// ========== OAM DMA Tests ==========

TEST(PPU, OAMDMA_Transfer) {
    PPU ppu;
    
    // Prepare 256 bytes of test data
    uint8_t test_data[0x10000];
    for (int i = 0; i < 256; i++) {
        test_data[0x0200 + i] = i;
    }
    
    // Set OAM address to 0
    ppu.write_register(0x2003, 0x00);
    
    // Perform DMA from CPU page $02
    ppu.oam_dma(test_data, 0x02);
    
    // Verify data was copied - need to set address before each read
    for (int i = 0; i < 256; i++) {
        ppu.write_register(0x2003, i);
        EXPECT_EQ(i, ppu.read_register(0x2004)) << "Failed at OAM index " << i;
    }
}

// ========== Mirroring Tests ==========

TEST(PPU, Mirroring_Horizontal) {
    PPU ppu;
    ppu.set_mirroring(PPU::Mirroring::HORIZONTAL);
    
    // Write to $2000
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x42);
    
    // $2400 should mirror to $2000
    ppu.write_register(0x2006, 0x24);
    ppu.write_register(0x2006, 0x00);
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0x42, ppu.read_register(0x2007));
    
    // $2800 should be different
    ppu.write_register(0x2006, 0x28);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x99);
    
    // $2C00 should mirror to $2800
    ppu.write_register(0x2006, 0x2C);
    ppu.write_register(0x2006, 0x00);
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0x99, ppu.read_register(0x2007));
}

TEST(PPU, Mirroring_Vertical) {
    PPU ppu;
    ppu.set_mirroring(PPU::Mirroring::VERTICAL);
    
    // Write to $2000
    ppu.write_register(0x2006, 0x20);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x42);
    
    // $2800 should mirror to $2000
    ppu.write_register(0x2006, 0x28);
    ppu.write_register(0x2006, 0x00);
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0x42, ppu.read_register(0x2007));
    
    // $2400 should be different
    ppu.write_register(0x2006, 0x24);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x99);
    
    // $2C00 should mirror to $2400
    ppu.write_register(0x2006, 0x2C);
    ppu.write_register(0x2006, 0x00);
    ppu.read_register(0x2007); // Dummy
    EXPECT_EQ(0x99, ppu.read_register(0x2007));
}

// ========== Palette Mirroring Tests ==========

TEST(PPU, PaletteMirroring_BackgroundToSprite) {
    PPU ppu;
    
    // Write to $3F00 (background palette 0, color 0)
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x00);
    ppu.write_register(0x2007, 0x0D); // Black
    
    // $3F10 (sprite palette 0, color 0) should mirror to $3F00
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x10);
    EXPECT_EQ(0x0D, ppu.read_register(0x2007));
    
    // Similarly for other transparent colors
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x04);
    ppu.write_register(0x2007, 0x15);
    
    ppu.write_register(0x2006, 0x3F);
    ppu.write_register(0x2006, 0x14);
    EXPECT_EQ(0x15, ppu.read_register(0x2007));
}

// ========== VBlank NMI Tests ==========

TEST(PPU, VBlank_NMI_Enabled) {
    PPU ppu;
    
    // Enable NMI in PPUCTRL
    ppu.write_register(0x2000, 0x80);
    
    // Run to scanline 241, cycle 1 (VBlank starts)
    for (int i = 0; i < 241 * 341 + 1; i++) {
        ppu.tick();
    }
    
    // NMI should be triggered
    EXPECT_TRUE(ppu.nmi_triggered());
    
    // Clear NMI flag
    ppu.clear_nmi();
    EXPECT_FALSE(ppu.nmi_triggered());
}

TEST(PPU, VBlank_NMI_Disabled) {
    PPU ppu;
    
    // NMI disabled (PPUCTRL bit 7 = 0)
    ppu.write_register(0x2000, 0x00);
    
    // Run to VBlank
    for (int i = 0; i < 241 * 341 + 1; i++) {
        ppu.tick();
    }
    
    // NMI should NOT be triggered
    EXPECT_FALSE(ppu.nmi_triggered());
}

// ========== Frame Completion Tests ==========

TEST(PPU, FrameCompletion) {
    PPU ppu;
    
    EXPECT_FALSE(ppu.is_frame_ready());
    
    // Run one full frame (261 scanlines × 341 cycles)
    for (int i = 0; i < 261 * 341; i++) {
        ppu.tick();
    }
    
    // Frame should be ready
    EXPECT_TRUE(ppu.is_frame_ready());
    
    // Clear flag
    ppu.clear_frame_ready();
    EXPECT_FALSE(ppu.is_frame_ready());
}
