#ifndef NES_INSTRUCTIONS_H
#define NES_INSTRUCTIONS_H

#include "common/types.h"

// Forward declaration
class CPU6502;
struct AddressingResult;

// Opcode table entry
struct OpcodeInfo {
    const char* mnemonic;      // Instruction name
    AddressingMode mode;       // Addressing mode
    u8 cycles;                 // Base cycle count
    bool extra_cycle_on_page;  // +1 cycle on page boundary cross
    
    // Instruction execution function pointer
    void (*execute)(CPU6502& cpu, const AddressingResult& addr_result);
};

// Instruction implementations
namespace Instructions {
    // === Load/Store Instructions ===
    void LDA(CPU6502& cpu, const AddressingResult& addr);
    void LDX(CPU6502& cpu, const AddressingResult& addr);
    void LDY(CPU6502& cpu, const AddressingResult& addr);
    void STA(CPU6502& cpu, const AddressingResult& addr);
    void STX(CPU6502& cpu, const AddressingResult& addr);
    void STY(CPU6502& cpu, const AddressingResult& addr);
    
    // === Transfer Instructions ===
    void TAX(CPU6502& cpu, const AddressingResult& addr);
    void TAY(CPU6502& cpu, const AddressingResult& addr);
    void TXA(CPU6502& cpu, const AddressingResult& addr);
    void TYA(CPU6502& cpu, const AddressingResult& addr);
    void TSX(CPU6502& cpu, const AddressingResult& addr);
    void TXS(CPU6502& cpu, const AddressingResult& addr);
    
    // === Stack Instructions ===
    void PHA(CPU6502& cpu, const AddressingResult& addr);
    void PHP(CPU6502& cpu, const AddressingResult& addr);
    void PLA(CPU6502& cpu, const AddressingResult& addr);
    void PLP(CPU6502& cpu, const AddressingResult& addr);
    
    // === Logical Instructions ===
    void AND(CPU6502& cpu, const AddressingResult& addr);
    void EOR(CPU6502& cpu, const AddressingResult& addr);
    void ORA(CPU6502& cpu, const AddressingResult& addr);
    void BIT(CPU6502& cpu, const AddressingResult& addr);
    
    // === Arithmetic Instructions ===
    void ADC(CPU6502& cpu, const AddressingResult& addr);
    void SBC(CPU6502& cpu, const AddressingResult& addr);
    void INC(CPU6502& cpu, const AddressingResult& addr);
    void INX(CPU6502& cpu, const AddressingResult& addr);
    void INY(CPU6502& cpu, const AddressingResult& addr);
    void DEC(CPU6502& cpu, const AddressingResult& addr);
    void DEX(CPU6502& cpu, const AddressingResult& addr);
    void DEY(CPU6502& cpu, const AddressingResult& addr);
    
    // === Shift/Rotate Instructions ===
    void ASL(CPU6502& cpu, const AddressingResult& addr);
    void LSR(CPU6502& cpu, const AddressingResult& addr);
    void ROL(CPU6502& cpu, const AddressingResult& addr);
    void ROR(CPU6502& cpu, const AddressingResult& addr);
    
    // === Compare Instructions ===
    void CMP(CPU6502& cpu, const AddressingResult& addr);
    void CPX(CPU6502& cpu, const AddressingResult& addr);
    void CPY(CPU6502& cpu, const AddressingResult& addr);
    
    // === Branch Instructions ===
    void BCC(CPU6502& cpu, const AddressingResult& addr);
    void BCS(CPU6502& cpu, const AddressingResult& addr);
    void BEQ(CPU6502& cpu, const AddressingResult& addr);
    void BMI(CPU6502& cpu, const AddressingResult& addr);
    void BNE(CPU6502& cpu, const AddressingResult& addr);
    void BPL(CPU6502& cpu, const AddressingResult& addr);
    void BVC(CPU6502& cpu, const AddressingResult& addr);
    void BVS(CPU6502& cpu, const AddressingResult& addr);
    
    // === Jump/Subroutine Instructions ===
    void JMP(CPU6502& cpu, const AddressingResult& addr);
    void JSR(CPU6502& cpu, const AddressingResult& addr);
    void RTS(CPU6502& cpu, const AddressingResult& addr);
    void RTI(CPU6502& cpu, const AddressingResult& addr);
    
    // === Flag Instructions ===
    void CLC(CPU6502& cpu, const AddressingResult& addr);
    void CLD(CPU6502& cpu, const AddressingResult& addr);
    void CLI(CPU6502& cpu, const AddressingResult& addr);
    void CLV(CPU6502& cpu, const AddressingResult& addr);
    void SEC(CPU6502& cpu, const AddressingResult& addr);
    void SED(CPU6502& cpu, const AddressingResult& addr);
    void SEI(CPU6502& cpu, const AddressingResult& addr);
    
    // === Special Instructions ===
    void BRK(CPU6502& cpu, const AddressingResult& addr);
    void NOP(CPU6502& cpu, const AddressingResult& addr);
}

// Opcode table (256 entries)
extern const OpcodeInfo OPCODE_TABLE[256];

#endif // NES_INSTRUCTIONS_H
