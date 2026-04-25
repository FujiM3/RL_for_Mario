#include <gtest/gtest.h>
#include "cpu/registers.h"

// Test default initialization
TEST(RegistersTest, DefaultInitialization) {
    CPU6502Registers regs;
    
    // Check power-up state
    EXPECT_EQ(regs.A, 0x00);
    EXPECT_EQ(regs.X, 0x00);
    EXPECT_EQ(regs.Y, 0x00);
    EXPECT_EQ(regs.SP, 0xFD);
    EXPECT_EQ(regs.PC, 0x0000);
    
    // U and I flags should be set
    EXPECT_TRUE(regs.get_flag(CPUFlag::U));
    EXPECT_TRUE(regs.get_flag(CPUFlag::I));
}

// Test reset
TEST(RegistersTest, Reset) {
    CPU6502Registers regs;
    
    // Modify all registers
    regs.A = 0xFF;
    regs.X = 0xAA;
    regs.Y = 0x55;
    regs.SP = 0x00;
    regs.PC = 0x1234;
    regs.P = 0xFF;
    
    // Reset
    regs.reset();
    
    // Verify reset state
    EXPECT_EQ(regs.A, 0x00);
    EXPECT_EQ(regs.X, 0x00);
    EXPECT_EQ(regs.Y, 0x00);
    EXPECT_EQ(regs.SP, 0xFD);
    EXPECT_EQ(regs.PC, 0x0000);
}

// Test individual flag getters
TEST(RegistersTest, FlagGetters) {
    CPU6502Registers regs;
    
    regs.P = 0x00;
    EXPECT_FALSE(regs.get_carry());
    EXPECT_FALSE(regs.get_zero());
    EXPECT_FALSE(regs.get_negative());
    
    regs.P = 0xFF;
    EXPECT_TRUE(regs.get_carry());
    EXPECT_TRUE(regs.get_zero());
    EXPECT_TRUE(regs.get_interrupt());
    EXPECT_TRUE(regs.get_decimal());
    EXPECT_TRUE(regs.get_break());
    EXPECT_TRUE(regs.get_overflow());
    EXPECT_TRUE(regs.get_negative());
}

// Test individual flag setters
TEST(RegistersTest, FlagSetters) {
    CPU6502Registers regs;
    regs.P = 0x00;
    
    regs.set_carry(true);
    EXPECT_EQ(regs.P, 0x01);
    EXPECT_TRUE(regs.get_carry());
    
    regs.set_zero(true);
    EXPECT_EQ(regs.P, 0x03);
    EXPECT_TRUE(regs.get_zero());
    
    regs.set_negative(true);
    EXPECT_EQ(regs.P, 0x83);
    EXPECT_TRUE(regs.get_negative());
    
    // Clear a flag
    regs.set_carry(false);
    EXPECT_EQ(regs.P, 0x82);
    EXPECT_FALSE(regs.get_carry());
}

// Test generic flag getter/setter
TEST(RegistersTest, GenericFlagOperations) {
    CPU6502Registers regs;
    regs.P = 0x00;
    
    regs.set_flag(CPUFlag::V, true);
    EXPECT_TRUE(regs.get_flag(CPUFlag::V));
    EXPECT_EQ(regs.P, 0x40);
    
    regs.set_flag(CPUFlag::V, false);
    EXPECT_FALSE(regs.get_flag(CPUFlag::V));
    EXPECT_EQ(regs.P, 0x00);
}

// Test update_zn function
TEST(RegistersTest, UpdateZN) {
    CPU6502Registers regs;
    
    // Test zero
    regs.update_zn(0x00);
    EXPECT_TRUE(regs.get_zero());
    EXPECT_FALSE(regs.get_negative());
    
    // Test positive
    regs.update_zn(0x42);
    EXPECT_FALSE(regs.get_zero());
    EXPECT_FALSE(regs.get_negative());
    
    // Test negative (bit 7 set)
    regs.update_zn(0x80);
    EXPECT_FALSE(regs.get_zero());
    EXPECT_TRUE(regs.get_negative());
    
    // Test negative and non-zero
    regs.update_zn(0xFF);
    EXPECT_FALSE(regs.get_zero());
    EXPECT_TRUE(regs.get_negative());
}

// Test stack operations
TEST(RegistersTest, StackOperations) {
    CPU6502Registers regs;
    
    // Initial stack pointer
    EXPECT_EQ(regs.SP, 0xFD);
    EXPECT_EQ(regs.stack_addr(), 0x01FD);
    
    // Push
    regs.push_stack();
    EXPECT_EQ(regs.SP, 0xFC);
    EXPECT_EQ(regs.stack_addr(), 0x01FC);
    
    // Push multiple
    regs.push_stack();
    regs.push_stack();
    EXPECT_EQ(regs.SP, 0xFA);
    EXPECT_EQ(regs.stack_addr(), 0x01FA);
    
    // Pop
    regs.pop_stack();
    EXPECT_EQ(regs.SP, 0xFB);
    EXPECT_EQ(regs.stack_addr(), 0x01FB);
    
    // Stack wrap-around (edge case)
    regs.SP = 0xFF;
    regs.push_stack();
    EXPECT_EQ(regs.SP, 0xFE);
    
    regs.SP = 0x00;
    regs.pop_stack();
    EXPECT_EQ(regs.SP, 0x01);
}

// Test status register for BRK/PHP
TEST(RegistersTest, StatusRegisterBRK) {
    CPU6502Registers regs;
    regs.P = 0b01010101;  // Some arbitrary flags
    
    u8 status_brk = regs.get_status_brk();
    
    // B and U flags should be set
    EXPECT_TRUE(status_brk & flag_mask(CPUFlag::B));
    EXPECT_TRUE(status_brk & flag_mask(CPUFlag::U));
}

// Test status register for IRQ/NMI
TEST(RegistersTest, StatusRegisterIRQ) {
    CPU6502Registers regs;
    regs.P = 0xFF;  // All flags set
    
    u8 status_irq = regs.get_status_irq();
    
    // B flag should be clear, U should be set
    EXPECT_FALSE(status_irq & flag_mask(CPUFlag::B));
    EXPECT_TRUE(status_irq & flag_mask(CPUFlag::U));
}

// Test set_status
TEST(RegistersTest, SetStatus) {
    CPU6502Registers regs;
    
    regs.set_status(0b10101010);
    
    // U flag should always be 1
    EXPECT_TRUE(regs.get_flag(CPUFlag::U));
    
    // Other flags should match (except U is forced to 1)
    EXPECT_EQ(regs.P, 0b10101010 | flag_mask(CPUFlag::U));
}

// Test clear_flag
TEST(RegistersTest, ClearFlag) {
    CPU6502Registers regs;
    regs.P = 0xFF;
    
    regs.clear_flag(CPUFlag::C);
    EXPECT_FALSE(regs.get_carry());
    EXPECT_EQ(regs.P, 0xFE);
    
    regs.clear_flag(CPUFlag::Z);
    EXPECT_FALSE(regs.get_zero());
    EXPECT_EQ(regs.P, 0xFC);
}
