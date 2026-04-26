/*
 * NES Frame Kernel - Phase 3: Single Instance GPU Port
 *
 * Runs one NES instance on one GPU thread for one complete frame.
 *
 * The main kernel (nes_run_frame) performs:
 *   1. Handle any pending NMI
 *   2. Step CPU by one instruction
 *   3. Tick PPU 3× per CPU cycle (CPU:PPU clock ratio = 1:3)
 *   4. Propagate PPU NMI -> CPU
 *   5. Repeat until frame_ready is set (when scanline 261 is entered)
 *   6. Clear frame_ready before returning
 *
 * Phase 3 design: 1 thread, 1 instance, proves correctness.
 * Phase 4 will scale to N threads × M instances.
 */

#include "device/nes_state.h"
#include "device/ppu_device.cuh"
#include "device/cpu_device.cuh"

// ---------------------------------------------------------------------------
// nes_run_frame: run one complete NES frame
//
// Parameters:
//   state    - device pointer to NES state (CPU + PPU)
//   prg_rom  - device pointer to PRG ROM (read-only)
//   prg_size - PRG ROM size in bytes (0x4000 or 0x8000)
//   chr_rom  - device pointer to CHR ROM (read-only, may be NULL for CHR RAM)
//   chr_size - CHR ROM size in bytes
//
// Grid/Block: <<<1,1>>> for Phase 3 (single instance)
// ---------------------------------------------------------------------------
__global__ void nes_run_frame(NESState* state,
                               const uint8_t* prg_rom, uint32_t prg_size,
                               const uint8_t* chr_rom, uint32_t chr_size) {
    NESCPUState* cpu = &state->cpu;
    NESPPUState* ppu = &state->ppu;

    // Clear frame_ready at start so we detect when this frame completes
    ppu->frame_ready = 0;

    // Safety limit: max cycles per frame to avoid infinite loops
    // One frame = ~29,780 CPU cycles (89,342 PPU / 3)
    // Add 20% margin for OAM DMA stalls
    const int MAX_CPU_CYCLES = 36000;
    int total_cpu_cycles = 0;

    while (!ppu->frame_ready && total_cpu_cycles < MAX_CPU_CYCLES) {
        int cpu_cycles = cpu_step(cpu, ppu, chr_rom, prg_rom, prg_size);
        total_cpu_cycles += cpu_cycles;

        // Tick PPU 3× per CPU cycle
        for (int i = 0; i < cpu_cycles * 3; i++) {
            ppu_tick(ppu, chr_rom);

            // Propagate NMI from PPU to CPU (checked each PPU tick for accuracy)
            if (ppu->nmi_flag) {
                ppu->nmi_flag = 0;
                cpu->nmi_pending = 1;
            }
        }
    }

    // Frame is complete: ppu->framebuffer contains the rendered frame
}

// ---------------------------------------------------------------------------
//
// Call this once after copying ROM to device, before the first nes_run_frame.
// Grid/Block: <<<1,1>>>
// ---------------------------------------------------------------------------
__global__ void nes_reset(NESState* state,
                           const uint8_t* prg_rom, uint32_t prg_size,
                           const uint8_t* chr_rom, uint32_t chr_size) {
    ppu_reset(&state->ppu);
    state->ppu.mirroring = MIRROR_HORIZONTAL;  // Default; host can override before launch
    cpu_reset(&state->cpu, &state->ppu, chr_rom, prg_rom, prg_size);
}

// ---------------------------------------------------------------------------
// nes_get_framebuffer: copy framebuffer to a separate output buffer
//
// Useful when the host wants to read the framebuffer without copying
// the entire NESState.
// Grid/Block: <<<240, 256>>> (one thread per pixel row)
// ---------------------------------------------------------------------------
__global__ void nes_get_framebuffer(const NESState* state, uint32_t* output) {
    int row = blockIdx.x;
    int col = threadIdx.x;
    if (row < 240 && col < 256) {
        // Convert palette index → RGBA32 using __constant__ palette lookup
        uint8_t idx = state->ppu.framebuffer[row * 256 + col];
        output[row * 256 + col] = NES_PALETTE_CONST[idx];
    }
}

// ---------------------------------------------------------------------------
// nes_step_frames: run N complete frames back-to-back
//
// Useful for benchmarking without host<->device transfer overhead.
// Grid/Block: <<<1,1>>>
// ---------------------------------------------------------------------------
__global__ void nes_step_frames(NESState* state,
                                 const uint8_t* prg_rom, uint32_t prg_size,
                                 const uint8_t* chr_rom, uint32_t chr_size,
                                 int num_frames) {
    NESCPUState* cpu = &state->cpu;
    NESPPUState* ppu = &state->ppu;

    for (int frame = 0; frame < num_frames; frame++) {
        ppu->frame_ready = 0;
        const int MAX_CPU_CYCLES = 36000;
        int total_cpu_cycles = 0;

        while (!ppu->frame_ready && total_cpu_cycles < MAX_CPU_CYCLES) {
            int cpu_cycles = cpu_step(cpu, ppu, chr_rom, prg_rom, prg_size);
            total_cpu_cycles += cpu_cycles;

            for (int i = 0; i < cpu_cycles * 3; i++) {
                ppu_tick(ppu, chr_rom);
                if (ppu->nmi_flag) {
                    ppu->nmi_flag = 0;
                    cpu->nmi_pending = 1;
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Test helper kernels (used by tests/cuda/test_gpu_single.cu)
// These live here because the test TU cannot include device headers directly
// without causing nvlink duplicate symbol errors.
// ---------------------------------------------------------------------------

__global__ void test_ppu_register_write_read(NESPPUState* ppu) {
    ppu_write_register(ppu, 0x2000, 0x90u);  // PPUCTRL: NMI enable + bg table $1000
    ppu_write_register(ppu, 0x2001, 0x1Eu);  // PPUMASK: enable bg + sprites
}

__global__ void test_ppu_vblank(NESPPUState* ppu, const uint8_t* chr_rom) {
    ppu->scanline = 240;
    ppu->cycle    = 340;
    ppu->ctrl     = 0x80u;  // NMI enable
    ppu_tick(ppu, chr_rom); // -> (241, 0)
    ppu_tick(ppu, chr_rom); // -> (241, 1) = VBlank start
}
