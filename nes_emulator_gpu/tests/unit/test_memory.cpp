#include <gtest/gtest.h>
#include "../../src/reference/common/memory.h"
#include "../../src/reference/common/mapper0.h"

// Test fixture for memory tests
class MemoryTest : public ::testing::Test {
protected:
    NESMemory memory;
    
    void SetUp() override {
        memory.reset();
    }
};

// Test RAM basic read/write
TEST_F(MemoryTest, RAMBasicReadWrite) {
    memory.write(0x0000, 0x42);
    EXPECT_EQ(memory.read(0x0000), 0x42);
    
    memory.write(0x07FF, 0xAB);
    EXPECT_EQ(memory.read(0x07FF), 0xAB);
}

// Test RAM mirroring at $0800-$1FFF
TEST_F(MemoryTest, RAMMirroring) {
    // Write to $0000, read from mirrors
    memory.write(0x0000, 0x12);
    EXPECT_EQ(memory.read(0x0800), 0x12);
    EXPECT_EQ(memory.read(0x1000), 0x12);
    EXPECT_EQ(memory.read(0x1800), 0x12);
    
    // Write to mirror, read from base
    memory.write(0x0855, 0x34);
    EXPECT_EQ(memory.read(0x0055), 0x34);
    EXPECT_EQ(memory.read(0x1055), 0x34);
    EXPECT_EQ(memory.read(0x1855), 0x34);
}

// Test SRAM read/write
TEST_F(MemoryTest, SRAMReadWrite) {
    memory.write(0x6000, 0xDE);
    EXPECT_EQ(memory.read(0x6000), 0xDE);
    
    memory.write(0x7FFF, 0xAD);
    EXPECT_EQ(memory.read(0x7FFF), 0xAD);
    
    memory.write(0x6ABC, 0xBE);
    EXPECT_EQ(memory.read(0x6ABC), 0xBE);
}

// Test PPU register callback
TEST_F(MemoryTest, PPURegisterCallback) {
    uint16_t last_read_addr = 0;
    uint16_t last_write_addr = 0;
    uint8_t last_write_value = 0;
    
    memory.set_ppu_read_callback([&](uint16_t addr) {
        last_read_addr = addr;
        return 0x99;
    });
    
    memory.set_ppu_write_callback([&](uint16_t addr, uint8_t value) {
        last_write_addr = addr;
        last_write_value = value;
    });
    
    // Read from PPU register
    uint8_t val = memory.read(0x2002);
    EXPECT_EQ(val, 0x99);
    EXPECT_EQ(last_read_addr, 0x2002);
    
    // Write to PPU register
    memory.write(0x2007, 0x55);
    EXPECT_EQ(last_write_addr, 0x2007);
    EXPECT_EQ(last_write_value, 0x55);
}

// Test PPU register mirroring ($2008-$3FFF)
TEST_F(MemoryTest, PPURegisterMirroring) {
    uint16_t last_addr = 0;
    
    memory.set_ppu_read_callback([&](uint16_t addr) {
        last_addr = addr;
        return 0;
    });
    
    // $2008 should mirror to $2000
    memory.read(0x2008);
    EXPECT_EQ(last_addr, 0x2000);
    
    // $2FFF should mirror to $2007
    memory.read(0x2FFF);
    EXPECT_EQ(last_addr, 0x2007);
    
    // $3ABC should mirror to $2004
    memory.read(0x3ABC);
    EXPECT_EQ(last_addr, 0x2004);
}

// Test APU/IO register callback
TEST_F(MemoryTest, APURegisterCallback) {
    uint16_t last_read_addr = 0;
    uint16_t last_write_addr = 0;
    
    memory.set_apu_read_callback([&](uint16_t addr) {
        last_read_addr = addr;
        return 0x77;
    });
    
    memory.set_apu_write_callback([&](uint16_t addr, uint8_t value) {
        last_write_addr = addr;
    });
    
    uint8_t val = memory.read(0x4015);
    EXPECT_EQ(val, 0x77);
    EXPECT_EQ(last_read_addr, 0x4015);
    
    memory.write(0x4000, 0x88);
    EXPECT_EQ(last_write_addr, 0x4000);
}

// Test PRG ROM callback
TEST_F(MemoryTest, PRGROMCallback) {
    memory.set_prg_read_callback([](uint16_t addr) {
        return static_cast<uint8_t>(addr & 0xFF);
    });
    
    EXPECT_EQ(memory.read(0x8000), 0x00);
    EXPECT_EQ(memory.read(0x8123), 0x23);
    EXPECT_EQ(memory.read(0xFFFF), 0xFF);
}

// Test fixture for Mapper 0
class Mapper0Test : public ::testing::Test {
protected:
    std::vector<uint8_t> prg_16kb;
    std::vector<uint8_t> prg_32kb;
    std::vector<uint8_t> chr_8kb;
    
    void SetUp() override {
        // Create 16KB PRG ROM
        prg_16kb.resize(16 * 1024);
        for (size_t i = 0; i < prg_16kb.size(); i++) {
            prg_16kb[i] = i & 0xFF;
        }
        
        // Create 32KB PRG ROM
        prg_32kb.resize(32 * 1024);
        for (size_t i = 0; i < prg_32kb.size(); i++) {
            prg_32kb[i] = (i >> 8) & 0xFF;
        }
        
        // Create 8KB CHR ROM
        chr_8kb.resize(8 * 1024);
        for (size_t i = 0; i < chr_8kb.size(); i++) {
            chr_8kb[i] = (i ^ 0xAA) & 0xFF;
        }
    }
};

// Test 16KB PRG mirroring
TEST_F(Mapper0Test, PRG16KBMirroring) {
    Mapper0 mapper(prg_16kb, chr_8kb);
    
    // $8000 and $C000 should read the same value (mirrored)
    EXPECT_EQ(mapper.read_prg(0x8000), mapper.read_prg(0xC000));
    EXPECT_EQ(mapper.read_prg(0x8123), mapper.read_prg(0xC123));
    EXPECT_EQ(mapper.read_prg(0xBFFF), mapper.read_prg(0xFFFF));
    
    // Verify actual values
    EXPECT_EQ(mapper.read_prg(0x8000), 0x00);
    EXPECT_EQ(mapper.read_prg(0x8100), 0x00);
    EXPECT_EQ(mapper.read_prg(0x8101), 0x01);
}

// Test 32KB PRG continuous mapping
TEST_F(Mapper0Test, PRG32KBContinuous) {
    Mapper0 mapper(prg_32kb, chr_8kb);
    
    // Verify continuous mapping (no mirroring)
    EXPECT_NE(mapper.read_prg(0x8000), mapper.read_prg(0xC000));
    
    // Check specific values
    EXPECT_EQ(mapper.read_prg(0x8000), 0x00);
    EXPECT_EQ(mapper.read_prg(0x8100), 0x01);
    EXPECT_EQ(mapper.read_prg(0xC000), 0x40);  // Offset 0x4000
    EXPECT_EQ(mapper.read_prg(0xFFFF), 0x7F);  // Last byte
}

// Test CHR ROM read
TEST_F(Mapper0Test, CHRROMRead) {
    Mapper0 mapper(prg_16kb, chr_8kb);
    
    EXPECT_EQ(mapper.read_chr(0x0000), 0xAA);
    EXPECT_EQ(mapper.read_chr(0x0001), 0xAB);
    EXPECT_EQ(mapper.read_chr(0x1FFF), (0x1FFF ^ 0xAA) & 0xFF);
}

// Test CHR RAM (when no CHR ROM provided)
TEST_F(Mapper0Test, CHRRAMWriteRead) {
    std::vector<uint8_t> empty_chr;
    Mapper0 mapper(prg_16kb, empty_chr);
    
    EXPECT_TRUE(mapper.has_chr_ram());
    
    // Should be able to write and read back
    mapper.write_chr(0x0000, 0x42);
    EXPECT_EQ(mapper.read_chr(0x0000), 0x42);
    
    mapper.write_chr(0x1FFF, 0xBE);
    EXPECT_EQ(mapper.read_chr(0x1FFF), 0xBE);
}

// Test that CHR ROM is read-only
TEST_F(Mapper0Test, CHRROMReadOnly) {
    Mapper0 mapper(prg_16kb, chr_8kb);
    
    EXPECT_FALSE(mapper.has_chr_ram());
    
    uint8_t original = mapper.read_chr(0x0100);
    mapper.write_chr(0x0100, 0xFF);
    
    // Value should not change (ROM is read-only)
    EXPECT_EQ(mapper.read_chr(0x0100), original);
}

// Test mapper info queries
TEST_F(Mapper0Test, MapperInfo) {
    Mapper0 mapper_16kb(prg_16kb, chr_8kb);
    EXPECT_EQ(mapper_16kb.get_prg_size(), 16 * 1024);
    EXPECT_FALSE(mapper_16kb.is_32kb_prg());
    
    Mapper0 mapper_32kb(prg_32kb, chr_8kb);
    EXPECT_EQ(mapper_32kb.get_prg_size(), 32 * 1024);
    EXPECT_TRUE(mapper_32kb.is_32kb_prg());
    
    EXPECT_EQ(mapper_16kb.get_chr_size(), 8 * 1024);
}
