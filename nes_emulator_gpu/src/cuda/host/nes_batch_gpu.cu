/*
 * NES Batch GPU Implementation - Phase 5: SoA Refactoring
 */

#include "nes_batch_gpu.h"
#include <cuda_runtime.h>
#include <cstring>
#include <stdexcept>
#include <string>

#include "device/nes_state.h"
#include "device/nes_batch_states_soa.h"

#define CUDA_CHECK(x) do { \
    cudaError_t e = (x); \
    if (e != cudaSuccess) { \
        throw std::runtime_error(std::string("CUDA error: ") + cudaGetErrorString(e)); \
    } \
} while(0)

// Number of threads per block for batch kernels (must be 32 for coalescing)
static constexpr int BLOCK_SIZE = 32;

// ---------------------------------------------------------------------------
// alloc_soa: allocate all SoA backing arrays and build the SoA struct
// ---------------------------------------------------------------------------

void NESBatchGpu::alloc_soa() {
    int N = num_instances_;

    // Allocate scalar arrays
    CUDA_CHECK(cudaMalloc(&d_cpu_A_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_X_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_Y_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_SP_,           (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_PC_,           (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMalloc(&d_cpu_P_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_total_cycles_, (size_t)N * sizeof(uint64_t)));
    CUDA_CHECK(cudaMalloc(&d_cpu_nmi_pending_,  (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_cpu_irq_pending_,  (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_ctrl_,                (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_mask_,                (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_status_,              (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_oam_addr_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_v_,                   (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMalloc(&d_ppu_t_,                   (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMalloc(&d_ppu_fine_x_,              (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_w_,                   (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_read_buffer_,         (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_mirroring_,           (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_scanline_,            (size_t)N * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&d_ppu_cycle_,               (size_t)N * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&d_ppu_frame_ready_,         (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_nmi_flag_,            (size_t)N));
    CUDA_CHECK(cudaMalloc(&d_ppu_active_sprite_count_, (size_t)N * sizeof(int)));

    // Allocate large arrays
    CUDA_CHECK(cudaMalloc(&d_cpu_ram_,         (size_t)N * NES_RAM_SIZE));
    CUDA_CHECK(cudaMalloc(&d_ppu_vram_,        (size_t)N * NES_VRAM_SIZE));
    CUDA_CHECK(cudaMalloc(&d_ppu_palette_,     (size_t)N * NES_PALETTE_SIZE));
    CUDA_CHECK(cudaMalloc(&d_ppu_oam_,         (size_t)N * NES_OAM_SIZE));
    CUDA_CHECK(cudaMalloc(&d_ppu_sprites_,     (size_t)N * NES_MAX_SPRITES * sizeof(ActiveSpriteGPU)));
    CUDA_CHECK(cudaMalloc(&d_ppu_framebuffer_, (size_t)N * NES_FRAMEBUFFER_SIZE));

    // Zero all arrays
    CUDA_CHECK(cudaMemset(d_cpu_A_,            0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_X_,            0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_Y_,            0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_SP_,           0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_PC_,           0, (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMemset(d_cpu_P_,            0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_total_cycles_, 0, (size_t)N * sizeof(uint64_t)));
    CUDA_CHECK(cudaMemset(d_cpu_nmi_pending_,  0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_cpu_irq_pending_,  0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_ctrl_,   0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_mask_,   0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_status_, 0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_oam_addr_,    0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_v_,      0, (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMemset(d_ppu_t_,      0, (size_t)N * sizeof(uint16_t)));
    CUDA_CHECK(cudaMemset(d_ppu_fine_x_, 0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_w_,      0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_read_buffer_, 0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_mirroring_,   0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_scanline_, 0, (size_t)N * sizeof(int)));
    CUDA_CHECK(cudaMemset(d_ppu_cycle_,    0, (size_t)N * sizeof(int)));
    CUDA_CHECK(cudaMemset(d_ppu_frame_ready_,         0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_nmi_flag_,            0, (size_t)N));
    CUDA_CHECK(cudaMemset(d_ppu_active_sprite_count_, 0, (size_t)N * sizeof(int)));
    CUDA_CHECK(cudaMemset(d_cpu_ram_,         0, (size_t)N * NES_RAM_SIZE));
    CUDA_CHECK(cudaMemset(d_ppu_vram_,        0, (size_t)N * NES_VRAM_SIZE));
    CUDA_CHECK(cudaMemset(d_ppu_palette_,     0, (size_t)N * NES_PALETTE_SIZE));
    CUDA_CHECK(cudaMemset(d_ppu_oam_,         0, (size_t)N * NES_OAM_SIZE));
    CUDA_CHECK(cudaMemset(d_ppu_sprites_,     0, (size_t)N * NES_MAX_SPRITES * sizeof(ActiveSpriteGPU)));
    CUDA_CHECK(cudaMemset(d_ppu_framebuffer_, 0, (size_t)N * NES_FRAMEBUFFER_SIZE));

    // Build the SoA struct on host, then copy to device
    NESBatchStatesSoA h_soa;
    h_soa.num_instances = N;
    h_soa.cpu_A             = d_cpu_A_;
    h_soa.cpu_X             = d_cpu_X_;
    h_soa.cpu_Y             = d_cpu_Y_;
    h_soa.cpu_SP            = d_cpu_SP_;
    h_soa.cpu_PC            = d_cpu_PC_;
    h_soa.cpu_P             = d_cpu_P_;
    h_soa.cpu_total_cycles  = d_cpu_total_cycles_;
    h_soa.cpu_nmi_pending   = d_cpu_nmi_pending_;
    h_soa.cpu_irq_pending   = d_cpu_irq_pending_;
    h_soa.cpu_ram           = d_cpu_ram_;
    h_soa.ppu_ctrl                = d_ppu_ctrl_;
    h_soa.ppu_mask                = d_ppu_mask_;
    h_soa.ppu_status              = d_ppu_status_;
    h_soa.ppu_oam_addr            = d_ppu_oam_addr_;
    h_soa.ppu_v                   = d_ppu_v_;
    h_soa.ppu_t                   = d_ppu_t_;
    h_soa.ppu_fine_x              = d_ppu_fine_x_;
    h_soa.ppu_w                   = d_ppu_w_;
    h_soa.ppu_read_buffer         = d_ppu_read_buffer_;
    h_soa.ppu_mirroring           = d_ppu_mirroring_;
    h_soa.ppu_scanline            = d_ppu_scanline_;
    h_soa.ppu_cycle               = d_ppu_cycle_;
    h_soa.ppu_frame_ready         = d_ppu_frame_ready_;
    h_soa.ppu_nmi_flag            = d_ppu_nmi_flag_;
    h_soa.ppu_active_sprite_count = d_ppu_active_sprite_count_;
    h_soa.ppu_vram           = d_ppu_vram_;
    h_soa.ppu_palette        = d_ppu_palette_;
    h_soa.ppu_oam            = d_ppu_oam_;
    h_soa.ppu_active_sprites = d_ppu_sprites_;
    h_soa.ppu_framebuffer    = d_ppu_framebuffer_;

    CUDA_CHECK(cudaMalloc(&d_soa_, sizeof(NESBatchStatesSoA)));
    CUDA_CHECK(cudaMemcpy(d_soa_, &h_soa, sizeof(NESBatchStatesSoA), cudaMemcpyHostToDevice));
}

// ---------------------------------------------------------------------------
// free_soa
// ---------------------------------------------------------------------------

void NESBatchGpu::free_soa() {
    if (d_soa_) { cudaFree(d_soa_); d_soa_ = nullptr; }
    if (d_cpu_A_)             { cudaFree(d_cpu_A_);             d_cpu_A_            = nullptr; }
    if (d_cpu_X_)             { cudaFree(d_cpu_X_);             d_cpu_X_            = nullptr; }
    if (d_cpu_Y_)             { cudaFree(d_cpu_Y_);             d_cpu_Y_            = nullptr; }
    if (d_cpu_SP_)            { cudaFree(d_cpu_SP_);            d_cpu_SP_           = nullptr; }
    if (d_cpu_PC_)            { cudaFree(d_cpu_PC_);            d_cpu_PC_           = nullptr; }
    if (d_cpu_P_)             { cudaFree(d_cpu_P_);             d_cpu_P_            = nullptr; }
    if (d_cpu_total_cycles_)  { cudaFree(d_cpu_total_cycles_);  d_cpu_total_cycles_ = nullptr; }
    if (d_cpu_nmi_pending_)   { cudaFree(d_cpu_nmi_pending_);   d_cpu_nmi_pending_  = nullptr; }
    if (d_cpu_irq_pending_)   { cudaFree(d_cpu_irq_pending_);   d_cpu_irq_pending_  = nullptr; }
    if (d_ppu_ctrl_)                { cudaFree(d_ppu_ctrl_);                d_ppu_ctrl_           = nullptr; }
    if (d_ppu_mask_)                { cudaFree(d_ppu_mask_);                d_ppu_mask_           = nullptr; }
    if (d_ppu_status_)              { cudaFree(d_ppu_status_);              d_ppu_status_         = nullptr; }
    if (d_ppu_oam_addr_)            { cudaFree(d_ppu_oam_addr_);            d_ppu_oam_addr_       = nullptr; }
    if (d_ppu_v_)                   { cudaFree(d_ppu_v_);                   d_ppu_v_              = nullptr; }
    if (d_ppu_t_)                   { cudaFree(d_ppu_t_);                   d_ppu_t_              = nullptr; }
    if (d_ppu_fine_x_)              { cudaFree(d_ppu_fine_x_);              d_ppu_fine_x_         = nullptr; }
    if (d_ppu_w_)                   { cudaFree(d_ppu_w_);                   d_ppu_w_              = nullptr; }
    if (d_ppu_read_buffer_)         { cudaFree(d_ppu_read_buffer_);         d_ppu_read_buffer_    = nullptr; }
    if (d_ppu_mirroring_)           { cudaFree(d_ppu_mirroring_);           d_ppu_mirroring_      = nullptr; }
    if (d_ppu_scanline_)            { cudaFree(d_ppu_scanline_);            d_ppu_scanline_       = nullptr; }
    if (d_ppu_cycle_)               { cudaFree(d_ppu_cycle_);               d_ppu_cycle_          = nullptr; }
    if (d_ppu_frame_ready_)         { cudaFree(d_ppu_frame_ready_);         d_ppu_frame_ready_    = nullptr; }
    if (d_ppu_nmi_flag_)            { cudaFree(d_ppu_nmi_flag_);            d_ppu_nmi_flag_       = nullptr; }
    if (d_ppu_active_sprite_count_) { cudaFree(d_ppu_active_sprite_count_); d_ppu_active_sprite_count_ = nullptr; }
    if (d_cpu_ram_)         { cudaFree(d_cpu_ram_);         d_cpu_ram_         = nullptr; }
    if (d_ppu_vram_)        { cudaFree(d_ppu_vram_);        d_ppu_vram_        = nullptr; }
    if (d_ppu_palette_)     { cudaFree(d_ppu_palette_);     d_ppu_palette_     = nullptr; }
    if (d_ppu_oam_)         { cudaFree(d_ppu_oam_);         d_ppu_oam_         = nullptr; }
    if (d_ppu_sprites_)     { cudaFree(d_ppu_sprites_);     d_ppu_sprites_     = nullptr; }
    if (d_ppu_framebuffer_) { cudaFree(d_ppu_framebuffer_); d_ppu_framebuffer_ = nullptr; }
}

// ---------------------------------------------------------------------------
// Constructor / Destructor
// ---------------------------------------------------------------------------

NESBatchGpu::NESBatchGpu(int num_instances)
    : num_instances_(num_instances) {
    if (num_instances <= 0 || num_instances > 65536) {
        throw std::invalid_argument("num_instances must be 1–65536");
    }

    alloc_soa();

    // RGBA32 output buffer (used by get_framebuffers)
    size_t fb_out_total = (size_t)num_instances_ * NES_FRAMEBUFFER_SIZE * sizeof(uint32_t);
    CUDA_CHECK(cudaMalloc(&d_fb_out_, fb_out_total));
}

NESBatchGpu::~NESBatchGpu() {
    free_soa();
    if (d_prg_)    cudaFree(d_prg_);
    if (d_chr_)    cudaFree(d_chr_);
    if (d_fb_out_) cudaFree(d_fb_out_);
}

// ---------------------------------------------------------------------------
// load_rom
// ---------------------------------------------------------------------------

void NESBatchGpu::load_rom(const uint8_t* prg_rom, uint32_t prg_size,
                            const uint8_t* chr_rom, uint32_t chr_size) {
    if (d_prg_) { cudaFree(d_prg_); d_prg_ = nullptr; }
    if (d_chr_) { cudaFree(d_chr_); d_chr_ = nullptr; }

    CUDA_CHECK(cudaMalloc(&d_prg_, prg_size));
    CUDA_CHECK(cudaMemcpy(d_prg_, prg_rom, prg_size, cudaMemcpyHostToDevice));
    prg_size_ = prg_size;

    CUDA_CHECK(cudaMalloc(&d_chr_, chr_size));
    CUDA_CHECK(cudaMemcpy(d_chr_, chr_rom, chr_size, cudaMemcpyHostToDevice));
    chr_size_ = chr_size;

    rom_loaded_ = true;
}

// ---------------------------------------------------------------------------
// reset_all
// ---------------------------------------------------------------------------

void NESBatchGpu::reset_all(uint8_t mirroring) {
    if (!rom_loaded_) {
        throw std::runtime_error("Call load_rom() before reset_all()");
    }

    // Set mirroring for all instances via host memset
    CUDA_CHECK(cudaMemset(d_ppu_mirroring_, mirroring, (size_t)num_instances_));

    // Launch reset kernel
    int grid = (num_instances_ + BLOCK_SIZE - 1) / BLOCK_SIZE;
    nes_batch_reset<<<grid, BLOCK_SIZE>>>(
        d_soa_, d_prg_, prg_size_, d_chr_, chr_size_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());
}

// ---------------------------------------------------------------------------
// run_frame_all
// ---------------------------------------------------------------------------

void NESBatchGpu::run_frame_all() {
    int grid = (num_instances_ + BLOCK_SIZE - 1) / BLOCK_SIZE;
    nes_batch_run_frame<<<grid, BLOCK_SIZE>>>(
        d_soa_, d_prg_, prg_size_, d_chr_, chr_size_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());
}

// ---------------------------------------------------------------------------
// run_frames_all (no sync between frames for benchmarking)
// ---------------------------------------------------------------------------

void NESBatchGpu::run_frames_all(int num_frames) {
    int grid = (num_instances_ + BLOCK_SIZE - 1) / BLOCK_SIZE;
    nes_batch_step_frames<<<grid, BLOCK_SIZE>>>(
        d_soa_, d_prg_, prg_size_, d_chr_, chr_size_, num_frames);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());
}

// ---------------------------------------------------------------------------
// get_framebuffers
// ---------------------------------------------------------------------------

void NESBatchGpu::get_framebuffers(uint32_t* host_output) {
    // Launch: one block per instance, 256 threads per block (one per pixel column)
    nes_batch_get_framebuffers<<<num_instances_, 256>>>(d_soa_, d_fb_out_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    size_t fb_total = (size_t)num_instances_ * NES_FRAMEBUFFER_SIZE * sizeof(uint32_t);
    CUDA_CHECK(cudaMemcpy(host_output, d_fb_out_, fb_total, cudaMemcpyDeviceToHost));
}

// ---------------------------------------------------------------------------
// get_state: gather one instance's scalars + arrays from SoA → NESState
// ---------------------------------------------------------------------------

void NESBatchGpu::get_state(int instance_idx, NESState& out) const {
    if (instance_idx < 0 || instance_idx >= num_instances_) {
        throw std::out_of_range("instance_idx out of range");
    }
    int i = instance_idx;

    // CPU scalars
    CUDA_CHECK(cudaMemcpy(&out.cpu.A,            d_cpu_A_            + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.X,            d_cpu_X_            + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.Y,            d_cpu_Y_            + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.SP,           d_cpu_SP_           + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.PC,           d_cpu_PC_           + i, sizeof(uint16_t),   cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.P,            d_cpu_P_            + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.total_cycles, d_cpu_total_cycles_ + i, sizeof(uint64_t),   cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.nmi_pending,  d_cpu_nmi_pending_  + i, 1,                  cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.cpu.irq_pending,  d_cpu_irq_pending_  + i, 1,                  cudaMemcpyDeviceToHost));
    out.cpu.ram = nullptr;  // Host NESState doesn't own the GPU RAM

    // PPU scalars
    CUDA_CHECK(cudaMemcpy(&out.ppu.ctrl,        d_ppu_ctrl_        + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.mask,        d_ppu_mask_        + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.status,      d_ppu_status_      + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.oam_addr,    d_ppu_oam_addr_    + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.v,           d_ppu_v_           + i, sizeof(uint16_t), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.t,           d_ppu_t_           + i, sizeof(uint16_t), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.fine_x,      d_ppu_fine_x_      + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.w,           d_ppu_w_           + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.read_buffer, d_ppu_read_buffer_ + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.mirroring,   d_ppu_mirroring_   + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.scanline,    d_ppu_scanline_    + i, sizeof(int), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.cycle,       d_ppu_cycle_       + i, sizeof(int), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.frame_ready, d_ppu_frame_ready_ + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.nmi_flag,    d_ppu_nmi_flag_    + i, 1, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(&out.ppu.active_sprite_count, d_ppu_active_sprite_count_ + i, sizeof(int), cudaMemcpyDeviceToHost));
    // Array pointers in NESState point to GPU memory — set to nullptr for host
    out.ppu.vram           = nullptr;
    out.ppu.palette        = nullptr;
    out.ppu.oam            = nullptr;
    out.ppu.active_sprites = nullptr;
    out.ppu.framebuffer    = nullptr;
}

// ---------------------------------------------------------------------------
// set_state: scatter one instance's scalars from NESState → SoA arrays
// ---------------------------------------------------------------------------

void NESBatchGpu::set_state(int instance_idx, const NESState& state) {
    if (instance_idx < 0 || instance_idx >= num_instances_) {
        throw std::out_of_range("instance_idx out of range");
    }
    int i = instance_idx;

    // CPU scalars
    CUDA_CHECK(cudaMemcpy(d_cpu_A_            + i, &state.cpu.A,            1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_X_            + i, &state.cpu.X,            1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_Y_            + i, &state.cpu.Y,            1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_SP_           + i, &state.cpu.SP,           1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_PC_           + i, &state.cpu.PC,           sizeof(uint16_t), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_P_            + i, &state.cpu.P,            1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_total_cycles_ + i, &state.cpu.total_cycles, sizeof(uint64_t), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_nmi_pending_  + i, &state.cpu.nmi_pending,  1,                cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_cpu_irq_pending_  + i, &state.cpu.irq_pending,  1,                cudaMemcpyHostToDevice));

    // PPU scalars
    CUDA_CHECK(cudaMemcpy(d_ppu_ctrl_        + i, &state.ppu.ctrl,        1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_mask_        + i, &state.ppu.mask,        1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_status_      + i, &state.ppu.status,      1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_oam_addr_    + i, &state.ppu.oam_addr,    1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_v_           + i, &state.ppu.v,           sizeof(uint16_t), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_t_           + i, &state.ppu.t,           sizeof(uint16_t), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_fine_x_      + i, &state.ppu.fine_x,      1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_w_           + i, &state.ppu.w,           1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_read_buffer_ + i, &state.ppu.read_buffer, 1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_mirroring_   + i, &state.ppu.mirroring,   1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_scanline_    + i, &state.ppu.scanline,    sizeof(int),    cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_cycle_       + i, &state.ppu.cycle,       sizeof(int),    cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_frame_ready_ + i, &state.ppu.frame_ready, 1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_nmi_flag_    + i, &state.ppu.nmi_flag,    1,              cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_ppu_active_sprite_count_ + i, &state.ppu.active_sprite_count, sizeof(int), cudaMemcpyHostToDevice));
    // Note: array data (ram, vram, oam) are not transferred by set_state.
    // To transfer array data, use separate array-level accessors or re-run reset.
}
