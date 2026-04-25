#ifndef NES_TYPES_H
#define NES_TYPES_H

#include <cstdint>
#include <cstddef>

// Basic type aliases for NES emulation
using u8  = uint8_t;   // 8-bit unsigned
using u16 = uint16_t;  // 16-bit unsigned
using u32 = uint32_t;  // 32-bit unsigned
using u64 = uint64_t;  // 64-bit unsigned
using s8  = int8_t;    // 8-bit signed
using s16 = int16_t;   // 16-bit signed

// CPU Status Register Flags (P register)
// Format: NV-BDIZC (8 bits)
enum class CPUFlag : u8 {
    C = 0,  // Carry
    Z = 1,  // Zero
    I = 2,  // Interrupt Disable
    D = 3,  // Decimal Mode (not used on NES, but implemented for completeness)
    B = 4,  // Break Command
    U = 5,  // Unused (always 1)
    V = 6,  // Overflow
    N = 7   // Negative
};

// Convert flag enum to bit mask
inline constexpr u8 flag_mask(CPUFlag flag) {
    return 1 << static_cast<u8>(flag);
}

// NES Memory Layout Constants
namespace Memory {
    // CPU Address Space
    constexpr u16 RAM_START         = 0x0000;
    constexpr u16 RAM_END           = 0x07FF;
    constexpr u16 RAM_SIZE          = 0x0800;  // 2KB internal RAM
    
    constexpr u16 RAM_MIRROR_END    = 0x1FFF;  // RAM mirrors 3 times
    
    constexpr u16 PPU_REG_START     = 0x2000;
    constexpr u16 PPU_REG_END       = 0x2007;
    constexpr u16 PPU_MIRROR_END    = 0x3FFF;  // PPU registers mirror many times
    
    constexpr u16 APU_IO_START      = 0x4000;
    constexpr u16 APU_IO_END        = 0x401F;
    
    constexpr u16 SRAM_START        = 0x6000;  // Battery-backed Save RAM
    constexpr u16 SRAM_END          = 0x7FFF;
    constexpr u16 SRAM_SIZE         = 0x2000;  // 8KB
    
    constexpr u16 PRG_ROM_START     = 0x8000;
    constexpr u16 PRG_ROM_END       = 0xFFFF;
    
    // Interrupt Vectors
    constexpr u16 NMI_VECTOR        = 0xFFFA;
    constexpr u16 RESET_VECTOR      = 0xFFFC;
    constexpr u16 IRQ_VECTOR        = 0xFFFE;
    
    // Stack
    constexpr u16 STACK_BASE        = 0x0100;
    constexpr u8  STACK_RESET       = 0xFD;    // Initial SP value
}

// CPU Timing
namespace Timing {
    constexpr u32 CPU_FREQ_HZ       = 1789773;  // NTSC CPU frequency (~1.79 MHz)
    constexpr u32 CPU_FREQ_PAL_HZ   = 1662607;  // PAL CPU frequency (~1.66 MHz)
    constexpr double NTSC_FPS       = 60.0988;
    constexpr double PAL_FPS        = 50.0070;
}

// Addressing Mode Types
enum class AddressingMode : u8 {
    Implied,           // No operand (e.g., NOP, CLC)
    Accumulator,       // Operate on accumulator (e.g., ASL A)
    Immediate,         // #$nn
    ZeroPage,          // $nn
    ZeroPageX,         // $nn,X
    ZeroPageY,         // $nn,Y
    Absolute,          // $nnnn
    AbsoluteX,         // $nnnn,X
    AbsoluteY,         // $nnnn,Y
    Relative,          // Branch instructions
    Indirect,          // ($nnnn) - JMP only
    IndexedIndirect,   // ($nn,X)
    IndirectIndexed    // ($nn),Y
};

// Instruction Opcodes (partial list - will be expanded in instructions.cpp)
namespace Opcode {
    // Some common opcodes for reference
    constexpr u8 BRK_IMP = 0x00;
    constexpr u8 NOP_IMP = 0xEA;
    constexpr u8 LDA_IMM = 0xA9;
    constexpr u8 LDA_ZP  = 0xA5;
    constexpr u8 STA_ZP  = 0x85;
    constexpr u8 JMP_ABS = 0x4C;
    constexpr u8 JSR_ABS = 0x20;
    constexpr u8 RTS_IMP = 0x60;
}

#endif // NES_TYPES_H
