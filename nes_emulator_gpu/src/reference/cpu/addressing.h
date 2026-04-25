#ifndef NES_ADDRESSING_H
#define NES_ADDRESSING_H

#include "common/types.h"

// Forward declaration
class CPU6502;

// Addressing mode result
struct AddressingResult {
    u16 address;       // Effective address for memory operations
    u8  value;         // Value read (for Immediate mode)
    bool page_crossed; // True if page boundary was crossed
    bool is_immediate; // True if Immediate addressing mode
    
    AddressingResult() 
        : address(0)
        , value(0)
        , page_crossed(false)
        , is_immediate(false)
    {}
};

// Addressing mode implementations
class Addressing {
public:
    // === Addressing Mode Functions ===
    
    // Implied: No operand (e.g., CLC, NOP)
    static AddressingResult implied(CPU6502& cpu);
    
    // Accumulator: Operate on accumulator (e.g., ASL A)
    static AddressingResult accumulator(CPU6502& cpu);
    
    // Immediate: #$nn
    static AddressingResult immediate(CPU6502& cpu);
    
    // Zero Page: $nn (address in first 256 bytes)
    static AddressingResult zero_page(CPU6502& cpu);
    
    // Zero Page, X: $nn,X
    static AddressingResult zero_page_x(CPU6502& cpu);
    
    // Zero Page, Y: $nn,Y
    static AddressingResult zero_page_y(CPU6502& cpu);
    
    // Absolute: $nnnn
    static AddressingResult absolute(CPU6502& cpu);
    
    // Absolute, X: $nnnn,X
    static AddressingResult absolute_x(CPU6502& cpu);
    
    // Absolute, Y: $nnnn,Y
    static AddressingResult absolute_y(CPU6502& cpu);
    
    // Relative: Branch offset (signed byte)
    static AddressingResult relative(CPU6502& cpu);
    
    // Indirect: ($nnnn) - JMP only
    static AddressingResult indirect(CPU6502& cpu);
    
    // Indexed Indirect: ($nn,X)
    static AddressingResult indexed_indirect(CPU6502& cpu);
    
    // Indirect Indexed: ($nn),Y
    static AddressingResult indirect_indexed(CPU6502& cpu);
    
private:
    // Helper: Check if page boundary crossed
    static inline bool page_crossed(u16 addr1, u16 addr2) {
        return (addr1 & 0xFF00) != (addr2 & 0xFF00);
    }
};

#endif // NES_ADDRESSING_H
