#include <gtest/gtest.h>
#include "cpu/addressing.h"
#include "cpu/cpu_6502.h"
#include <vector>

// Mock memory for testing
class MockMemory {
public:
    std::vector<u8> data;
    
    MockMemory() : data(0x10000, 0) {}
    
    u8 read(u16 addr) {
        return data[addr];
    }
    
    void write(u16 addr, u8 value) {
        data[addr] = value;
    }
    
    u16 read_word(u16 addr) {
        return data[addr] | (u16(data[addr + 1]) << 8);
    }
    
    void write_word(u16 addr, u16 value) {
        data[addr] = value & 0xFF;
        data[addr + 1] = (value >> 8) & 0xFF;
    }
};

// Test fixture
class AddressingTest : public ::testing::Test {
protected:
    CPU6502 cpu;
    MockMemory mem;
    
    void SetUp() override {
        cpu.set_read_callback([this](u16 addr) { return mem.read(addr); });
        cpu.set_write_callback([this](u16 addr, u8 value) { mem.write(addr, value); });
        cpu.reset();
    }
};

// === Test Cases ===

TEST_F(AddressingTest, Implied) {
    auto result = Addressing::implied(cpu);
    EXPECT_EQ(result.address, 0);
    EXPECT_FALSE(result.is_immediate);
    EXPECT_FALSE(result.page_crossed);
}

TEST_F(AddressingTest, Accumulator) {
    auto result = Addressing::accumulator(cpu);
    EXPECT_EQ(result.address, 0);
    EXPECT_FALSE(result.is_immediate);
}

TEST_F(AddressingTest, Immediate) {
    cpu.get_registers().PC = 0x8000;
    mem.data[0x8000] = 0x42;
    
    auto result = Addressing::immediate(cpu);
    EXPECT_TRUE(result.is_immediate);
    EXPECT_EQ(result.value, 0x42);
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, ZeroPage) {
    cpu.get_registers().PC = 0x8000;
    mem.data[0x8000] = 0x42;
    
    auto result = Addressing::zero_page(cpu);
    EXPECT_EQ(result.address, 0x0042);
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, ZeroPageX) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x05;
    mem.data[0x8000] = 0x42;
    
    auto result = Addressing::zero_page_x(cpu);
    EXPECT_EQ(result.address, 0x0047);  // 0x42 + 0x05
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, ZeroPageXWrap) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x10;
    mem.data[0x8000] = 0xFF;
    
    auto result = Addressing::zero_page_x(cpu);
    EXPECT_EQ(result.address, 0x000F);  // Wraps: (0xFF + 0x10) & 0xFF
}

TEST_F(AddressingTest, ZeroPageY) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x03;
    mem.data[0x8000] = 0x40;
    
    auto result = Addressing::zero_page_y(cpu);
    EXPECT_EQ(result.address, 0x0043);  // 0x40 + 0x03
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, Absolute) {
    cpu.get_registers().PC = 0x8000;
    mem.write_word(0x8000, 0x1234);
    
    auto result = Addressing::absolute(cpu);
    EXPECT_EQ(result.address, 0x1234);
    EXPECT_EQ(cpu.get_registers().PC, 0x8002);
}

TEST_F(AddressingTest, AbsoluteX_NoPageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x05;
    mem.write_word(0x8000, 0x1234);
    
    auto result = Addressing::absolute_x(cpu);
    EXPECT_EQ(result.address, 0x1239);  // 0x1234 + 0x05
    EXPECT_FALSE(result.page_crossed);
    EXPECT_EQ(cpu.get_registers().PC, 0x8002);
}

TEST_F(AddressingTest, AbsoluteX_PageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x10;
    mem.write_word(0x8000, 0x12FF);
    
    auto result = Addressing::absolute_x(cpu);
    EXPECT_EQ(result.address, 0x130F);  // 0x12FF + 0x10 crosses page
    EXPECT_TRUE(result.page_crossed);
}

TEST_F(AddressingTest, AbsoluteY_NoPageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x05;
    mem.write_word(0x8000, 0x1234);
    
    auto result = Addressing::absolute_y(cpu);
    EXPECT_EQ(result.address, 0x1239);  // 0x1234 + 0x05
    EXPECT_FALSE(result.page_crossed);
}

TEST_F(AddressingTest, AbsoluteY_PageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x02;
    mem.write_word(0x8000, 0x12FE);
    
    auto result = Addressing::absolute_y(cpu);
    EXPECT_EQ(result.address, 0x1300);  // 0x12FE + 0x02 crosses page
    EXPECT_TRUE(result.page_crossed);
}

TEST_F(AddressingTest, Relative_Forward) {
    cpu.get_registers().PC = 0x8000;
    mem.data[0x8000] = 0x10;  // Forward +16
    
    auto result = Addressing::relative(cpu);
    EXPECT_EQ(result.address, 0x8011);  // 0x8001 + 0x10
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, Relative_Backward) {
    cpu.get_registers().PC = 0x8000;
    mem.data[0x8000] = 0xFE;  // Backward -2 (signed)
    
    auto result = Addressing::relative(cpu);
    EXPECT_EQ(result.address, 0x7FFF);  // 0x8001 + (-2)
}

TEST_F(AddressingTest, Relative_PageCross) {
    cpu.get_registers().PC = 0x80F0;
    mem.data[0x80F0] = 0x20;  // Forward +32
    
    auto result = Addressing::relative(cpu);
    EXPECT_EQ(result.address, 0x8111);  // 0x80F1 + 0x20 crosses page
    EXPECT_TRUE(result.page_crossed);
}

TEST_F(AddressingTest, Indirect_Normal) {
    cpu.get_registers().PC = 0x8000;
    mem.write_word(0x8000, 0x1234);  // Pointer address
    mem.write_word(0x1234, 0x5678);  // Target address
    
    auto result = Addressing::indirect(cpu);
    EXPECT_EQ(result.address, 0x5678);
    EXPECT_EQ(cpu.get_registers().PC, 0x8002);
}

TEST_F(AddressingTest, Indirect_PageBoundaryBug) {
    cpu.get_registers().PC = 0x8000;
    mem.write_word(0x8000, 0x12FF);  // Pointer at page boundary
    mem.data[0x12FF] = 0x78;         // Low byte
    mem.data[0x1200] = 0x56;         // High byte wraps to page start
    
    auto result = Addressing::indirect(cpu);
    EXPECT_EQ(result.address, 0x5678);  // Uses $1200, not $1300
}

TEST_F(AddressingTest, IndexedIndirect) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x04;
    mem.data[0x8000] = 0x20;         // Zero page base
    mem.write_word(0x0024, 0x1234);  // Pointer at $20 + $04 = $24
    
    auto result = Addressing::indexed_indirect(cpu);
    EXPECT_EQ(result.address, 0x1234);
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);
}

TEST_F(AddressingTest, IndexedIndirect_Wrap) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().X = 0x10;
    mem.data[0x8000] = 0xFF;         // Zero page base
    mem.data[0x000F] = 0x34;         // Wraps: (0xFF + 0x10) & 0xFF = 0x0F
    mem.data[0x0010] = 0x12;
    
    auto result = Addressing::indexed_indirect(cpu);
    EXPECT_EQ(result.address, 0x1234);
}

TEST_F(AddressingTest, IndirectIndexed_NoPageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x05;
    mem.data[0x8000] = 0x20;         // Zero page address
    mem.write_word(0x0020, 0x1234);  // Base address
    
    auto result = Addressing::indirect_indexed(cpu);
    EXPECT_EQ(result.address, 0x1239);  // 0x1234 + 0x05
    EXPECT_FALSE(result.page_crossed);
}

TEST_F(AddressingTest, IndirectIndexed_PageCross) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x10;
    mem.data[0x8000] = 0x20;         // Zero page address
    mem.write_word(0x0020, 0x12FF);  // Base address
    
    auto result = Addressing::indirect_indexed(cpu);
    EXPECT_EQ(result.address, 0x130F);  // 0x12FF + 0x10 crosses page
    EXPECT_TRUE(result.page_crossed);
}

TEST_F(AddressingTest, IndirectIndexed_ZeroPageWrap) {
    cpu.get_registers().PC = 0x8000;
    cpu.get_registers().Y = 0x05;
    mem.data[0x8000] = 0xFF;         // Zero page address
    mem.data[0x00FF] = 0x34;
    mem.data[0x0000] = 0x12;         // Wraps to $00
    
    auto result = Addressing::indirect_indexed(cpu);
    EXPECT_EQ(result.address, 0x1239);  // (0x1234) + 0x05
}
