/*
 * NES Batch Kernel - Phase 5: SoA Refactoring
 *
 * Uses Structure-of-Arrays (SoA) state layout for GPU memory coalescing.
 * Each CUDA thread handles one NES instance. Block size = 32 (one full warp).
 *
 * Grid layout:
 *   gridDim.x  = ceil(num_instances / NES_BATCH_BLOCK_SIZE)
 *   blockDim.x = NES_BATCH_BLOCK_SIZE (32)
 *
 * WHY SoA ENABLES BLOCK SIZE 32:
 * With AoS (Phase 4), accessing ppu.cycle for 32 threads spanned 32×4504=144KB
 * (32× memory bandwidth overhead). With SoA, all N ppu_cycle values are in a
 * contiguous array: loading [0..31] = 128 bytes = 1 cache line = 1 transaction.
 *
 * Per-kernel pattern:
 *   1. Load scalar fields from SoA arrays → local NESCPUState/NESPPUState
 *      (coalesced: 32 consecutive scalars loaded in 1-2 cache line transactions)
 *   2. Set array pointers (ram, vram, oam, palette) into SoA batch allocations
 *   3. Run the full frame using existing cpu_step/ppu_tick device functions
 *   4. Write scalar fields back to SoA arrays (coalesced)
 *   5. Large arrays (ram, vram, oam) were modified in-place via pointers in step 3
 *
 * Phase 5 expected improvement: ~30-50% at 1000 instances (39%→~100% warp util)
 */

#include "device/nes_state.h"
#include "device/nes_batch_states_soa.h"
#include "device/ppu_device.cuh"
#include "device/cpu_device.cuh"

#define NES_BATCH_BLOCK_SIZE 32

// ---------------------------------------------------------------------------
// nes_batch_run_frame: run one frame for all instances in parallel
//
// Parameters:
//   soa          - device pointer to NESBatchStatesSoA (all scalars + array ptrs)
//   prg_rom      - device pointer to shared PRG ROM (same ROM for all)
//   prg_size     - PRG ROM size in bytes
//   chr_rom      - device pointer to shared CHR ROM
//   chr_size     - CHR ROM size in bytes
//
// Grid:  <<<ceil(N/32), 32>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_run_frame(NESBatchStatesSoA* soa,
                                     const uint8_t* prg_rom, uint32_t prg_size,
                                     const uint8_t* chr_rom, uint32_t chr_size) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= soa->num_instances) return;

    // --- Load scalars from SoA (coalesced) ---
    NESCPUState cpu;
    NESPPUState ppu;
    soa_load_cpu(soa, idx, &cpu);
    soa_load_ppu(soa, idx, &ppu);

    ppu.frame_ready = 0;
    ppu.headless    = 0;  // Single-frame kernel always does full rendering

    const int MAX_CPU_CYCLES = 65000;  // 2× one frame; allows long init sequences
    int total_cpu_cycles = 0;

    while (!ppu.frame_ready && total_cpu_cycles < MAX_CPU_CYCLES) {
        int cpu_cycles = cpu_step(&cpu, &ppu, chr_rom, prg_rom, prg_size);
        total_cpu_cycles += cpu_cycles;

        for (int i = 0; i < cpu_cycles * 3; i++) {
            ppu_tick(&ppu, chr_rom);
            if (ppu.nmi_flag) {
                ppu.nmi_flag = 0;
                cpu.nmi_pending = 1;
            }
        }
    }

    // --- Write scalars back to SoA (coalesced) ---
    soa_store_cpu(soa, idx, &cpu);
    soa_store_ppu(soa, idx, &ppu);
}

// ---------------------------------------------------------------------------
// nes_batch_reset: reset all instances in parallel
// Grid: <<<ceil(N/32), 32>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_reset(NESBatchStatesSoA* soa,
                                 const uint8_t* prg_rom, uint32_t prg_size,
                                 const uint8_t* chr_rom, uint32_t chr_size) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= soa->num_instances) return;

    // Build local PPU/CPU with array pointers set
    NESCPUState cpu;
    NESPPUState ppu;

    cpu.ram           = soa->cpu_ram    + (size_t)idx * NES_RAM_SIZE;
    ppu.vram          = soa->ppu_vram   + (size_t)idx * NES_VRAM_SIZE;
    ppu.oam           = soa->ppu_oam    + (size_t)idx * NES_OAM_SIZE;
    ppu.palette       = soa->ppu_palette+ (size_t)idx * NES_PALETTE_SIZE;
    ppu.active_sprites= soa->ppu_active_sprites + (size_t)idx * NES_MAX_SPRITES;
    ppu.framebuffer   = nullptr;  // Set by run kernels

    ppu_reset(&ppu);
    ppu.mirroring = soa->ppu_mirroring[idx];  // Preserve mirroring set by host
    cpu_reset(&cpu, &ppu, chr_rom, prg_rom, prg_size);

    soa_store_cpu(soa, idx, &cpu);
    soa_store_ppu(soa, idx, &ppu);
    // Restore mirroring (soa_store_ppu writes it back, so it's fine)
}

// ---------------------------------------------------------------------------
// nes_batch_step_frames: run N frames for all instances (benchmarking)
// Grid: <<<ceil(N/32), 32>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_step_frames(NESBatchStatesSoA* soa,
                                       const uint8_t* prg_rom, uint32_t prg_size,
                                       const uint8_t* chr_rom, uint32_t chr_size,
                                       int num_frames) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= soa->num_instances) return;

    // --- Load scalars from SoA ---
    NESCPUState cpu;
    NESPPUState ppu;
    soa_load_cpu(soa, idx, &cpu);
    soa_load_ppu(soa, idx, &ppu);

    for (int frame = 0; frame < num_frames; frame++) {
        // Headless mode for intermediate frames: skip BG rendering and sprite-0-only
        // evaluation to save ~80% of rendering work. Only the last frame needs full
        // rendering for the observation.  Sprite-0-hit detection still fires correctly
        // via the simplified check in ppu_render_sprite_pixel.
        ppu.headless = (frame < num_frames - 1) ? 1u : 0u;

        ppu.frame_ready = 0;
        const int MAX_CPU_CYCLES = 65000;  // 2× one frame; allows long init sequences
        int total_cpu_cycles = 0;

        while (!ppu.frame_ready && total_cpu_cycles < MAX_CPU_CYCLES) {
            int cpu_cycles = cpu_step(&cpu, &ppu, chr_rom, prg_rom, prg_size);
            total_cpu_cycles += cpu_cycles;

            for (int i = 0; i < cpu_cycles * 3; i++) {
                ppu_tick(&ppu, chr_rom);
                if (ppu.nmi_flag) {
                    ppu.nmi_flag = 0;
                    cpu.nmi_pending = 1;
                }
            }
        }
    }

    // --- Write scalars back to SoA ---
    soa_store_cpu(soa, idx, &cpu);
    soa_store_ppu(soa, idx, &ppu);
}

// ---------------------------------------------------------------------------
// nes_batch_get_framebuffers: copy all framebuffers to flat RGBA32 output
//
// output layout: [instance 0 framebuffer (240×256 uint32)] [instance 1] ...
// Grid: <<<num_instances, 256>>>  (one block per instance, 256 threads per column)
// ---------------------------------------------------------------------------
__global__ void nes_batch_get_framebuffers(const NESBatchStatesSoA* soa,
                                            uint32_t* output) {
    int inst = blockIdx.x;
    int col  = threadIdx.x;
    if (inst >= soa->num_instances || col >= 256) return;

    const uint8_t* fb = soa->ppu_framebuffer + (size_t)inst * NES_FRAMEBUFFER_SIZE;
    uint32_t* out = output + (size_t)inst * (240 * 256);

    for (int row = 0; row < 240; row++) {
        uint8_t idx = fb[row * 256 + col];
        out[row * 256 + col] = NES_PALETTE_CONST[idx];  // palette index → RGBA32
    }
}

// ---------------------------------------------------------------------------
// nes_batch_get_obs: render all framebuffers as 84×84 grayscale observations
//
// Downsamples 240×256 → 84×84 using bilinear interpolation + luma conversion.
// Format: 0xFFRRGGBB for palette (A byte unused, R/G/B extracted for luma).
//
// obs_out: [N × 84 × 84] uint8 (row-major, grayscale 0-255)
// Grid: <<<dim3(N, 84, 1), 84>>> — N×84 blocks × 84 threads
// ---------------------------------------------------------------------------
__device__ __forceinline__ float nes_pal_to_gray(uint8_t pal_idx) {
    uint32_t rgba = NES_PALETTE_CONST[pal_idx];
    float r = (float)((rgba >> 16) & 0xFFu);
    float g = (float)((rgba >>  8) & 0xFFu);
    float b = (float)(rgba & 0xFFu);
    return 0.299f * r + 0.587f * g + 0.114f * b;
}

__global__ void nes_batch_get_obs(const NESBatchStatesSoA* soa,
                                   uint8_t* obs_out, int N) {
    int inst  = blockIdx.x;
    int out_y = blockIdx.y;
    int out_x = threadIdx.x;
    if (inst >= N || out_y >= 84 || out_x >= 84) return;

    const uint8_t* fb = soa->ppu_framebuffer + (size_t)inst * NES_FRAMEBUFFER_SIZE;

    // Map output pixel center to source pixel center (bilinear)
    float fy = (out_y + 0.5f) * (240.0f / 84.0f) - 0.5f;
    float fx = (out_x + 0.5f) * (256.0f / 84.0f) - 0.5f;

    int y0 = (fy < 0.0f) ? 0 : (int)fy;
    int x0 = (fx < 0.0f) ? 0 : (int)fx;
    int y1 = (y0 + 1 < 240) ? y0 + 1 : 239;
    int x1 = (x0 + 1 < 256) ? x0 + 1 : 255;
    float wy = fy - (float)y0;
    float wx = fx - (float)x0;
    if (wy < 0.0f) wy = 0.0f;
    if (wx < 0.0f) wx = 0.0f;

    float gray = (1.0f - wy) * (1.0f - wx) * nes_pal_to_gray(fb[y0 * 256 + x0])
               + (1.0f - wy) * wx           * nes_pal_to_gray(fb[y0 * 256 + x1])
               + wy           * (1.0f - wx) * nes_pal_to_gray(fb[y1 * 256 + x0])
               + wy           * wx           * nes_pal_to_gray(fb[y1 * 256 + x1]);

    obs_out[(size_t)inst * 84 * 84 + (size_t)out_y * 84 + out_x] = (uint8_t)(gray + 0.5f);
}

// ---------------------------------------------------------------------------
// nes_batch_reset_selected: reset only instances where done_mask[idx] != 0
// Grid: <<<ceil(N/32), 32>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_reset_selected(NESBatchStatesSoA* soa,
                                          const uint8_t* done_mask,
                                          const uint8_t* prg_rom, uint32_t prg_size,
                                          const uint8_t* chr_rom, uint32_t chr_size) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= soa->num_instances) return;
    if (!done_mask[idx]) return;

    NESCPUState cpu;
    NESPPUState ppu;
    cpu.ram            = soa->cpu_ram     + (size_t)idx * NES_RAM_SIZE;
    ppu.vram           = soa->ppu_vram    + (size_t)idx * NES_VRAM_SIZE;
    ppu.oam            = soa->ppu_oam     + (size_t)idx * NES_OAM_SIZE;
    ppu.palette        = soa->ppu_palette + (size_t)idx * NES_PALETTE_SIZE;
    ppu.active_sprites = soa->ppu_active_sprites + (size_t)idx * NES_MAX_SPRITES;
    ppu.framebuffer    = nullptr;

    ppu_reset(&ppu);
    ppu.mirroring = soa->ppu_mirroring[idx];
    cpu_reset(&cpu, &ppu, chr_rom, prg_rom, prg_size);

    soa_store_cpu(soa, idx, &cpu);
    soa_store_ppu(soa, idx, &ppu);
}
