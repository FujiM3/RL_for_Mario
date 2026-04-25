#include "cpu/instructions.h"

// Helper macro for defining opcodes
#define OP(mnem, mode, cyc, extra) { #mnem, AddressingMode::mode, cyc, extra, Instructions::mnem }
#define ILLEGAL { "???", AddressingMode::Implied, 2, false, Instructions::NOP }

// Complete 6502 Opcode Table (256 entries)
// Reference: http://www.obelisk.me.uk/6502/reference.html
const OpcodeInfo OPCODE_TABLE[256] = {
    // 0x00-0x0F
    OP(BRK, Implied, 7, false),         // 0x00 - BRK
    OP(ORA, IndexedIndirect, 6, false), // 0x01 - ORA ($nn,X)
    ILLEGAL,                            // 0x02
    ILLEGAL,                            // 0x03
    ILLEGAL,                            // 0x04
    OP(ORA, ZeroPage, 3, false),        // 0x05 - ORA $nn
    OP(ASL, ZeroPage, 5, false),        // 0x06 - ASL $nn
    ILLEGAL,                            // 0x07
    OP(PHP, Implied, 3, false),         // 0x08 - PHP
    OP(ORA, Immediate, 2, false),       // 0x09 - ORA #$nn
    OP(ASL, Accumulator, 2, false),     // 0x0A - ASL A
    ILLEGAL,                            // 0x0B
    ILLEGAL,                            // 0x0C
    OP(ORA, Absolute, 4, false),        // 0x0D - ORA $nnnn
    OP(ASL, Absolute, 6, false),        // 0x0E - ASL $nnnn
    ILLEGAL,                            // 0x0F
    
    // 0x10-0x1F
    OP(BPL, Relative, 2, true),         // 0x10 - BPL
    OP(ORA, IndirectIndexed, 5, true),  // 0x11 - ORA ($nn),Y
    ILLEGAL,                            // 0x12
    ILLEGAL,                            // 0x13
    ILLEGAL,                            // 0x14
    OP(ORA, ZeroPageX, 4, false),       // 0x15 - ORA $nn,X
    OP(ASL, ZeroPageX, 6, false),       // 0x16 - ASL $nn,X
    ILLEGAL,                            // 0x17
    OP(CLC, Implied, 2, false),         // 0x18 - CLC
    OP(ORA, AbsoluteY, 4, true),        // 0x19 - ORA $nnnn,Y
    ILLEGAL,                            // 0x1A
    ILLEGAL,                            // 0x1B
    ILLEGAL,                            // 0x1C
    OP(ORA, AbsoluteX, 4, true),        // 0x1D - ORA $nnnn,X
    OP(ASL, AbsoluteX, 7, false),       // 0x1E - ASL $nnnn,X
    ILLEGAL,                            // 0x1F
    
    // 0x20-0x2F
    OP(JSR, Absolute, 6, false),        // 0x20 - JSR
    OP(AND, IndexedIndirect, 6, false), // 0x21 - AND ($nn,X)
    ILLEGAL,                            // 0x22
    ILLEGAL,                            // 0x23
    OP(BIT, ZeroPage, 3, false),        // 0x24 - BIT $nn
    OP(AND, ZeroPage, 3, false),        // 0x25 - AND $nn
    OP(ROL, ZeroPage, 5, false),        // 0x26 - ROL $nn
    ILLEGAL,                            // 0x27
    OP(PLP, Implied, 4, false),         // 0x28 - PLP
    OP(AND, Immediate, 2, false),       // 0x29 - AND #$nn
    OP(ROL, Accumulator, 2, false),     // 0x2A - ROL A
    ILLEGAL,                            // 0x2B
    OP(BIT, Absolute, 4, false),        // 0x2C - BIT $nnnn
    OP(AND, Absolute, 4, false),        // 0x2D - AND $nnnn
    OP(ROL, Absolute, 6, false),        // 0x2E - ROL $nnnn
    ILLEGAL,                            // 0x2F
    
    // 0x30-0x3F
    OP(BMI, Relative, 2, true),         // 0x30 - BMI
    OP(AND, IndirectIndexed, 5, true),  // 0x31 - AND ($nn),Y
    ILLEGAL,                            // 0x32
    ILLEGAL,                            // 0x33
    ILLEGAL,                            // 0x34
    OP(AND, ZeroPageX, 4, false),       // 0x35 - AND $nn,X
    OP(ROL, ZeroPageX, 6, false),       // 0x36 - ROL $nn,X
    ILLEGAL,                            // 0x37
    OP(SEC, Implied, 2, false),         // 0x38 - SEC
    OP(AND, AbsoluteY, 4, true),        // 0x39 - AND $nnnn,Y
    ILLEGAL,                            // 0x3A
    ILLEGAL,                            // 0x3B
    ILLEGAL,                            // 0x3C
    OP(AND, AbsoluteX, 4, true),        // 0x3D - AND $nnnn,X
    OP(ROL, AbsoluteX, 7, false),       // 0x3E - ROL $nnnn,X
    ILLEGAL,                            // 0x3F
    
    // 0x40-0x4F
    OP(RTI, Implied, 6, false),         // 0x40 - RTI
    OP(EOR, IndexedIndirect, 6, false), // 0x41 - EOR ($nn,X)
    ILLEGAL,                            // 0x42
    ILLEGAL,                            // 0x43
    ILLEGAL,                            // 0x44
    OP(EOR, ZeroPage, 3, false),        // 0x45 - EOR $nn
    OP(LSR, ZeroPage, 5, false),        // 0x46 - LSR $nn
    ILLEGAL,                            // 0x47
    OP(PHA, Implied, 3, false),         // 0x48 - PHA
    OP(EOR, Immediate, 2, false),       // 0x49 - EOR #$nn
    OP(LSR, Accumulator, 2, false),     // 0x4A - LSR A
    ILLEGAL,                            // 0x4B
    OP(JMP, Absolute, 3, false),        // 0x4C - JMP $nnnn
    OP(EOR, Absolute, 4, false),        // 0x4D - EOR $nnnn
    OP(LSR, Absolute, 6, false),        // 0x4E - LSR $nnnn
    ILLEGAL,                            // 0x4F
    
    // 0x50-0x5F
    OP(BVC, Relative, 2, true),         // 0x50 - BVC
    OP(EOR, IndirectIndexed, 5, true),  // 0x51 - EOR ($nn),Y
    ILLEGAL,                            // 0x52
    ILLEGAL,                            // 0x53
    ILLEGAL,                            // 0x54
    OP(EOR, ZeroPageX, 4, false),       // 0x55 - EOR $nn,X
    OP(LSR, ZeroPageX, 6, false),       // 0x56 - LSR $nn,X
    ILLEGAL,                            // 0x57
    OP(CLI, Implied, 2, false),         // 0x58 - CLI
    OP(EOR, AbsoluteY, 4, true),        // 0x59 - EOR $nnnn,Y
    ILLEGAL,                            // 0x5A
    ILLEGAL,                            // 0x5B
    ILLEGAL,                            // 0x5C
    OP(EOR, AbsoluteX, 4, true),        // 0x5D - EOR $nnnn,X
    OP(LSR, AbsoluteX, 7, false),       // 0x5E - LSR $nnnn,X
    ILLEGAL,                            // 0x5F
    
    // 0x60-0x6F
    OP(RTS, Implied, 6, false),         // 0x60 - RTS
    OP(ADC, IndexedIndirect, 6, false), // 0x61 - ADC ($nn,X)
    ILLEGAL,                            // 0x62
    ILLEGAL,                            // 0x63
    ILLEGAL,                            // 0x64
    OP(ADC, ZeroPage, 3, false),        // 0x65 - ADC $nn
    OP(ROR, ZeroPage, 5, false),        // 0x66 - ROR $nn
    ILLEGAL,                            // 0x67
    OP(PLA, Implied, 4, false),         // 0x68 - PLA
    OP(ADC, Immediate, 2, false),       // 0x69 - ADC #$nn
    OP(ROR, Accumulator, 2, false),     // 0x6A - ROR A
    ILLEGAL,                            // 0x6B
    OP(JMP, Indirect, 5, false),        // 0x6C - JMP ($nnnn)
    OP(ADC, Absolute, 4, false),        // 0x6D - ADC $nnnn
    OP(ROR, Absolute, 6, false),        // 0x6E - ROR $nnnn
    ILLEGAL,                            // 0x6F
    
    // 0x70-0x7F
    OP(BVS, Relative, 2, true),         // 0x70 - BVS
    OP(ADC, IndirectIndexed, 5, true),  // 0x71 - ADC ($nn),Y
    ILLEGAL,                            // 0x72
    ILLEGAL,                            // 0x73
    ILLEGAL,                            // 0x74
    OP(ADC, ZeroPageX, 4, false),       // 0x75 - ADC $nn,X
    OP(ROR, ZeroPageX, 6, false),       // 0x76 - ROR $nn,X
    ILLEGAL,                            // 0x77
    OP(SEI, Implied, 2, false),         // 0x78 - SEI
    OP(ADC, AbsoluteY, 4, true),        // 0x79 - ADC $nnnn,Y
    ILLEGAL,                            // 0x7A
    ILLEGAL,                            // 0x7B
    ILLEGAL,                            // 0x7C
    OP(ADC, AbsoluteX, 4, true),        // 0x7D - ADC $nnnn,X
    OP(ROR, AbsoluteX, 7, false),       // 0x7E - ROR $nnnn,X
    ILLEGAL,                            // 0x7F
    
    // 0x80-0x8F
    ILLEGAL,                            // 0x80
    OP(STA, IndexedIndirect, 6, false), // 0x81 - STA ($nn,X)
    ILLEGAL,                            // 0x82
    ILLEGAL,                            // 0x83
    OP(STY, ZeroPage, 3, false),        // 0x84 - STY $nn
    OP(STA, ZeroPage, 3, false),        // 0x85 - STA $nn
    OP(STX, ZeroPage, 3, false),        // 0x86 - STX $nn
    ILLEGAL,                            // 0x87
    OP(DEY, Implied, 2, false),         // 0x88 - DEY
    ILLEGAL,                            // 0x89
    OP(TXA, Implied, 2, false),         // 0x8A - TXA
    ILLEGAL,                            // 0x8B
    OP(STY, Absolute, 4, false),        // 0x8C - STY $nnnn
    OP(STA, Absolute, 4, false),        // 0x8D - STA $nnnn
    OP(STX, Absolute, 4, false),        // 0x8E - STX $nnnn
    ILLEGAL,                            // 0x8F
    
    // 0x90-0x9F
    OP(BCC, Relative, 2, true),         // 0x90 - BCC
    OP(STA, IndirectIndexed, 6, false), // 0x91 - STA ($nn),Y
    ILLEGAL,                            // 0x92
    ILLEGAL,                            // 0x93
    OP(STY, ZeroPageX, 4, false),       // 0x94 - STY $nn,X
    OP(STA, ZeroPageX, 4, false),       // 0x95 - STA $nn,X
    OP(STX, ZeroPageY, 4, false),       // 0x96 - STX $nn,Y
    ILLEGAL,                            // 0x97
    OP(TYA, Implied, 2, false),         // 0x98 - TYA
    OP(STA, AbsoluteY, 5, false),       // 0x99 - STA $nnnn,Y
    OP(TXS, Implied, 2, false),         // 0x9A - TXS
    ILLEGAL,                            // 0x9B
    ILLEGAL,                            // 0x9C
    OP(STA, AbsoluteX, 5, false),       // 0x9D - STA $nnnn,X
    ILLEGAL,                            // 0x9E
    ILLEGAL,                            // 0x9F
    
    // 0xA0-0xAF
    OP(LDY, Immediate, 2, false),       // 0xA0 - LDY #$nn
    OP(LDA, IndexedIndirect, 6, false), // 0xA1 - LDA ($nn,X)
    OP(LDX, Immediate, 2, false),       // 0xA2 - LDX #$nn
    ILLEGAL,                            // 0xA3
    OP(LDY, ZeroPage, 3, false),        // 0xA4 - LDY $nn
    OP(LDA, ZeroPage, 3, false),        // 0xA5 - LDA $nn
    OP(LDX, ZeroPage, 3, false),        // 0xA6 - LDX $nn
    ILLEGAL,                            // 0xA7
    OP(TAY, Implied, 2, false),         // 0xA8 - TAY
    OP(LDA, Immediate, 2, false),       // 0xA9 - LDA #$nn
    OP(TAX, Implied, 2, false),         // 0xAA - TAX
    ILLEGAL,                            // 0xAB
    OP(LDY, Absolute, 4, false),        // 0xAC - LDY $nnnn
    OP(LDA, Absolute, 4, false),        // 0xAD - LDA $nnnn
    OP(LDX, Absolute, 4, false),        // 0xAE - LDX $nnnn
    ILLEGAL,                            // 0xAF
    
    // 0xB0-0xBF
    OP(BCS, Relative, 2, true),         // 0xB0 - BCS
    OP(LDA, IndirectIndexed, 5, true),  // 0xB1 - LDA ($nn),Y
    ILLEGAL,                            // 0xB2
    ILLEGAL,                            // 0xB3
    OP(LDY, ZeroPageX, 4, false),       // 0xB4 - LDY $nn,X
    OP(LDA, ZeroPageX, 4, false),       // 0xB5 - LDA $nn,X
    OP(LDX, ZeroPageY, 4, false),       // 0xB6 - LDX $nn,Y
    ILLEGAL,                            // 0xB7
    OP(CLV, Implied, 2, false),         // 0xB8 - CLV
    OP(LDA, AbsoluteY, 4, true),        // 0xB9 - LDA $nnnn,Y
    OP(TSX, Implied, 2, false),         // 0xBA - TSX
    ILLEGAL,                            // 0xBB
    OP(LDY, AbsoluteX, 4, true),        // 0xBC - LDY $nnnn,X
    OP(LDA, AbsoluteX, 4, true),        // 0xBD - LDA $nnnn,X
    OP(LDX, AbsoluteY, 4, true),        // 0xBE - LDX $nnnn,Y
    ILLEGAL,                            // 0xBF
    
    // 0xC0-0xCF
    OP(CPY, Immediate, 2, false),       // 0xC0 - CPY #$nn
    OP(CMP, IndexedIndirect, 6, false), // 0xC1 - CMP ($nn,X)
    ILLEGAL,                            // 0xC2
    ILLEGAL,                            // 0xC3
    OP(CPY, ZeroPage, 3, false),        // 0xC4 - CPY $nn
    OP(CMP, ZeroPage, 3, false),        // 0xC5 - CMP $nn
    OP(DEC, ZeroPage, 5, false),        // 0xC6 - DEC $nn
    ILLEGAL,                            // 0xC7
    OP(INY, Implied, 2, false),         // 0xC8 - INY
    OP(CMP, Immediate, 2, false),       // 0xC9 - CMP #$nn
    OP(DEX, Implied, 2, false),         // 0xCA - DEX
    ILLEGAL,                            // 0xCB
    OP(CPY, Absolute, 4, false),        // 0xCC - CPY $nnnn
    OP(CMP, Absolute, 4, false),        // 0xCD - CMP $nnnn
    OP(DEC, Absolute, 6, false),        // 0xCE - DEC $nnnn
    ILLEGAL,                            // 0xCF
    
    // 0xD0-0xDF
    OP(BNE, Relative, 2, true),         // 0xD0 - BNE
    OP(CMP, IndirectIndexed, 5, true),  // 0xD1 - CMP ($nn),Y
    ILLEGAL,                            // 0xD2
    ILLEGAL,                            // 0xD3
    ILLEGAL,                            // 0xD4
    OP(CMP, ZeroPageX, 4, false),       // 0xD5 - CMP $nn,X
    OP(DEC, ZeroPageX, 6, false),       // 0xD6 - DEC $nn,X
    ILLEGAL,                            // 0xD7
    OP(CLD, Implied, 2, false),         // 0xD8 - CLD
    OP(CMP, AbsoluteY, 4, true),        // 0xD9 - CMP $nnnn,Y
    ILLEGAL,                            // 0xDA
    ILLEGAL,                            // 0xDB
    ILLEGAL,                            // 0xDC
    OP(CMP, AbsoluteX, 4, true),        // 0xDD - CMP $nnnn,X
    OP(DEC, AbsoluteX, 7, false),       // 0xDE - DEC $nnnn,X
    ILLEGAL,                            // 0xDF
    
    // 0xE0-0xEF
    OP(CPX, Immediate, 2, false),       // 0xE0 - CPX #$nn
    OP(SBC, IndexedIndirect, 6, false), // 0xE1 - SBC ($nn,X)
    ILLEGAL,                            // 0xE2
    ILLEGAL,                            // 0xE3
    OP(CPX, ZeroPage, 3, false),        // 0xE4 - CPX $nn
    OP(SBC, ZeroPage, 3, false),        // 0xE5 - SBC $nn
    OP(INC, ZeroPage, 5, false),        // 0xE6 - INC $nn
    ILLEGAL,                            // 0xE7
    OP(INX, Implied, 2, false),         // 0xE8 - INX
    OP(SBC, Immediate, 2, false),       // 0xE9 - SBC #$nn
    OP(NOP, Implied, 2, false),         // 0xEA - NOP
    ILLEGAL,                            // 0xEB
    OP(CPX, Absolute, 4, false),        // 0xEC - CPX $nnnn
    OP(SBC, Absolute, 4, false),        // 0xED - SBC $nnnn
    OP(INC, Absolute, 6, false),        // 0xEE - INC $nnnn
    ILLEGAL,                            // 0xEF
    
    // 0xF0-0xFF
    OP(BEQ, Relative, 2, true),         // 0xF0 - BEQ
    OP(SBC, IndirectIndexed, 5, true),  // 0xF1 - SBC ($nn),Y
    ILLEGAL,                            // 0xF2
    ILLEGAL,                            // 0xF3
    ILLEGAL,                            // 0xF4
    OP(SBC, ZeroPageX, 4, false),       // 0xF5 - SBC $nn,X
    OP(INC, ZeroPageX, 6, false),       // 0xF6 - INC $nn,X
    ILLEGAL,                            // 0xF7
    OP(SED, Implied, 2, false),         // 0xF8 - SED
    OP(SBC, AbsoluteY, 4, true),        // 0xF9 - SBC $nnnn,Y
    ILLEGAL,                            // 0xFA
    ILLEGAL,                            // 0xFB
    ILLEGAL,                            // 0xFC
    OP(SBC, AbsoluteX, 4, true),        // 0xFD - SBC $nnnn,X
    OP(INC, AbsoluteX, 7, false),       // 0xFE - INC $nnnn,X
    ILLEGAL,                            // 0xFF
};

#undef OP
#undef ILLEGAL
