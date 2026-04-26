/*
 * NES Batch GPU - Phase 5: SoA Refactoring
 *
 * Manages N independent NES instances running in parallel on the GPU
 * using Structure-of-Arrays (SoA) state layout for coalesced memory access.
 *
 * Phase 4 (AoS):  NESState[N], 4.5KB/instance, <<<N,1>>> kernels
 * Phase 5 (SoA):  NESBatchStatesSoA, ~120B scalars + separate arrays, <<<ceil(N/32),32>>> kernels
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
#include "device/nes_batch_states_soa.h"

// Forward declarations for SoA batch kernels
__global__ void nes_batch_run_frame(NESBatchStatesSoA*, const uint8_t*, uint32_t,
                                     const uint8_t*, uint32_t);
__global__ void nes_batch_reset(NESBatchStatesSoA*, const uint8_t*, uint32_t,
                                 const uint8_t*, uint32_t);
__global__ void nes_batch_step_frames(NESBatchStatesSoA*, const uint8_t*, uint32_t,
                                       const uint8_t*, uint32_t, int);
__global__ void nes_batch_get_framebuffers(const NESBatchStatesSoA*, uint32_t*);

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

    // Read back one instance's full state (for debugging/RL observation)
    void get_state(int instance_idx, NESState& out) const;

    // Write one instance's state (for setting different initial conditions)
    void set_state(int instance_idx, const NESState& state);

    int num_instances() const { return num_instances_; }

private:
    int num_instances_;

    // ---- SoA struct (on device) ----
    // d_soa_ is a device pointer to a NESBatchStatesSoA struct.
    // The struct itself lives on the device and contains device pointers
    // to the backing arrays below.
    NESBatchStatesSoA* d_soa_ = nullptr;

    // ---- Scalar field arrays (N elements each, separate allocs) ----
    // CPU scalars
    uint8_t*  d_cpu_A_             = nullptr;
    uint8_t*  d_cpu_X_             = nullptr;
    uint8_t*  d_cpu_Y_             = nullptr;
    uint8_t*  d_cpu_SP_            = nullptr;
    uint16_t* d_cpu_PC_            = nullptr;
    uint8_t*  d_cpu_P_             = nullptr;
    uint64_t* d_cpu_total_cycles_  = nullptr;
    uint8_t*  d_cpu_nmi_pending_   = nullptr;
    uint8_t*  d_cpu_irq_pending_   = nullptr;
    // PPU scalars
    uint8_t*  d_ppu_ctrl_                = nullptr;
    uint8_t*  d_ppu_mask_                = nullptr;
    uint8_t*  d_ppu_status_              = nullptr;
    uint8_t*  d_ppu_oam_addr_            = nullptr;
    uint16_t* d_ppu_v_                   = nullptr;
    uint16_t* d_ppu_t_                   = nullptr;
    uint8_t*  d_ppu_fine_x_              = nullptr;
    uint8_t*  d_ppu_w_                   = nullptr;
    uint8_t*  d_ppu_read_buffer_         = nullptr;
    uint8_t*  d_ppu_mirroring_           = nullptr;
    int*      d_ppu_scanline_            = nullptr;
    int*      d_ppu_cycle_               = nullptr;
    uint8_t*  d_ppu_frame_ready_         = nullptr;
    uint8_t*  d_ppu_nmi_flag_            = nullptr;
    int*      d_ppu_active_sprite_count_ = nullptr;

    // ---- Large array allocations (N × array_size) ----
    uint8_t*         d_cpu_ram_          = nullptr;  // [N × NES_RAM_SIZE]
    uint8_t*         d_ppu_vram_         = nullptr;  // [N × NES_VRAM_SIZE]
    uint8_t*         d_ppu_palette_      = nullptr;  // [N × NES_PALETTE_SIZE]
    uint8_t*         d_ppu_oam_          = nullptr;  // [N × NES_OAM_SIZE]
    ActiveSpriteGPU* d_ppu_sprites_      = nullptr;  // [N × NES_MAX_SPRITES]
    uint8_t*         d_ppu_framebuffer_  = nullptr;  // [N × NES_FRAMEBUFFER_SIZE]

    // ---- ROM ----
    uint8_t*  d_prg_       = nullptr;
    uint8_t*  d_chr_       = nullptr;
    uint32_t  prg_size_    = 0;
    uint32_t  chr_size_    = 0;

    // ---- RGBA32 output buffer ----
    uint32_t* d_fb_out_    = nullptr;  // [N × 240 × 256]

    bool rom_loaded_ = false;

    // Helper: allocate all SoA arrays and build the SoA struct on device
    void alloc_soa();
    void free_soa();
};
