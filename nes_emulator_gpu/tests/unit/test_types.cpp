#include <gtest/gtest.h>
#include "common/types.h"

// Test basic type sizes
TEST(TypesTest, BasicTypeSizes) {
    EXPECT_EQ(sizeof(u8), 1);
    EXPECT_EQ(sizeof(u16), 2);
    EXPECT_EQ(sizeof(u32), 4);
    EXPECT_EQ(sizeof(s8), 1);
    EXPECT_EQ(sizeof(s16), 2);
}

// Test CPU flag masks
TEST(TypesTest, CPUFlagMasks) {
    EXPECT_EQ(flag_mask(CPUFlag::C), 0x01);  // Carry
    EXPECT_EQ(flag_mask(CPUFlag::Z), 0x02);  // Zero
    EXPECT_EQ(flag_mask(CPUFlag::I), 0x04);  // Interrupt Disable
    EXPECT_EQ(flag_mask(CPUFlag::D), 0x08);  // Decimal
    EXPECT_EQ(flag_mask(CPUFlag::B), 0x10);  // Break
    EXPECT_EQ(flag_mask(CPUFlag::U), 0x20);  // Unused
    EXPECT_EQ(flag_mask(CPUFlag::V), 0x40);  // Overflow
    EXPECT_EQ(flag_mask(CPUFlag::N), 0x80);  // Negative
}

// Test memory layout constants
TEST(TypesTest, MemoryLayout) {
    using namespace Memory;
    
    // RAM
    EXPECT_EQ(RAM_START, 0x0000);
    EXPECT_EQ(RAM_END, 0x07FF);
    EXPECT_EQ(RAM_SIZE, 0x0800);  // 2KB
    
    // PPU registers
    EXPECT_EQ(PPU_REG_START, 0x2000);
    EXPECT_EQ(PPU_REG_END, 0x2007);
    
    // Interrupt vectors
    EXPECT_EQ(NMI_VECTOR, 0xFFFA);
    EXPECT_EQ(RESET_VECTOR, 0xFFFC);
    EXPECT_EQ(IRQ_VECTOR, 0xFFFE);
    
    // Stack
    EXPECT_EQ(STACK_BASE, 0x0100);
    EXPECT_EQ(STACK_RESET, 0xFD);
}

// Test timing constants
TEST(TypesTest, TimingConstants) {
    using namespace Timing;
    
    EXPECT_EQ(CPU_FREQ_HZ, 1789773);
    EXPECT_NEAR(NTSC_FPS, 60.0988, 0.0001);
}

// Test addressing mode enum
TEST(TypesTest, AddressingModeEnum) {
    AddressingMode mode = AddressingMode::Immediate;
    EXPECT_EQ(mode, AddressingMode::Immediate);
    
    mode = AddressingMode::ZeroPage;
    EXPECT_NE(mode, AddressingMode::Absolute);
}

// Test opcode constants
TEST(TypesTest, OpcodeConstants) {
    using namespace Opcode;
    
    EXPECT_EQ(BRK_IMP, 0x00);
    EXPECT_EQ(NOP_IMP, 0xEA);
    EXPECT_EQ(LDA_IMM, 0xA9);
    EXPECT_EQ(JMP_ABS, 0x4C);
}
