#ifndef NES_CPU_REGISTERS_H
#define NES_CPU_REGISTERS_H

#include "common/types.h"

// 6502 CPU Registers
struct CPU6502Registers {
    u8  A;   // Accumulator
    u8  X;   // Index Register X
    u8  Y;   // Index Register Y
    u8  SP;  // Stack Pointer (points to $0100-$01FF)
    u16 PC;  // Program Counter
    u8  P;   // Processor Status (flags)
    
    // Initialize registers to power-up state
    CPU6502Registers() {
        reset();
    }
    
    // Reset to power-up state
    void reset() {
        A = 0x00;
        X = 0x00;
        Y = 0x00;
        SP = Memory::STACK_RESET;  // 0xFD
        PC = 0x0000;  // Will be loaded from RESET vector
        P = flag_mask(CPUFlag::U) | flag_mask(CPUFlag::I);  // U=1, I=1
    }
    
    // === Flag Getters ===
    
    inline bool get_flag(CPUFlag flag) const {
        return (P & flag_mask(flag)) != 0;
    }
    
    inline bool get_carry() const       { return get_flag(CPUFlag::C); }
    inline bool get_zero() const        { return get_flag(CPUFlag::Z); }
    inline bool get_interrupt() const   { return get_flag(CPUFlag::I); }
    inline bool get_decimal() const     { return get_flag(CPUFlag::D); }
    inline bool get_break() const       { return get_flag(CPUFlag::B); }
    inline bool get_overflow() const    { return get_flag(CPUFlag::V); }
    inline bool get_negative() const    { return get_flag(CPUFlag::N); }
    
    // === Flag Setters ===
    
    inline void set_flag(CPUFlag flag, bool value) {
        if (value) {
            P |= flag_mask(flag);
        } else {
            P &= ~flag_mask(flag);
        }
    }
    
    inline void set_carry(bool value)       { set_flag(CPUFlag::C, value); }
    inline void set_zero(bool value)        { set_flag(CPUFlag::Z, value); }
    inline void set_interrupt(bool value)   { set_flag(CPUFlag::I, value); }
    inline void set_decimal(bool value)     { set_flag(CPUFlag::D, value); }
    inline void set_break(bool value)       { set_flag(CPUFlag::B, value); }
    inline void set_overflow(bool value)    { set_flag(CPUFlag::V, value); }
    inline void set_negative(bool value)    { set_flag(CPUFlag::N, value); }
    
    // === Flag Updates (convenience functions) ===
    
    // Update Zero and Negative flags based on value
    inline void update_zn(u8 value) {
        set_zero(value == 0);
        set_negative((value & 0x80) != 0);  // Bit 7 is sign bit
    }
    
    // Clear a flag
    inline void clear_flag(CPUFlag flag) {
        set_flag(flag, false);
    }
    
    // === Stack Operations ===
    
    // Get current stack address ($0100 + SP)
    inline u16 stack_addr() const {
        return Memory::STACK_BASE + SP;
    }
    
    // Push to stack (decrements SP)
    inline void push_stack() {
        SP--;
    }
    
    // Pop from stack (increments SP)
    inline void pop_stack() {
        SP++;
    }
    
    // === Status Register Utilities ===
    
    // Get status register with specific B and U flag states
    // Used for BRK/PHP (B=1) vs IRQ/NMI (B=0)
    inline u8 get_status_brk() const {
        return P | flag_mask(CPUFlag::B) | flag_mask(CPUFlag::U);
    }
    
    inline u8 get_status_irq() const {
        return (P & ~flag_mask(CPUFlag::B)) | flag_mask(CPUFlag::U);
    }
    
    // Set status register (typically from stack during RTI)
    inline void set_status(u8 value) {
        P = value | flag_mask(CPUFlag::U);  // U flag always 1
    }
};

#endif // NES_CPU_REGISTERS_H
