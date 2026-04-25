#include "cpu/instructions.h"
#include "cpu/cpu_6502.h"
#include "cpu/addressing.h"

// ============================================================================
// Load/Store Instructions
// ============================================================================

// LDA - Load Accumulator
// A = M
// Flags: N, Z
void Instructions::LDA(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().A = value;
    cpu.get_registers().update_zn(value);
}

// LDX - Load X Register
// X = M
// Flags: N, Z
void Instructions::LDX(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().X = value;
    cpu.get_registers().update_zn(value);
}

// LDY - Load Y Register
// Y = M
// Flags: N, Z
void Instructions::LDY(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().Y = value;
    cpu.get_registers().update_zn(value);
}

// STA - Store Accumulator
// M = A
void Instructions::STA(CPU6502& cpu, const AddressingResult& addr) {
    cpu.write(addr.address, cpu.get_registers().A);
}

// STX - Store X Register
// M = X
void Instructions::STX(CPU6502& cpu, const AddressingResult& addr) {
    cpu.write(addr.address, cpu.get_registers().X);
}

// STY - Store Y Register
// M = Y
void Instructions::STY(CPU6502& cpu, const AddressingResult& addr) {
    cpu.write(addr.address, cpu.get_registers().Y);
}

// ============================================================================
// Transfer Instructions
// ============================================================================

// TAX - Transfer A to X
// X = A
// Flags: N, Z
void Instructions::TAX(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().X = cpu.get_registers().A;
    cpu.get_registers().update_zn(cpu.get_registers().X);
}

// TAY - Transfer A to Y
// Y = A
// Flags: N, Z
void Instructions::TAY(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().Y = cpu.get_registers().A;
    cpu.get_registers().update_zn(cpu.get_registers().Y);
}

// TXA - Transfer X to A
// A = X
// Flags: N, Z
void Instructions::TXA(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().A = cpu.get_registers().X;
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// TYA - Transfer Y to A
// A = Y
// Flags: N, Z
void Instructions::TYA(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().A = cpu.get_registers().Y;
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// TSX - Transfer SP to X
// X = SP
// Flags: N, Z
void Instructions::TSX(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().X = cpu.get_registers().SP;
    cpu.get_registers().update_zn(cpu.get_registers().X);
}

// TXS - Transfer X to SP
// SP = X
void Instructions::TXS(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().SP = cpu.get_registers().X;
    // Note: TXS does NOT affect flags
}

// ============================================================================
// Stack Instructions
// ============================================================================

// PHA - Push Accumulator
// [SP--] = A
void Instructions::PHA(CPU6502& cpu, const AddressingResult& addr) {
    cpu.push_byte(cpu.get_registers().A);
}

// PHP - Push Processor Status
// [SP--] = P (with B flag set)
void Instructions::PHP(CPU6502& cpu, const AddressingResult& addr) {
    cpu.push_byte(cpu.get_registers().get_status_brk());
}

// PLA - Pull Accumulator
// A = [++SP]
// Flags: N, Z
void Instructions::PLA(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().A = cpu.pop_byte();
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// PLP - Pull Processor Status
// P = [++SP]
void Instructions::PLP(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_status(cpu.pop_byte());
}

// ============================================================================
// Logical Instructions
// ============================================================================

// AND - Logical AND
// A = A & M
// Flags: N, Z
void Instructions::AND(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().A &= value;
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// EOR - Exclusive OR
// A = A ^ M
// Flags: N, Z
void Instructions::EOR(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().A ^= value;
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// ORA - Logical OR
// A = A | M
// Flags: N, Z
void Instructions::ORA(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    cpu.get_registers().A |= value;
    cpu.get_registers().update_zn(cpu.get_registers().A);
}

// BIT - Bit Test
// Z = !(A & M)
// N = M[7], V = M[6]
void Instructions::BIT(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = cpu.read(addr.address);
    u8 result = cpu.get_registers().A & value;
    
    // Set Z flag based on result
    cpu.get_registers().set_flag(CPUFlag::Z, result == 0);
    // Set N flag from bit 7 of memory
    cpu.get_registers().set_flag(CPUFlag::N, (value & 0x80) != 0);
    // Set V flag from bit 6 of memory
    cpu.get_registers().set_flag(CPUFlag::V, (value & 0x40) != 0);
}

// ============================================================================
// Arithmetic Instructions
// ============================================================================

// ADC - Add with Carry
// A = A + M + C
// Flags: N, V, Z, C
void Instructions::ADC(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    u8 a = cpu.get_registers().A;
    u8 carry = cpu.get_registers().get_flag(CPUFlag::C) ? 1 : 0;
    
    u16 sum = u16(a) + u16(value) + u16(carry);
    u8 result = sum & 0xFF;
    
    // Set flags
    cpu.get_registers().set_flag(CPUFlag::C, sum > 0xFF);
    cpu.get_registers().set_flag(CPUFlag::Z, result == 0);
    cpu.get_registers().set_flag(CPUFlag::N, (result & 0x80) != 0);
    
    // Overflow: (A and M have same sign) and (result has different sign)
    bool overflow = ((a ^ value) & 0x80) == 0 && ((a ^ result) & 0x80) != 0;
    cpu.get_registers().set_flag(CPUFlag::V, overflow);
    
    cpu.get_registers().A = result;
}

// SBC - Subtract with Carry
// A = A - M - (1 - C)
// Flags: N, V, Z, C
void Instructions::SBC(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    u8 a = cpu.get_registers().A;
    u8 carry = cpu.get_registers().get_flag(CPUFlag::C) ? 1 : 0;
    
    // SBC is equivalent to ADC with inverted operand
    u16 diff = u16(a) - u16(value) - u16(1 - carry);
    u8 result = diff & 0xFF;
    
    // Set flags
    cpu.get_registers().set_flag(CPUFlag::C, diff < 0x100);  // No borrow
    cpu.get_registers().set_flag(CPUFlag::Z, result == 0);
    cpu.get_registers().set_flag(CPUFlag::N, (result & 0x80) != 0);
    
    // Overflow: (A and M have different sign) and (A and result have different sign)
    bool overflow = ((a ^ value) & 0x80) != 0 && ((a ^ result) & 0x80) != 0;
    cpu.get_registers().set_flag(CPUFlag::V, overflow);
    
    cpu.get_registers().A = result;
}

// INC - Increment Memory
// M = M + 1
// Flags: N, Z
void Instructions::INC(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = cpu.read(addr.address);
    value++;
    cpu.write(addr.address, value);
    cpu.get_registers().update_zn(value);
}

// INX - Increment X
// X = X + 1
// Flags: N, Z
void Instructions::INX(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().X++;
    cpu.get_registers().update_zn(cpu.get_registers().X);
}

// INY - Increment Y
// Y = Y + 1
// Flags: N, Z
void Instructions::INY(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().Y++;
    cpu.get_registers().update_zn(cpu.get_registers().Y);
}

// DEC - Decrement Memory
// M = M - 1
// Flags: N, Z
void Instructions::DEC(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = cpu.read(addr.address);
    value--;
    cpu.write(addr.address, value);
    cpu.get_registers().update_zn(value);
}

// DEX - Decrement X
// X = X - 1
// Flags: N, Z
void Instructions::DEX(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().X--;
    cpu.get_registers().update_zn(cpu.get_registers().X);
}

// DEY - Decrement Y
// Y = Y - 1
// Flags: N, Z
void Instructions::DEY(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().Y--;
    cpu.get_registers().update_zn(cpu.get_registers().Y);
}

// ============================================================================
// Shift/Rotate Instructions
// ============================================================================

// ASL - Arithmetic Shift Left
// C <- [76543210] <- 0
// Flags: N, Z, C
void Instructions::ASL(CPU6502& cpu, const AddressingResult& addr) {
    u8 value;
    bool is_accumulator = false;
    
    // Check if this is accumulator mode (no address used)
    if (addr.address == 0 && !addr.is_immediate) {
        value = cpu.get_registers().A;
        is_accumulator = true;
    } else {
        value = cpu.read(addr.address);
    }
    
    cpu.get_registers().set_flag(CPUFlag::C, (value & 0x80) != 0);
    value <<= 1;
    cpu.get_registers().update_zn(value);
    
    if (is_accumulator) {
        cpu.get_registers().A = value;
    } else {
        cpu.write(addr.address, value);
    }
}

// LSR - Logical Shift Right
// 0 -> [76543210] -> C
// Flags: N(=0), Z, C
void Instructions::LSR(CPU6502& cpu, const AddressingResult& addr) {
    u8 value;
    bool is_accumulator = false;
    
    if (addr.address == 0 && !addr.is_immediate) {
        value = cpu.get_registers().A;
        is_accumulator = true;
    } else {
        value = cpu.read(addr.address);
    }
    
    cpu.get_registers().set_flag(CPUFlag::C, (value & 0x01) != 0);
    value >>= 1;
    cpu.get_registers().update_zn(value);
    
    if (is_accumulator) {
        cpu.get_registers().A = value;
    } else {
        cpu.write(addr.address, value);
    }
}

// ROL - Rotate Left
// C <- [76543210] <- C
// Flags: N, Z, C
void Instructions::ROL(CPU6502& cpu, const AddressingResult& addr) {
    u8 value;
    bool is_accumulator = false;
    
    if (addr.address == 0 && !addr.is_immediate) {
        value = cpu.get_registers().A;
        is_accumulator = true;
    } else {
        value = cpu.read(addr.address);
    }
    
    bool old_carry = cpu.get_registers().get_flag(CPUFlag::C);
    cpu.get_registers().set_flag(CPUFlag::C, (value & 0x80) != 0);
    value = (value << 1) | (old_carry ? 1 : 0);
    cpu.get_registers().update_zn(value);
    
    if (is_accumulator) {
        cpu.get_registers().A = value;
    } else {
        cpu.write(addr.address, value);
    }
}

// ROR - Rotate Right
// C -> [76543210] -> C
// Flags: N, Z, C
void Instructions::ROR(CPU6502& cpu, const AddressingResult& addr) {
    u8 value;
    bool is_accumulator = false;
    
    if (addr.address == 0 && !addr.is_immediate) {
        value = cpu.get_registers().A;
        is_accumulator = true;
    } else {
        value = cpu.read(addr.address);
    }
    
    bool old_carry = cpu.get_registers().get_flag(CPUFlag::C);
    cpu.get_registers().set_flag(CPUFlag::C, (value & 0x01) != 0);
    value = (value >> 1) | (old_carry ? 0x80 : 0);
    cpu.get_registers().update_zn(value);
    
    if (is_accumulator) {
        cpu.get_registers().A = value;
    } else {
        cpu.write(addr.address, value);
    }
}

// ============================================================================
// Compare Instructions
// ============================================================================

// CMP - Compare Accumulator
// Flags: N, Z, C
void Instructions::CMP(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    u8 a = cpu.get_registers().A;
    u8 result = a - value;
    
    cpu.get_registers().set_flag(CPUFlag::C, a >= value);
    cpu.get_registers().set_flag(CPUFlag::Z, a == value);
    cpu.get_registers().set_flag(CPUFlag::N, (result & 0x80) != 0);
}

// CPX - Compare X Register
// Flags: N, Z, C
void Instructions::CPX(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    u8 x = cpu.get_registers().X;
    u8 result = x - value;
    
    cpu.get_registers().set_flag(CPUFlag::C, x >= value);
    cpu.get_registers().set_flag(CPUFlag::Z, x == value);
    cpu.get_registers().set_flag(CPUFlag::N, (result & 0x80) != 0);
}

// CPY - Compare Y Register
// Flags: N, Z, C
void Instructions::CPY(CPU6502& cpu, const AddressingResult& addr) {
    u8 value = addr.is_immediate ? addr.value : cpu.read(addr.address);
    u8 y = cpu.get_registers().Y;
    u8 result = y - value;
    
    cpu.get_registers().set_flag(CPUFlag::C, y >= value);
    cpu.get_registers().set_flag(CPUFlag::Z, y == value);
    cpu.get_registers().set_flag(CPUFlag::N, (result & 0x80) != 0);
}

// ============================================================================
// Branch Instructions
// ============================================================================

// BCC - Branch if Carry Clear
void Instructions::BCC(CPU6502& cpu, const AddressingResult& addr) {
    if (!cpu.get_registers().get_flag(CPUFlag::C)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BCS - Branch if Carry Set
void Instructions::BCS(CPU6502& cpu, const AddressingResult& addr) {
    if (cpu.get_registers().get_flag(CPUFlag::C)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BEQ - Branch if Equal (Z=1)
void Instructions::BEQ(CPU6502& cpu, const AddressingResult& addr) {
    if (cpu.get_registers().get_flag(CPUFlag::Z)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BMI - Branch if Minus (N=1)
void Instructions::BMI(CPU6502& cpu, const AddressingResult& addr) {
    if (cpu.get_registers().get_flag(CPUFlag::N)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BNE - Branch if Not Equal (Z=0)
void Instructions::BNE(CPU6502& cpu, const AddressingResult& addr) {
    if (!cpu.get_registers().get_flag(CPUFlag::Z)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BPL - Branch if Plus (N=0)
void Instructions::BPL(CPU6502& cpu, const AddressingResult& addr) {
    if (!cpu.get_registers().get_flag(CPUFlag::N)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BVC - Branch if Overflow Clear (V=0)
void Instructions::BVC(CPU6502& cpu, const AddressingResult& addr) {
    if (!cpu.get_registers().get_flag(CPUFlag::V)) {
        cpu.get_registers().PC = addr.address;
    }
}

// BVS - Branch if Overflow Set (V=1)
void Instructions::BVS(CPU6502& cpu, const AddressingResult& addr) {
    if (cpu.get_registers().get_flag(CPUFlag::V)) {
        cpu.get_registers().PC = addr.address;
    }
}

// ============================================================================
// Jump/Subroutine Instructions
// ============================================================================

// JMP - Jump
void Instructions::JMP(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().PC = addr.address;
}

// JSR - Jump to Subroutine
void Instructions::JSR(CPU6502& cpu, const AddressingResult& addr) {
    // Push return address (PC - 1) to stack
    cpu.push_word_public(cpu.get_registers().PC - 1);
    cpu.get_registers().PC = addr.address;
}

// RTS - Return from Subroutine
void Instructions::RTS(CPU6502& cpu, const AddressingResult& addr) {
    // Pull return address and add 1
    cpu.get_registers().PC = cpu.pop_word_public() + 1;
}

// RTI - Return from Interrupt
void Instructions::RTI(CPU6502& cpu, const AddressingResult& addr) {
    // Pull processor status
    cpu.get_registers().set_status(cpu.pop_byte());
    // Pull program counter
    cpu.get_registers().PC = cpu.pop_word_public();
}

// ============================================================================
// Flag Instructions
// ============================================================================

// CLC - Clear Carry Flag
void Instructions::CLC(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::C, false);
}

// CLD - Clear Decimal Flag
void Instructions::CLD(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::D, false);
}

// CLI - Clear Interrupt Disable
void Instructions::CLI(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::I, false);
}

// CLV - Clear Overflow Flag
void Instructions::CLV(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::V, false);
}

// SEC - Set Carry Flag
void Instructions::SEC(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::C, true);
}

// SED - Set Decimal Flag
void Instructions::SED(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::D, true);
}

// SEI - Set Interrupt Disable
void Instructions::SEI(CPU6502& cpu, const AddressingResult& addr) {
    cpu.get_registers().set_flag(CPUFlag::I, true);
}

// ============================================================================
// Special Instructions
// ============================================================================

// BRK - Break
void Instructions::BRK(CPU6502& cpu, const AddressingResult& addr) {
    // BRK is handled in cpu_6502.cpp as it's part of interrupt system
    // This is just a placeholder
    cpu.trigger_brk();
}

// NOP - No Operation
void Instructions::NOP(CPU6502& cpu, const AddressingResult& addr) {
    // Do nothing
}

// ============================================================================
// Opcode Table (256 entries)
// ============================================================================

