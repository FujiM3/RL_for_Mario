/*
 * NES Batch GPU - Phase 4: Host Interface
 *
 * Manages N independent NES instances running in parallel on the GPU.
 * All instances share the same PRG/CHR ROM (same game).
 *
 * Usage:
 *   NESBatchGpu batch(1000);
 *   batch.load_rom(prg_data, prg_size, chr_data, chr_size);
 *   batch.reset_all(MIRROR_HORIZONTAL);
 *   for (int step = 0; step < 1000; step++) {
 *       batch.run_frame_all();
 *       batch.get_framebuffers(output);  // optional
 *   }
 */

#pragma once

#include <cstdint>
#include <vector>
#include <stdexcept>
#include "device/nes_state.h"

// Forward declarations for batch kernels
__global__ void nes_batch_run_frame(NESState*, const uint8_t*, uint32_t,
                                     const uint8_t*, uint32_t, int, uint8_t*);
__global__ void nes_batch_reset(NESState*, const uint8_t*, uint32_t,
                                 const uint8_t*, uint32_t, int);
__global__ void nes_batch_step_frames(NESState*, const uint8_t*, uint32_t,
                                       const uint8_t*, uint32_t, int, int, uint8_t*);
__global__ void nes_batch_get_framebuffers(const NESState*, uint32_t*, int, const uint8_t*);

class NESBatchGpu {
public:
    explicit NESBatchGpu(int num_instances);
    ~NESBatchGpu();

    // Prevent copy (manages device memory)
    NESBatchGpu(const NESBatchGpu&) = delete;
    NESBatchGpu& operator=(const NESBatchGpu&) = delete;

    // Load ROM to device (shared across all instances)
    void load_rom(const uint8_t* prg_rom, uint32_t prg_size,
                  const uint8_t* chr_rom, uint32_t chr_size);

    // Reset all instances (must call after load_rom)
    void reset_all(uint8_t mirroring = MIRROR_HORIZONTAL);

    // Run one frame for all instances in parallel
    void run_frame_all();

    // Run N frames for all instances (no host sync between frames, fast)
    void run_frames_all(int num_frames);

    // Copy all framebuffers to host (output: num_instances × 240 × 256 uint32)
    void get_framebuffers(uint32_t* host_output);

    // Read back one instance's full state (for debugging)
    void get_state(int instance_idx, NESState& out) const;

    // Write one instance's state (for setting different initial conditions)
    void set_state(int instance_idx, const NESState& state);

    int num_instances() const { return num_instances_; }

private:
    int num_instances_;

    // Device memory
    NESState* d_states_    = nullptr;  // [num_instances] NESState (~4.5KB each)
    uint8_t*  d_prg_       = nullptr;
    uint8_t*  d_chr_       = nullptr;
    uint8_t*  d_fb_pool_   = nullptr;  // [num_instances × 61440] palette-index pool
    uint32_t* d_fb_out_    = nullptr;  // [num_instances × 240 × 256] RGBA32 output

    uint32_t prg_size_ = 0;
    uint32_t chr_size_ = 0;

    bool rom_loaded_ = false;
};
