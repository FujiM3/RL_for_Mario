#include <gtest/gtest.h>
#include "cpu/cpu_6502.h"
#include <vector>

// Mock memory for testing
class MockMemory {
public:
    std::vector<u8> data;
    
    MockMemory() : data(0x10000, 0) {}  // 64KB zero-filled
    
    u8 read(u16 addr) {
        return data[addr];
    }
    
    void write(u16 addr, u8 value) {
        data[addr] = value;
    }
};

// Test CPU construction
TEST(CPU6502Test, Construction) {
    CPU6502 cpu;
    
    // CPU should be constructed successfully
    EXPECT_EQ(cpu.get_cycles(), 0);
}

// Test reset
TEST(CPU6502Test, Reset) {
    CPU6502 cpu;
    MockMemory mem;
    
    // Set up callbacks
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set RESET vector to $8000
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    
    // Reset CPU
    cpu.reset();
    
    // Check PC loaded from RESET vector
    EXPECT_EQ(cpu.get_registers().PC, 0x8000);
    
    // Check other registers
    EXPECT_EQ(cpu.get_registers().A, 0x00);
    EXPECT_EQ(cpu.get_registers().X, 0x00);
    EXPECT_EQ(cpu.get_registers().Y, 0x00);
    EXPECT_EQ(cpu.get_registers().SP, 0xFD);
}

// Test memory read/write callbacks
TEST(CPU6502Test, MemoryCallbacks) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Write
    cpu.write(0x1234, 0xAB);
    EXPECT_EQ(mem.data[0x1234], 0xAB);
    
    // Read
    mem.data[0x5678] = 0xCD;
    EXPECT_EQ(cpu.read(0x5678), 0xCD);
}

// Test read_word (little-endian)
TEST(CPU6502Test, ReadWord) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set up little-endian word
    mem.data[0x1000] = 0x34;  // Low byte
    mem.data[0x1001] = 0x12;  // High byte
    
    EXPECT_EQ(cpu.read_word(0x1000), 0x1234);
}

// Test stack push/pop
TEST(CPU6502Test, StackOperations) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Reset to initialize SP
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    // Get initial SP
    u8 initial_sp = cpu.get_registers().SP;
    
    // Push byte
    cpu.write(cpu.get_registers().stack_addr(), 0xAB);
    cpu.get_registers().push_stack();
    
    EXPECT_EQ(cpu.get_registers().SP, initial_sp - 1);
    EXPECT_EQ(mem.data[0x0100 + initial_sp], 0xAB);
    
    // Pop byte
    cpu.get_registers().pop_stack();
    u8 value = cpu.read(cpu.get_registers().stack_addr());
    
    EXPECT_EQ(cpu.get_registers().SP, initial_sp);
    EXPECT_EQ(value, 0xAB);
}

// Test NOP instruction
TEST(CPU6502Test, NOPInstruction) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set PC and NOP instruction
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    cpu.reset();
    
    // Place NOP at $8000
    mem.data[0x8000] = Opcode::NOP_IMP;
    
    // Execute one instruction
    u8 cycles = cpu.step();
    
    EXPECT_EQ(cycles, 2);  // NOP takes 2 cycles
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);  // PC should advance
    EXPECT_EQ(cpu.get_cycles(), 2);  // Total cycles
}

// Test BRK instruction
TEST(CPU6502Test, BRKInstruction) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set vectors
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    mem.data[Memory::IRQ_VECTOR] = 0x00;
    mem.data[Memory::IRQ_VECTOR + 1] = 0x90;  // IRQ handler at $9000
    
    cpu.reset();
    
    // Place BRK at $8000
    mem.data[0x8000] = Opcode::BRK_IMP;
    
    u8 initial_sp = cpu.get_registers().SP;
    
    // Execute BRK
    u8 cycles = cpu.step();
    
    EXPECT_EQ(cycles, 7);  // BRK takes 7 cycles
    EXPECT_EQ(cpu.get_registers().PC, 0x9000);  // PC loaded from IRQ vector
    EXPECT_TRUE(cpu.get_registers().get_interrupt());  // I flag set
    EXPECT_EQ(cpu.get_registers().SP, initial_sp - 3);  // 3 bytes pushed
}

// Test NMI
TEST(CPU6502Test, NMI) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set vectors
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    mem.data[Memory::NMI_VECTOR] = 0x00;
    mem.data[Memory::NMI_VECTOR + 1] = 0xA0;  // NMI handler at $A000
    
    cpu.reset();
    
    // Place NOP at both $8000 and $A000
    mem.data[0x8000] = Opcode::NOP_IMP;
    mem.data[0xA000] = Opcode::NOP_IMP;
    
    u8 initial_sp = cpu.get_registers().SP;
    
    // Trigger NMI
    cpu.trigger_nmi();
    
    // Execute (should handle NMI, then execute instruction at $A000)
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, 0xA001);  // PC at NMI handler, executed NOP
    EXPECT_TRUE(cpu.get_registers().get_interrupt());  // I flag set
    EXPECT_LT(cpu.get_registers().SP, initial_sp);  // Stack used for pushing PC and P
}

// Test IRQ (maskable)
TEST(CPU6502Test, IRQ) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    // Set vectors
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    mem.data[Memory::IRQ_VECTOR] = 0x00;
    mem.data[Memory::IRQ_VECTOR + 1] = 0xB0;  // IRQ handler at $B000
    
    cpu.reset();
    cpu.get_registers().set_interrupt(false);  // Clear I flag
    
    // Place NOP at both locations
    mem.data[0x8000] = Opcode::NOP_IMP;
    mem.data[0xB000] = Opcode::NOP_IMP;
    
    // Trigger IRQ
    cpu.trigger_irq();
    
    // Execute (should handle IRQ, then execute instruction at $B000)
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, 0xB001);  // PC at IRQ handler, executed NOP
    EXPECT_TRUE(cpu.get_registers().get_interrupt());  // I flag set
}

// Test IRQ masked
TEST(CPU6502Test, IRQMasked) {
    CPU6502 cpu;
    MockMemory mem;
    
    cpu.set_read_callback([&mem](u16 addr) { return mem.read(addr); });
    cpu.set_write_callback([&mem](u16 addr, u8 value) { mem.write(addr, value); });
    
    mem.data[Memory::RESET_VECTOR] = 0x00;
    mem.data[Memory::RESET_VECTOR + 1] = 0x80;
    
    cpu.reset();
    cpu.get_registers().set_interrupt(true);  // Set I flag (mask IRQ)
    
    mem.data[0x8000] = Opcode::NOP_IMP;
    
    // Trigger IRQ
    cpu.trigger_irq();
    
    // Execute (should NOT handle IRQ because I flag is set)
    cpu.step();
    
    EXPECT_EQ(cpu.get_registers().PC, 0x8001);  // PC just advanced past NOP
}
