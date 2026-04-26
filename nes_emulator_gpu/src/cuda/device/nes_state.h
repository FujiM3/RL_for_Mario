#pragma once

/*
 * NES GPU State Structures
 *
 * Phase 3: Flat C-style structs for GPU device code.
 * Replaces OOP classes from Phase 2 reference implementation.
 *
 * Design principles:
 * - No std::function (not allowed in CUDA device code)
 * - No virtual functions, no inheritance
 * - Fixed-size arrays only (no dynamic allocation)
 * - Compatible with both __host__ and __device__ code
 *
 * Memory per NES instance:
 *   CPU state:  ~2 KB  (registers + 2 KB RAM)
 *   PPU state:  ~248 KB (registers + VRAM + OAM + palette + framebuffer)
 *   Total:      ~250 KB
 */

#include <stdint.h>

// ---------------------------------------------------------------------------
// CPU Status Flag Bits
// ---------------------------------------------------------------------------
#define CPU_FLAG_C 0x01u  // Carry
#define CPU_FLAG_Z 0x02u  // Zero
#define CPU_FLAG_I 0x04u  // Interrupt Disable
#define CPU_FLAG_D 0x08u  // Decimal (unused on NES)
#define CPU_FLAG_B 0x10u  // Break command
#define CPU_FLAG_U 0x20u  // Unused (always 1)
#define CPU_FLAG_V 0x40u  // Overflow
#define CPU_FLAG_N 0x80u  // Negative

// ---------------------------------------------------------------------------
// Memory sizes
// ---------------------------------------------------------------------------
#define NES_RAM_SIZE           2048
#define NES_VRAM_SIZE          2048
#define NES_OAM_SIZE           256
#define NES_PALETTE_SIZE       32
#define NES_FRAMEBUFFER_SIZE   (256 * 240)  // 61440 pixels
#define NES_MAX_SPRITES        8

// ---------------------------------------------------------------------------
// Mirroring modes (matches PPU::Mirroring enum from reference)
// ---------------------------------------------------------------------------
#define MIRROR_HORIZONTAL  0   // SMB uses this
#define MIRROR_VERTICAL    1
#define MIRROR_SINGLE_A    2
#define MIRROR_SINGLE_B    3
#define MIRROR_FOUR_SCREEN 4

// ---------------------------------------------------------------------------
// Interrupt / Reset vectors
// ---------------------------------------------------------------------------
#define NES_NMI_VECTOR   0xFFFA
#define NES_RESET_VECTOR 0xFFFC
#define NES_IRQ_VECTOR   0xFFFE

// ---------------------------------------------------------------------------
// Active sprite: pre-fetched per scanline to avoid CHR reads during rendering
// (Phase 2 optimization carried over to GPU)
// ---------------------------------------------------------------------------
struct ActiveSpriteGPU {
    uint8_t  x;          // X position
    uint8_t  y;          // Y position (raw OAM value)
    uint8_t  tile;       // Tile index
    uint8_t  attr;       // Attribute byte (palette/priority/flip)
    uint8_t  oam_index;  // Original OAM entry (0-63)
    uint16_t pattern;    // Pre-fetched: lo plane in high byte, hi plane in low byte
};

// ---------------------------------------------------------------------------
// PPU state
// ---------------------------------------------------------------------------
struct NESPPUState {
    // ---- CPU-visible registers ($2000-$2007) ----
    uint8_t  ctrl;        // $2000 PPUCTRL: NMI enable, pattern table selects, etc.
    uint8_t  mask;        // $2001 PPUMASK: rendering enables, color emphasis
    uint8_t  status;      // $2002 PPUSTATUS: VBlank, sprite-0-hit, overflow
    uint8_t  oam_addr;    // $2003 OAMADDR: OAM byte address for next DMA/write

    // ---- Internal Loopy scroll registers ----
    uint16_t v;           // Current VRAM address (15 bits): yyy NN YYYYY XXXXX
    uint16_t t;           // Temporary VRAM address (15 bits)
    uint8_t  fine_x;      // Fine X scroll (3 bits, 0-7)
    uint8_t  w;           // Write toggle: 0 = first write, 1 = second write

    // ---- PPUDATA internal read buffer ----
    uint8_t  read_buffer;

    // ---- Mirroring mode ----
    uint8_t  mirroring;   // One of MIRROR_* constants

    // ---- PPU memory ----
    uint8_t  vram[NES_VRAM_SIZE];           // 2 KB nametable VRAM
    uint8_t  palette[NES_PALETTE_SIZE];     // 32-byte palette RAM
    uint8_t  oam[NES_OAM_SIZE];             // 256-byte Object Attribute Memory

    // ---- Output framebuffer (pointer to 256×240 palette-index buffer) ----
    // Framebuffer lives in a separate device allocation to reduce NESState size.
    // Before each frame, the kernel sets this pointer to the instance's slice.
    // Use nes_get_framebuffer / nes_batch_get_framebuffers to get RGBA32 output.
    uint8_t* framebuffer;

    // ---- Sprite rendering state (rebuilt each scanline) ----
    ActiveSpriteGPU active_sprites[NES_MAX_SPRITES];
    int             active_sprite_count;

    // ---- Timing counters ----
    int scanline;   // Current scanline (0-261)
    int cycle;      // Current cycle within scanline (0-340)

    // ---- Control flags ----
    uint8_t frame_ready;  // Set when entering scanline 261 (pre-render)
    uint8_t nmi_flag;     // Set at VBlank start if NMI enabled in ctrl
};

// ---------------------------------------------------------------------------
// CPU state
// ---------------------------------------------------------------------------
struct NESCPUState {
    // ---- Registers ----
    uint8_t  A;           // Accumulator
    uint8_t  X;           // Index register X
    uint8_t  Y;           // Index register Y
    uint8_t  SP;          // Stack pointer (full address = 0x0100 | SP)
    uint16_t PC;          // Program counter
    uint8_t  P;           // Processor status (NV_BDIZC)

    // ---- 2 KB internal RAM ----
    uint8_t  ram[NES_RAM_SIZE];

    // ---- Cycle tracking ----
    uint64_t total_cycles;

    // ---- Interrupt flags ----
    uint8_t  nmi_pending;
    uint8_t  irq_pending;
};

// ---------------------------------------------------------------------------
// ROM data (passed as read-only pointers; lives in separate device memory)
// ---------------------------------------------------------------------------
struct NESROMData {
    const uint8_t* prg_rom;   // PRG ROM (typically 16KB or 32KB for NROM)
    uint32_t       prg_size;  // Size in bytes (0x4000 = 16KB, 0x8000 = 32KB)
    const uint8_t* chr_rom;   // CHR ROM (typically 8KB for NROM)
    uint32_t       chr_size;  // Size in bytes
};

// ---------------------------------------------------------------------------
// Combined NES instance state
// ---------------------------------------------------------------------------
struct NESState {
    NESCPUState cpu;
    NESPPUState ppu;
};
