#pragma once

/*
 * CPU Device Functions - Phase 3 GPU Port
 *
 * Ports the 6502 CPU (src/reference/cpu/) to CUDA __device__ functions.
 *
 * Key changes from reference:
 *   - std::function read/write callbacks  ->  direct inline memory dispatch
 *   - Class methods  ->  free __device__ functions taking NESCPUState*
 *   - OpcodeInfo table with function pointers  ->  flat switch statement
 *   - No exceptions (replace with NOP on illegal opcodes)
 *
 * Memory map implemented:
 *   $0000-$07FF  2KB internal RAM (mirrored to $1FFF)
 *   $2000-$3FFF  PPU registers (mirrors of $2000-$2007)
 *   $4014        OAM DMA
 *   $8000-$FFFF  PRG ROM (16KB mirrored or 32KB)
 *
 * Note: APU ($4000-$4013,$4015-$401F) and controllers ($4016-$4017)
 *       are stubbed (reads return 0, writes ignored) for Phase 3.
 */

#include "nes_state.h"
#include "ppu_device.cuh"

// ---------------------------------------------------------------------------
// CPU flag helpers
// ---------------------------------------------------------------------------
__device__ __forceinline__ bool cpu_flag(const NESCPUState* c, uint8_t f) { return (c->P & f) != 0; }
__device__ __forceinline__ void cpu_set_flag(NESCPUState* c, uint8_t f, bool v) {
    if (v) c->P |= f; else c->P &= ~f;
}
__device__ __forceinline__ void cpu_update_zn(NESCPUState* c, uint8_t val) {
    cpu_set_flag(c, CPU_FLAG_Z, val == 0);
    cpu_set_flag(c, CPU_FLAG_N, (val & 0x80u) != 0);
}

// Status with B flag set (for BRK/PHP)
__device__ __forceinline__ uint8_t cpu_status_brk(const NESCPUState* c) {
    return c->P | CPU_FLAG_B | CPU_FLAG_U;
}
// Status with B flag clear (for NMI/IRQ)
__device__ __forceinline__ uint8_t cpu_status_irq(const NESCPUState* c) {
    return (c->P & ~CPU_FLAG_B) | CPU_FLAG_U;
}

// ---------------------------------------------------------------------------
// Memory read/write through NES address space
// ---------------------------------------------------------------------------
__device__ uint8_t cpu_read(NESCPUState* cpu, NESPPUState* ppu,
                             const uint8_t* chr_rom,
                             const uint8_t* prg_rom, uint32_t prg_size,
                             uint16_t addr) {
    if (addr < 0x2000u) {
        return cpu->ram[addr & 0x07FFu];  // 2KB mirrored
    } else if (addr < 0x4000u) {
        return ppu_read_register(ppu, chr_rom, addr);  // PPU registers
    } else if (addr == 0x4016u || addr == 0x4017u) {
        return 0u;  // Controller (stub)
    } else if (addr >= 0x8000u) {
        if (prg_size == 0x4000u) {
            return __ldg(&prg_rom[(addr - 0x8000u) & 0x3FFFu]);  // 16KB mirrored
        }
        return __ldg(&prg_rom[addr - 0x8000u]);  // 32KB
    }
    return 0u;
}

__device__ void cpu_write(NESCPUState* cpu, NESPPUState* ppu,
                           const uint8_t* prg_rom, uint32_t prg_size,
                           uint16_t addr, uint8_t value) {
    if (addr < 0x2000u) {
        cpu->ram[addr & 0x07FFu] = value;  // 2KB mirrored
    } else if (addr < 0x4000u) {
        ppu_write_register(ppu, addr, value);  // PPU registers
    } else if (addr == 0x4014u) {
        // OAM DMA: copy CPU RAM page to PPU OAM
        ppu_oam_dma(ppu, cpu->ram, value);
        cpu->total_cycles += 513;  // OAM DMA stall cycles
    }
    // Writes to ROM and other addresses ignored in Phase 3
}

// Helper for 16-bit reads
__device__ __forceinline__ uint16_t cpu_read16(NESCPUState* cpu, NESPPUState* ppu,
                                                const uint8_t* chr_rom,
                                                const uint8_t* prg_rom, uint32_t prg_size,
                                                uint16_t addr) {
    uint8_t lo = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
    uint8_t hi = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)(addr + 1));
    return (uint16_t)((hi << 8) | lo);
}

// 6502 page-crossing bug: indirect JMP wraps within page
__device__ __forceinline__ uint16_t cpu_read16_bug(NESCPUState* cpu, NESPPUState* ppu,
                                                    const uint8_t* chr_rom,
                                                    const uint8_t* prg_rom, uint32_t prg_size,
                                                    uint16_t addr) {
    uint16_t hi_addr = (addr & 0xFF00u) | (uint16_t)((addr + 1) & 0x00FFu);
    uint8_t lo = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
    uint8_t hi = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, hi_addr);
    return (uint16_t)((hi << 8) | lo);
}

// ---------------------------------------------------------------------------
// Stack operations (stack at $0100-$01FF)
// ---------------------------------------------------------------------------
__device__ __forceinline__ void cpu_push(NESCPUState* cpu, NESPPUState* ppu,
                                          const uint8_t* prg_rom, uint32_t prg_size,
                                          uint8_t value) {
    cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)(0x0100u + cpu->SP), value);
    cpu->SP--;
}

__device__ __forceinline__ uint8_t cpu_pop(NESCPUState* cpu, NESPPUState* ppu,
                                            const uint8_t* chr_rom,
                                            const uint8_t* prg_rom, uint32_t prg_size) {
    cpu->SP++;
    return cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)(0x0100u + cpu->SP));
}

__device__ __forceinline__ void cpu_push16(NESCPUState* cpu, NESPPUState* ppu,
                                            const uint8_t* prg_rom, uint32_t prg_size,
                                            uint16_t value) {
    cpu_push(cpu, ppu, prg_rom, prg_size, (uint8_t)(value >> 8));
    cpu_push(cpu, ppu, prg_rom, prg_size, (uint8_t)(value & 0xFFu));
}

__device__ __forceinline__ uint16_t cpu_pop16(NESCPUState* cpu, NESPPUState* ppu,
                                               const uint8_t* chr_rom,
                                               const uint8_t* prg_rom, uint32_t prg_size) {
    uint8_t lo = cpu_pop(cpu, ppu, chr_rom, prg_rom, prg_size);
    uint8_t hi = cpu_pop(cpu, ppu, chr_rom, prg_rom, prg_size);
    return (uint16_t)((hi << 8) | lo);
}

// ---------------------------------------------------------------------------
// Interrupt execution
// ---------------------------------------------------------------------------
__device__ __forceinline__ void cpu_execute_nmi(NESCPUState* cpu, NESPPUState* ppu,
                                                 const uint8_t* chr_rom,
                                                 const uint8_t* prg_rom, uint32_t prg_size) {
    cpu_push16(cpu, ppu, prg_rom, prg_size, cpu->PC);
    cpu_push(cpu, ppu, prg_rom, prg_size, cpu_status_irq(cpu));
    cpu_set_flag(cpu, CPU_FLAG_I, true);
    cpu->PC = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, NES_NMI_VECTOR);
    cpu->total_cycles += 7;
}

__device__ __forceinline__ void cpu_execute_irq(NESCPUState* cpu, NESPPUState* ppu,
                                                 const uint8_t* chr_rom,
                                                 const uint8_t* prg_rom, uint32_t prg_size) {
    cpu_push16(cpu, ppu, prg_rom, prg_size, cpu->PC);
    cpu_push(cpu, ppu, prg_rom, prg_size, cpu_status_irq(cpu));
    cpu_set_flag(cpu, CPU_FLAG_I, true);
    cpu->PC = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, NES_IRQ_VECTOR);
    cpu->total_cycles += 7;
}

// ---------------------------------------------------------------------------
// Page crossing check
// ---------------------------------------------------------------------------
__device__ __forceinline__ bool cpu_page_crossed(uint16_t a, uint16_t b) {
    return (a & 0xFF00u) != (b & 0xFF00u);
}

// ---------------------------------------------------------------------------
// CPU step: fetch, decode, and execute one instruction
// Returns the number of cycles consumed.
// ---------------------------------------------------------------------------
__device__ int cpu_step(NESCPUState* cpu, NESPPUState* ppu,
                         const uint8_t* chr_rom,
                         const uint8_t* prg_rom, uint32_t prg_size) {
    // Handle pending NMI before fetch
    if (cpu->nmi_pending) {
        cpu->nmi_pending = 0;
        cpu_execute_nmi(cpu, ppu, chr_rom, prg_rom, prg_size);
        return 7;
    }
    if (cpu->irq_pending && !cpu_flag(cpu, CPU_FLAG_I)) {
        cpu->irq_pending = 0;
        cpu_execute_irq(cpu, ppu, chr_rom, prg_rom, prg_size);
        return 7;
    }

    uint8_t opcode = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);

    // Shorthand macros for addressing (reduces boilerplate)
    // All declared as local variables inside the switch arms they're used in.

    int cycles = 2;        // default cycles; overridden per opcode

    switch (opcode) {

    // -----------------------------------------------------------------------
    // LDA
    case 0xA9: { // LDA imm
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->A);
        cycles = 2; break;
    }
    case 0xA5: { // LDA zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->A);
        cycles = 3; break;
    }
    case 0xB5: { // LDA zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp + cpu->X) & 0xFFu));
        cpu_update_zn(cpu, cpu->A);
        cycles = 4; break;
    }
    case 0xAD: { // LDA abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4; break;
    }
    case 0xBD: { // LDA abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xB9: { // LDA abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xA1: { // LDA (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 6; break;
    }
    case 0xB1: { // LDA (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    // -----------------------------------------------------------------------
    // LDX
    case 0xA2: { // LDX imm
        cpu->X = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->X); cycles = 2; break;
    }
    case 0xA6: { // LDX zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->X = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->X); cycles = 3; break;
    }
    case 0xB6: { // LDX zp,Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->X = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp + cpu->Y) & 0xFFu));
        cpu_update_zn(cpu, cpu->X); cycles = 4; break;
    }
    case 0xAE: { // LDX abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->X = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->X); cycles = 4; break;
    }
    case 0xBE: { // LDX abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->X = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->X);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    // -----------------------------------------------------------------------
    // LDY
    case 0xA0: { // LDY imm
        cpu->Y = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->Y); cycles = 2; break;
    }
    case 0xA4: { // LDY zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->Y = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->Y); cycles = 3; break;
    }
    case 0xB4: { // LDY zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->Y = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp + cpu->X) & 0xFFu));
        cpu_update_zn(cpu, cpu->Y); cycles = 4; break;
    }
    case 0xAC: { // LDY abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->Y = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->Y); cycles = 4; break;
    }
    case 0xBC: { // LDY abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cpu->Y = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->Y);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    // -----------------------------------------------------------------------
    // STA
    case 0x85: { // STA zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, cpu->A);
        cycles = 3; break;
    }
    case 0x95: { // STA zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)((zp + cpu->X) & 0xFFu), cpu->A);
        cycles = 4; break;
    }
    case 0x8D: { // STA abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->A);
        cycles = 4; break;
    }
    case 0x9D: { // STA abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->A);
        cycles = 5; break;
    }
    case 0x99: { // STA abs,Y
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->Y); cpu->PC += 2;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->A);
        cycles = 5; break;
    }
    case 0x81: { // STA (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->A);
        cycles = 6; break;
    }
    case 0x91: { // STA (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp) + cpu->Y);
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->A);
        cycles = 6; break;
    }

    // -----------------------------------------------------------------------
    // STX
    case 0x86: { // STX zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, cpu->X);
        cycles = 3; break;
    }
    case 0x96: { // STX zp,Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)((zp + cpu->Y) & 0xFFu), cpu->X);
        cycles = 4; break;
    }
    case 0x8E: { // STX abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->X);
        cycles = 4; break;
    }

    // -----------------------------------------------------------------------
    // STY
    case 0x84: { // STY zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, cpu->Y);
        cycles = 3; break;
    }
    case 0x94: { // STY zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)((zp + cpu->X) & 0xFFu), cpu->Y);
        cycles = 4; break;
    }
    case 0x8C: { // STY abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, cpu->Y);
        cycles = 4; break;
    }

    // -----------------------------------------------------------------------
    // Register Transfers
    case 0xAA: { cpu->X = cpu->A; cpu_update_zn(cpu, cpu->X); cycles = 2; break; } // TAX
    case 0xA8: { cpu->Y = cpu->A; cpu_update_zn(cpu, cpu->Y); cycles = 2; break; } // TAY
    case 0x8A: { cpu->A = cpu->X; cpu_update_zn(cpu, cpu->A); cycles = 2; break; } // TXA
    case 0x98: { cpu->A = cpu->Y; cpu_update_zn(cpu, cpu->A); cycles = 2; break; } // TYA
    case 0xBA: { cpu->X = cpu->SP; cpu_update_zn(cpu, cpu->X); cycles = 2; break; } // TSX
    case 0x9A: { cpu->SP = cpu->X; cycles = 2; break; } // TXS (no flag update)

    // -----------------------------------------------------------------------
    // Stack
    case 0x48: { // PHA
        cpu_push(cpu, ppu, prg_rom, prg_size, cpu->A);
        cycles = 3; break;
    }
    case 0x08: { // PHP
        cpu_push(cpu, ppu, prg_rom, prg_size, cpu_status_brk(cpu));
        cycles = 3; break;
    }
    case 0x68: { // PLA
        cpu->A = cpu_pop(cpu, ppu, chr_rom, prg_rom, prg_size);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4; break;
    }
    case 0x28: { // PLP
        cpu->P = (cpu_pop(cpu, ppu, chr_rom, prg_rom, prg_size) & ~CPU_FLAG_B) | CPU_FLAG_U;
        cycles = 4; break;
    }

    // -----------------------------------------------------------------------
    // Logical
    case 0x29: { // AND imm
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x25: { // AND zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->A); cycles = 3; break;
    }
    case 0x35: { // AND zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x2D: { // AND abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x3D: { // AND abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x39: { // AND abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x21: { // AND (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 6; break;
    }
    case 0x31: { // AND (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A &= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    case 0x49: { // EOR imm
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x45: { // EOR zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->A); cycles = 3; break;
    }
    case 0x55: { // EOR zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x4D: { // EOR abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x5D: { // EOR abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x59: { // EOR abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x41: { // EOR (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 6; break;
    }
    case 0x51: { // EOR (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A ^= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    case 0x09: { // ORA imm
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x05: { // ORA zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_update_zn(cpu, cpu->A); cycles = 3; break;
    }
    case 0x15: { // ORA zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x0D: { // ORA abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 4; break;
    }
    case 0x1D: { // ORA abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x19: { // ORA abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x01: { // ORA (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A); cycles = 6; break;
    }
    case 0x11: { // ORA (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        cpu->A |= cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_update_zn(cpu, cpu->A);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    case 0x24: { // BIT zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_set_flag(cpu, CPU_FLAG_Z, (cpu->A & val) == 0);
        cpu_set_flag(cpu, CPU_FLAG_N, (val & 0x80u) != 0);
        cpu_set_flag(cpu, CPU_FLAG_V, (val & 0x40u) != 0);
        cycles = 3; break;
    }
    case 0x2C: { // BIT abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_Z, (cpu->A & val) == 0);
        cpu_set_flag(cpu, CPU_FLAG_N, (val & 0x80u) != 0);
        cpu_set_flag(cpu, CPU_FLAG_V, (val & 0x40u) != 0);
        cycles = 4; break;
    }

    // -----------------------------------------------------------------------
    // Arithmetic: ADC
    case 0x69: { // ADC imm
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 2; break;
    }
    case 0x65: { // ADC zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 3; break;
    }
    case 0x75: { // ADC zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 4; break;
    }
    case 0x6D: { // ADC abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 4; break;
    }
    case 0x7D: { // ADC abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x79: { // ADC abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0x61: { // ADC (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 6; break;
    }
    case 0x71: { // ADC (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t sum = (uint16_t)cpu->A + val + (cpu_flag(cpu, CPU_FLAG_C) ? 1 : 0);
        uint8_t r = (uint8_t)(sum & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, sum > 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) == 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    // -----------------------------------------------------------------------
    // Arithmetic: SBC (A = A - M - (1-C), equivalent to ADC with ~M)
    case 0xE9: { // SBC imm
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 2; break;
    }
    case 0xE5: { // SBC zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 3; break;
    }
    case 0xF5: { // SBC zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 4; break;
    }
    case 0xED: { // SBC abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 4; break;
    }
    case 0xFD: { // SBC abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xF9: { // SBC abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xE1: { // SBC (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r); cycles = 6; break;
    }
    case 0xF1: { // SBC (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint16_t diff = (uint16_t)cpu->A - val - (cpu_flag(cpu, CPU_FLAG_C) ? 0 : 1);
        uint8_t r = (uint8_t)(diff & 0xFFu);
        cpu_set_flag(cpu, CPU_FLAG_C, diff < 0x100u);
        cpu_set_flag(cpu, CPU_FLAG_V, ((cpu->A ^ val) & 0x80u) != 0 && ((cpu->A ^ r) & 0x80u) != 0);
        cpu->A = r; cpu_update_zn(cpu, r);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    // -----------------------------------------------------------------------
    // INC / DEC memory
    case 0xE6: { // INC zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp) + 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0xF6: { // INC zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) + 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0xEE: { // INC abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) + 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0xFE: { // INC abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) + 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }
    case 0xC6: { // DEC zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp) - 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0xD6: { // DEC zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) - 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0xCE: { // DEC abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) - 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0xDE: { // DEC abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr) - 1;
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }

    // INX/INY/DEX/DEY
    case 0xE8: { cpu->X++; cpu_update_zn(cpu, cpu->X); cycles = 2; break; } // INX
    case 0xC8: { cpu->Y++; cpu_update_zn(cpu, cpu->Y); cycles = 2; break; } // INY
    case 0xCA: { cpu->X--; cpu_update_zn(cpu, cpu->X); cycles = 2; break; } // DEX
    case 0x88: { cpu->Y--; cpu_update_zn(cpu, cpu->Y); cycles = 2; break; } // DEY

    // -----------------------------------------------------------------------
    // Shift/Rotate (accumulator mode: address==0 and not immediate in reference;
    //               here we use separate opcodes for accumulator vs. memory)
    case 0x0A: { // ASL A
        cpu_set_flag(cpu, CPU_FLAG_C, (cpu->A & 0x80u) != 0);
        cpu->A <<= 1; cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x06: { // ASL zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v <<= 1; cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0x16: { // ASL zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v <<= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x0E: { // ASL abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v <<= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x1E: { // ASL abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v <<= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }

    case 0x4A: { // LSR A
        cpu_set_flag(cpu, CPU_FLAG_C, (cpu->A & 0x01u) != 0);
        cpu->A >>= 1; cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x46: { // LSR zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v >>= 1; cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0x56: { // LSR zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v >>= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x4E: { // LSR abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v >>= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x5E: { // LSR abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v >>= 1; cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }

    case 0x2A: { // ROL A
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (cpu->A & 0x80u) != 0);
        cpu->A = (uint8_t)((cpu->A << 1) | (old_c ? 1 : 0));
        cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x26: { // ROL zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v = (uint8_t)((v << 1) | (old_c ? 1 : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0x36: { // ROL zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v = (uint8_t)((v << 1) | (old_c ? 1 : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x2E: { // ROL abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v = (uint8_t)((v << 1) | (old_c ? 1 : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x3E: { // ROL abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x80u) != 0);
        v = (uint8_t)((v << 1) | (old_c ? 1 : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }

    case 0x6A: { // ROR A
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (cpu->A & 0x01u) != 0);
        cpu->A = (uint8_t)((cpu->A >> 1) | (old_c ? 0x80u : 0));
        cpu_update_zn(cpu, cpu->A); cycles = 2; break;
    }
    case 0x66: { // ROR zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v = (uint8_t)((v >> 1) | (old_c ? 0x80u : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, (uint16_t)zp, v);
        cpu_update_zn(cpu, v); cycles = 5; break;
    }
    case 0x76: { // ROR zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t addr = (uint16_t)((zp + cpu->X) & 0xFFu);
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v = (uint8_t)((v >> 1) | (old_c ? 0x80u : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x6E: { // ROR abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v = (uint8_t)((v >> 1) | (old_c ? 0x80u : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 6; break;
    }
    case 0x7E: { // ROR abs,X
        uint16_t addr = (uint16_t)(cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC) + cpu->X); cpu->PC += 2;
        uint8_t v = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        bool old_c = cpu_flag(cpu, CPU_FLAG_C);
        cpu_set_flag(cpu, CPU_FLAG_C, (v & 0x01u) != 0);
        v = (uint8_t)((v >> 1) | (old_c ? 0x80u : 0));
        cpu_write(cpu, ppu, prg_rom, prg_size, addr, v);
        cpu_update_zn(cpu, v); cycles = 7; break;
    }

    // -----------------------------------------------------------------------
    // Compare
    case 0xC9: { // CMP imm
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 2; break;
    }
    case 0xC5: { // CMP zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 3; break;
    }
    case 0xD5: { // CMP zp,X
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)((zp+cpu->X)&0xFFu));
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4; break;
    }
    case 0xCD: { // CMP abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4; break;
    }
    case 0xDD: { // CMP abs,X
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xD9: { // CMP abs,Y
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }
    case 0xC1: { // CMP (ind,X)
        uint8_t zp = (uint8_t)(cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++) + cpu->X);
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 6; break;
    }
    case 0xD1: { // CMP (ind),Y
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint16_t addr = (uint16_t)(base + cpu->Y);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->A - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->A >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->A == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 5 + (cpu_page_crossed(base, addr) ? 1 : 0); break;
    }

    case 0xE0: { // CPX imm
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t r = (uint8_t)(cpu->X - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->X >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->X == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 2; break;
    }
    case 0xE4: { // CPX zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t r = (uint8_t)(cpu->X - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->X >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->X == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 3; break;
    }
    case 0xEC: { // CPX abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->X - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->X >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->X == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4; break;
    }

    case 0xC0: { // CPY imm
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t r = (uint8_t)(cpu->Y - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->Y >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->Y == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 2; break;
    }
    case 0xC4: { // CPY zp
        uint8_t zp = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, (uint16_t)zp);
        uint8_t r = (uint8_t)(cpu->Y - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->Y >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->Y == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 3; break;
    }
    case 0xCC: { // CPY abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint8_t val = cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, addr);
        uint8_t r = (uint8_t)(cpu->Y - val);
        cpu_set_flag(cpu, CPU_FLAG_C, cpu->Y >= val);
        cpu_set_flag(cpu, CPU_FLAG_Z, cpu->Y == val);
        cpu_set_flag(cpu, CPU_FLAG_N, (r & 0x80u) != 0);
        cycles = 4; break;
    }

    // -----------------------------------------------------------------------
    // Branch instructions (extra cycle if taken, +1 more if page crossed)
    case 0x90: { // BCC
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (!cpu_flag(cpu, CPU_FLAG_C)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0xB0: { // BCS
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (cpu_flag(cpu, CPU_FLAG_C)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0xF0: { // BEQ
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (cpu_flag(cpu, CPU_FLAG_Z)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0x30: { // BMI
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (cpu_flag(cpu, CPU_FLAG_N)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0xD0: { // BNE
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (!cpu_flag(cpu, CPU_FLAG_Z)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0x10: { // BPL
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (!cpu_flag(cpu, CPU_FLAG_N)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0x50: { // BVC
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (!cpu_flag(cpu, CPU_FLAG_V)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }
    case 0x70: { // BVS
        int8_t offset = (int8_t)cpu_read(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC++);
        if (cpu_flag(cpu, CPU_FLAG_V)) {
            uint16_t new_pc = (uint16_t)(cpu->PC + offset);
            cycles = 3 + (cpu_page_crossed(cpu->PC, new_pc) ? 1 : 0);
            cpu->PC = new_pc;
        } else { cycles = 2; }
        break;
    }

    // -----------------------------------------------------------------------
    // Jump / Subroutine
    case 0x4C: { // JMP abs
        cpu->PC = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC);
        cycles = 3; break;
    }
    case 0x6C: { // JMP (ind) -- with 6502 page-wrap bug
        uint16_t ptr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu->PC = cpu_read16_bug(cpu, ppu, chr_rom, prg_rom, prg_size, ptr);
        cycles = 5; break;
    }
    case 0x20: { // JSR abs
        uint16_t addr = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        cpu_push16(cpu, ppu, prg_rom, prg_size, (uint16_t)(cpu->PC - 1));
        cpu->PC = addr;
        cycles = 6; break;
    }
    case 0x60: { // RTS
        cpu->PC = (uint16_t)(cpu_pop16(cpu, ppu, chr_rom, prg_rom, prg_size) + 1);
        cycles = 6; break;
    }
    case 0x40: { // RTI
        cpu->P = (cpu_pop(cpu, ppu, chr_rom, prg_rom, prg_size) & ~CPU_FLAG_B) | CPU_FLAG_U;
        cpu->PC = cpu_pop16(cpu, ppu, chr_rom, prg_rom, prg_size);
        cycles = 6; break;
    }

    // -----------------------------------------------------------------------
    // Flags
    case 0x18: { cpu_set_flag(cpu, CPU_FLAG_C, false); cycles = 2; break; } // CLC
    case 0xD8: { cpu_set_flag(cpu, CPU_FLAG_D, false); cycles = 2; break; } // CLD
    case 0x58: { cpu_set_flag(cpu, CPU_FLAG_I, false); cycles = 2; break; } // CLI
    case 0xB8: { cpu_set_flag(cpu, CPU_FLAG_V, false); cycles = 2; break; } // CLV
    case 0x38: { cpu_set_flag(cpu, CPU_FLAG_C, true);  cycles = 2; break; } // SEC
    case 0xF8: { cpu_set_flag(cpu, CPU_FLAG_D, true);  cycles = 2; break; } // SED
    case 0x78: { cpu_set_flag(cpu, CPU_FLAG_I, true);  cycles = 2; break; } // SEI

    // -----------------------------------------------------------------------
    // BRK
    case 0x00: {
        cpu->PC++;  // Skip padding byte
        cpu_push16(cpu, ppu, prg_rom, prg_size, cpu->PC);
        cpu_push(cpu, ppu, prg_rom, prg_size, cpu_status_brk(cpu));
        cpu_set_flag(cpu, CPU_FLAG_I, true);
        cpu->PC = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, NES_IRQ_VECTOR);
        cycles = 7; break;
    }

    // -----------------------------------------------------------------------
    // NOP
    case 0xEA: { cycles = 2; break; }

    // -----------------------------------------------------------------------
    // Unofficial NOPs (common in NES games)
    case 0x1A: case 0x3A: case 0x5A: case 0x7A: case 0xDA: case 0xFA:
        cycles = 2; break;
    case 0x80: case 0x82: case 0x89: case 0xC2: case 0xE2:
        cpu->PC++; cycles = 2; break;  // NOP imm
    case 0x04: case 0x44: case 0x64:
        cpu->PC++; cycles = 3; break;  // NOP zp
    case 0x14: case 0x34: case 0x54: case 0x74: case 0xD4: case 0xF4:
        cpu->PC++; cycles = 4; break;  // NOP zp,X
    case 0x0C:
        cpu->PC += 2; cycles = 4; break;  // NOP abs
    case 0x1C: case 0x3C: case 0x5C: case 0x7C: case 0xDC: case 0xFC: {
        uint16_t base = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, cpu->PC); cpu->PC += 2;
        uint16_t addr = (uint16_t)(base + cpu->X);
        cycles = 4 + (cpu_page_crossed(base, addr) ? 1 : 0); break;  // NOP abs,X
    }

    // -----------------------------------------------------------------------
    default:
        // Unknown/illegal opcode: treat as NOP (1 cycle)
        cycles = 1;
        break;

    } // end switch (opcode)

    cpu->total_cycles += (uint64_t)cycles;
    return cycles;
}

// ---------------------------------------------------------------------------
// CPU reset: load PC from RESET vector
// ---------------------------------------------------------------------------
__device__ void cpu_reset(NESCPUState* cpu, NESPPUState* ppu,
                           const uint8_t* chr_rom,
                           const uint8_t* prg_rom, uint32_t prg_size) {
    cpu->A = 0;
    cpu->X = 0;
    cpu->Y = 0;
    cpu->SP = 0xFD;
    cpu->P = CPU_FLAG_U | CPU_FLAG_I;
    cpu->total_cycles = 0;
    cpu->nmi_pending = 0;
    cpu->irq_pending = 0;

    for (int i = 0; i < NES_RAM_SIZE; i++) cpu->ram[i] = 0;

    cpu->PC = cpu_read16(cpu, ppu, chr_rom, prg_rom, prg_size, NES_RESET_VECTOR);
}
