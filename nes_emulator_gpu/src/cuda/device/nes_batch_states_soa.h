#pragma once

/*
 * NES Batch States - Structure of Arrays (SoA) Layout
 *
 * Phase 5: SoA refactoring for GPU coalescing.
 *
 * AoS (old):  states[N] — accessing ppu.cycle for 32 threads spans 32×4504=144KB
 * SoA (new):  ppu_cycle[N] — accessing 32 consecutive elements = 128B (1 cache line)
 *
 * Layout:
 *   Scalar fields: separate [N]-element arrays → perfect coalescing with block_size=32
 *   Large arrays:  AoS-within-batch (instance i's RAM at i*2048) — random access anyway
 *
 * Usage in kernels (block_size=32):
 *   int idx = blockIdx.x * blockDim.x + threadIdx.x;
 *   // 1. Load scalars from SoA → local NESCPUState/NESPPUState
 *   NESCPUState cpu;
 *   cpu.A  = soa->cpu_A[idx];   // coalesced: loads [0..31] in 1 transaction
 *   cpu.ram = soa->cpu_ram + (size_t)idx * NES_RAM_SIZE;  // pointer only
 *   ...
 *   // 2. Run frame using existing device functions (cpu_step, ppu_tick)
 *   // 3. Write scalars back to SoA
 *   soa->cpu_A[idx] = cpu.A;    // coalesced write
 *
 * NOTE: This struct is stored in device memory. The pointers inside point to
 * other device allocations managed by NESBatchGpu. The struct itself is small
 * (~400 bytes) and can be passed by value or via device pointer.
 */

#include "nes_state.h"

struct NESBatchStatesSoA {
    int num_instances;

    // ---- CPU scalar fields — each is a [num_instances] array ----
    uint8_t*  cpu_A;              // Accumulator
    uint8_t*  cpu_X;              // Index X
    uint8_t*  cpu_Y;              // Index Y
    uint8_t*  cpu_SP;             // Stack pointer
    uint16_t* cpu_PC;             // Program counter
    uint8_t*  cpu_P;              // Processor status
    uint64_t* cpu_total_cycles;   // Total cycles executed
    uint8_t*  cpu_nmi_pending;    // NMI pending flag
    uint8_t*  cpu_irq_pending;    // IRQ pending flag

    // ---- CPU large array ----
    uint8_t*  cpu_ram;            // [N × NES_RAM_SIZE]  AoS layout

    // ---- PPU scalar fields — each is a [num_instances] array ----
    uint8_t*  ppu_ctrl;           // $2000 PPUCTRL
    uint8_t*  ppu_mask;           // $2001 PPUMASK
    uint8_t*  ppu_status;         // $2002 PPUSTATUS
    uint8_t*  ppu_oam_addr;       // $2003 OAMADDR
    uint16_t* ppu_v;              // Loopy VRAM address
    uint16_t* ppu_t;              // Loopy temp address
    uint8_t*  ppu_fine_x;         // Fine X scroll
    uint8_t*  ppu_w;              // Write toggle
    uint8_t*  ppu_read_buffer;    // PPUDATA read buffer
    uint8_t*  ppu_mirroring;      // Mirroring mode
    int*      ppu_scanline;       // Current scanline
    int*      ppu_cycle;          // Current cycle within scanline
    uint8_t*  ppu_frame_ready;    // Frame complete flag
    uint8_t*  ppu_nmi_flag;       // NMI trigger flag
    int*      ppu_active_sprite_count;  // Sprites on current scanline

    // ---- PPU large arrays ----
    uint8_t*         ppu_vram;    // [N × NES_VRAM_SIZE]
    uint8_t*         ppu_palette; // [N × NES_PALETTE_SIZE]
    uint8_t*         ppu_oam;     // [N × NES_OAM_SIZE]
    ActiveSpriteGPU* ppu_active_sprites;  // [N × NES_MAX_SPRITES]
    uint8_t*         ppu_framebuffer;     // [N × NES_FRAMEBUFFER_SIZE]
};

// ---------------------------------------------------------------------------
// Inline helpers to load/store NESCPUState and NESPPUState from/to SoA
// (defined inline so they can be used in both host .cu and device kernels)
// ---------------------------------------------------------------------------

__device__ __forceinline__ void soa_load_cpu(const NESBatchStatesSoA* soa, int idx,
                                              NESCPUState* cpu) {
    cpu->A            = soa->cpu_A[idx];
    cpu->X            = soa->cpu_X[idx];
    cpu->Y            = soa->cpu_Y[idx];
    cpu->SP           = soa->cpu_SP[idx];
    cpu->PC           = soa->cpu_PC[idx];
    cpu->P            = soa->cpu_P[idx];
    cpu->total_cycles = soa->cpu_total_cycles[idx];
    cpu->nmi_pending  = soa->cpu_nmi_pending[idx];
    cpu->irq_pending  = soa->cpu_irq_pending[idx];
    cpu->ram          = soa->cpu_ram + (size_t)idx * NES_RAM_SIZE;
}

__device__ __forceinline__ void soa_store_cpu(NESBatchStatesSoA* soa, int idx,
                                               const NESCPUState* cpu) {
    soa->cpu_A[idx]            = cpu->A;
    soa->cpu_X[idx]            = cpu->X;
    soa->cpu_Y[idx]            = cpu->Y;
    soa->cpu_SP[idx]           = cpu->SP;
    soa->cpu_PC[idx]           = cpu->PC;
    soa->cpu_P[idx]            = cpu->P;
    soa->cpu_total_cycles[idx] = cpu->total_cycles;
    soa->cpu_nmi_pending[idx]  = cpu->nmi_pending;
    soa->cpu_irq_pending[idx]  = cpu->irq_pending;
    // cpu->ram is a pointer into SoA; writes during frame already went to SoA
}

__device__ __forceinline__ void soa_load_ppu(const NESBatchStatesSoA* soa, int idx,
                                              NESPPUState* ppu) {
    ppu->ctrl         = soa->ppu_ctrl[idx];
    ppu->mask         = soa->ppu_mask[idx];
    ppu->status       = soa->ppu_status[idx];
    ppu->oam_addr     = soa->ppu_oam_addr[idx];
    ppu->v            = soa->ppu_v[idx];
    ppu->t            = soa->ppu_t[idx];
    ppu->fine_x       = soa->ppu_fine_x[idx];
    ppu->w            = soa->ppu_w[idx];
    ppu->read_buffer  = soa->ppu_read_buffer[idx];
    ppu->mirroring    = soa->ppu_mirroring[idx];
    ppu->scanline     = soa->ppu_scanline[idx];
    ppu->cycle        = soa->ppu_cycle[idx];
    ppu->frame_ready  = soa->ppu_frame_ready[idx];
    ppu->nmi_flag     = soa->ppu_nmi_flag[idx];
    ppu->active_sprite_count = soa->ppu_active_sprite_count[idx];

    // Set array pointers into SoA batch allocations
    ppu->vram            = soa->ppu_vram    + (size_t)idx * NES_VRAM_SIZE;
    ppu->palette         = soa->ppu_palette + (size_t)idx * NES_PALETTE_SIZE;
    ppu->oam             = soa->ppu_oam     + (size_t)idx * NES_OAM_SIZE;
    ppu->active_sprites  = soa->ppu_active_sprites + (size_t)idx * NES_MAX_SPRITES;
    ppu->framebuffer     = soa->ppu_framebuffer + (size_t)idx * NES_FRAMEBUFFER_SIZE;
}

__device__ __forceinline__ void soa_store_ppu(NESBatchStatesSoA* soa, int idx,
                                               const NESPPUState* ppu) {
    soa->ppu_ctrl[idx]         = ppu->ctrl;
    soa->ppu_mask[idx]         = ppu->mask;
    soa->ppu_status[idx]       = ppu->status;
    soa->ppu_oam_addr[idx]     = ppu->oam_addr;
    soa->ppu_v[idx]            = ppu->v;
    soa->ppu_t[idx]            = ppu->t;
    soa->ppu_fine_x[idx]       = ppu->fine_x;
    soa->ppu_w[idx]            = ppu->w;
    soa->ppu_read_buffer[idx]  = ppu->read_buffer;
    soa->ppu_mirroring[idx]    = ppu->mirroring;
    soa->ppu_scanline[idx]     = ppu->scanline;
    soa->ppu_cycle[idx]        = ppu->cycle;
    soa->ppu_frame_ready[idx]  = ppu->frame_ready;
    soa->ppu_nmi_flag[idx]     = ppu->nmi_flag;
    soa->ppu_active_sprite_count[idx] = ppu->active_sprite_count;
    // vram/palette/oam/active_sprites/framebuffer: writes during frame already
    // went directly to SoA arrays via the pointer in ppu
}
