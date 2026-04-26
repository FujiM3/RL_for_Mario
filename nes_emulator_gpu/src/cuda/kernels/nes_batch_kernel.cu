/*
 * NES Batch Kernel - Phase 4: GPU Batch Parallel
 *
 * Runs N independent NES instances in parallel on the GPU.
 * Each CUDA block (1 thread per block) handles one NES instance.
 *
 * Grid layout:
 *   gridDim.x  = num_instances
 *   blockDim.x = 1 (one thread per block)
 *
 * WHY 1 THREAD PER BLOCK:
 * NES state is Array-of-Structures (AoS), 4.5KB per instance. If multiple
 * threads in the same warp each handle a different instance, their state
 * accesses are strided by 4.5KB — 32 non-coalesced memory transactions per
 * warp instruction instead of 1. This overwhelms the memory controller and
 * causes severe bandwidth regression.
 *
 * With 1 thread per block, each SM schedules ≤32 blocks concurrently. Each
 * block has its own warp with 1 active thread — no coalescing issue. The GPU
 * hides latency by switching between the 32 active warps.
 *
 * The path to further improvement is Structure-of-Arrays (SoA) state layout
 * so that all instances' `ppu.cycle` values are stored contiguously, enabling
 * true coalesced access. That would allow larger block sizes to be beneficial.
 *
 * Phase 4 target: 30,240 SPS (120× vs nes_py 252 SPS)
 */

#include "device/nes_state.h"
#include "device/ppu_device.cuh"
#include "device/cpu_device.cuh"

// ---------------------------------------------------------------------------
// nes_batch_run_frame: run one frame for all instances in parallel
//
// Parameters:
//   states       - device pointer to array of NESState[num_instances]
//   prg_rom      - device pointer to shared PRG ROM (same ROM for all)
//   prg_size     - PRG ROM size in bytes
//   chr_rom      - device pointer to shared CHR ROM
//   chr_size     - CHR ROM size in bytes
//   num_instances - number of NES instances
//
// Grid:  <<<num_instances, 1>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_run_frame(NESState* states,
                                     const uint8_t* prg_rom, uint32_t prg_size,
                                     const uint8_t* chr_rom, uint32_t chr_size,
                                     int num_instances,
                                     uint8_t* fb_pool) {
    int idx = blockIdx.x;
    if (idx >= num_instances) return;

    NESCPUState* cpu = &states[idx].cpu;
    NESPPUState* ppu = &states[idx].ppu;

    // Set framebuffer pointer for this instance's slice in the pool
    ppu->framebuffer = fb_pool + (size_t)idx * NES_FRAMEBUFFER_SIZE;

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

// ---------------------------------------------------------------------------
// nes_batch_reset: reset all instances in parallel
// Grid: <<<num_instances, 1>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_reset(NESState* states,
                                 const uint8_t* prg_rom, uint32_t prg_size,
                                 const uint8_t* chr_rom, uint32_t chr_size,
                                 int num_instances) {
    int idx = blockIdx.x;
    if (idx >= num_instances) return;

    ppu_reset(&states[idx].ppu);
    states[idx].ppu.mirroring = MIRROR_HORIZONTAL;
    cpu_reset(&states[idx].cpu, &states[idx].ppu, chr_rom, prg_rom, prg_size);
}

// ---------------------------------------------------------------------------
// nes_batch_step_frames: run N frames for all instances (benchmarking)
// Grid: <<<num_instances, 1>>>
// ---------------------------------------------------------------------------
__global__ void nes_batch_step_frames(NESState* states,
                                       const uint8_t* prg_rom, uint32_t prg_size,
                                       const uint8_t* chr_rom, uint32_t chr_size,
                                       int num_instances,
                                       int num_frames,
                                       uint8_t* fb_pool) {
    int idx = blockIdx.x;
    if (idx >= num_instances) return;

    NESCPUState* cpu = &states[idx].cpu;
    NESPPUState* ppu = &states[idx].ppu;

    // Set framebuffer pointer once (reused across all frames)
    ppu->framebuffer = fb_pool + (size_t)idx * NES_FRAMEBUFFER_SIZE;

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
// nes_batch_get_framebuffers: copy all framebuffers to flat output array
//
// output layout: [instance 0 framebuffer (240×256 uint32)] [instance 1] ...
// Grid: <<<num_instances, 256>>>  (one block per instance, 256 threads per row)
// ---------------------------------------------------------------------------
__global__ void nes_batch_get_framebuffers(const NESState* states,
                                            uint32_t* output,
                                            int num_instances,
                                            const uint8_t* fb_pool) {
    int inst = blockIdx.x;
    int col  = threadIdx.x;
    if (inst >= num_instances || col >= 256) return;

    const uint8_t* fb = fb_pool + (size_t)inst * NES_FRAMEBUFFER_SIZE;
    uint32_t* out = output + inst * (240 * 256);

    for (int row = 0; row < 240; row++) {
        uint8_t idx = fb[row * 256 + col];
        out[row * 256 + col] = NES_PALETTE_CONST[idx];  // palette index → RGBA32
    }
}
