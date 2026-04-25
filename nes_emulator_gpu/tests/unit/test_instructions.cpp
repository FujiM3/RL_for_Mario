#include <gtest/gtest.h>
#include "../../src/reference/cpu/cpu_6502.h"
#include "../../src/reference/cpu/instructions.h"
#include "../../src/reference/common/types.h"
#include <vector>

// Mock memory for testing
class MockMemory {
public:
    std::vector<uint8_t> data;
    
    MockMemory() : data(0x10000, 0) {}  // 64KB zero-filled
    
    uint8_t read(uint16_t addr) {
        return data[addr];
    }
    
    void write(uint16_t addr, uint8_t value) {
        data[addr] = value;
    }
};

// === Load Instructions ===

TEST(InstructionTest, LDA_Immediate) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    mem.data[0x8000] = 0xA9;  // LDA #$42
    mem.data[0x8001] = 0x42;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().A, 0x42);
    EXPECT_FALSE(cpu.get_registers().get_zero());
    EXPECT_FALSE(cpu.get_registers().get_negative());
}

TEST(InstructionTest, LDA_ZeroFlag) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    mem.data[0x8000] = 0xA9;  // LDA #$00
    mem.data[0x8001] = 0x00;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().A, 0x00);
    EXPECT_TRUE(cpu.get_registers().get_zero());
}

// === Store Instructions ===

TEST(InstructionTest, STA_ZeroPage) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().A = 0x42;
    mem.data[0x8000] = 0x85;  // STA $10
    mem.data[0x8001] = 0x10;
    
    cpu.step();
    
    EXPECT_EQ(mem.data[0x0010], 0x42);
}

// === Transfer Instructions ===

TEST(InstructionTest, TAX) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().A = 0x42;
    mem.data[0x8000] = 0xAA;  // TAX
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().X, 0x42);
}

// === Arithmetic Instructions ===

TEST(InstructionTest, ADC_Simple) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().A = 0x10;
    cpu.get_registers().set_carry(false);
    mem.data[0x8000] = 0x69;  // ADC #$20
    mem.data[0x8001] = 0x20;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().A, 0x30);
    EXPECT_FALSE(cpu.get_registers().get_carry());
}

TEST(InstructionTest, ADC_Carry) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().A = 0xFF;
    cpu.get_registers().set_carry(false);
    mem.data[0x8000] = 0x69;  // ADC #$01
    mem.data[0x8001] = 0x01;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().A, 0x00);
    EXPECT_TRUE(cpu.get_registers().get_carry());
    EXPECT_TRUE(cpu.get_registers().get_zero());
}

// === Logical Instructions ===

TEST(InstructionTest, AND_Immediate) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().A = 0xFF;
    mem.data[0x8000] = 0x29;  // AND #$0F
    mem.data[0x8001] = 0x0F;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().A, 0x0F);
}

// === Branch Instructions ===

TEST(InstructionTest, BEQ_Taken) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().set_zero(true);
    mem.data[0x8000] = 0xF0;  // BEQ +$05
    mem.data[0x8001] = 0x05;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, 0x8007);  // $8000 + 2 + $05
}

// === Jump Instructions ===

TEST(InstructionTest, JMP_Absolute) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    mem.data[0x8000] = 0x4C;  // JMP $1234
    mem.data[0x8001] = 0x34;
    mem.data[0x8002] = 0x12;
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, 0x1234);
}

// === Flag Instructions ===

TEST(InstructionTest, SEC_CLC) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    cpu.get_registers().set_carry(false);
    mem.data[0x8000] = 0x38;  // SEC
    cpu.step();
    EXPECT_TRUE(cpu.get_registers().get_carry());
    
    mem.data[0x8001] = 0x18;  // CLC
    cpu.step();
    EXPECT_FALSE(cpu.get_registers().get_carry());
}

// === Special Instructions ===

TEST(InstructionTest, NOP) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](uint16_t addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](uint16_t addr, uint8_t val) { mem.write(addr, val); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    auto pc_before = cpu.get_registers().PC;
    mem.data[0x8000] = 0xEA;  // NOP
    
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, pc_before + 1);
}
