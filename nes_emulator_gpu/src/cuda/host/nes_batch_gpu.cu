/*
 * NES Batch GPU Implementation - Phase 4
 */

#include "nes_batch_gpu.h"
#include <cuda_runtime.h>
#include <cstring>
#include <stdexcept>
#include <string>

#define CUDA_CHECK(x) do { \
    cudaError_t e = (x); \
    if (e != cudaSuccess) { \
        throw std::runtime_error(std::string("CUDA error: ") + cudaGetErrorString(e)); \
    } \
} while(0)

// ---------------------------------------------------------------------------
// Constructor / Destructor
// ---------------------------------------------------------------------------

NESBatchGpu::NESBatchGpu(int num_instances)
    : num_instances_(num_instances) {
    if (num_instances <= 0 || num_instances > 65536) {
        throw std::invalid_argument("num_instances must be 1–65536");
    }

    CUDA_CHECK(cudaMalloc(&d_states_, sizeof(NESState) * num_instances_));
    CUDA_CHECK(cudaMemset(d_states_, 0, sizeof(NESState) * num_instances_));

    // Separate palette-index framebuffer pool (60KB per instance)
    size_t fb_palette_total = (size_t)num_instances_ * NES_FRAMEBUFFER_SIZE;
    CUDA_CHECK(cudaMalloc(&d_fb_pool_, fb_palette_total));

    // RGBA32 output buffer (used by get_framebuffers)
    size_t fb_out_total = (size_t)num_instances_ * NES_FRAMEBUFFER_SIZE * sizeof(uint32_t);
    CUDA_CHECK(cudaMalloc(&d_fb_out_, fb_out_total));
}

NESBatchGpu::~NESBatchGpu() {
    if (d_states_)  cudaFree(d_states_);
    if (d_prg_)     cudaFree(d_prg_);
    if (d_chr_)     cudaFree(d_chr_);
    if (d_fb_pool_) cudaFree(d_fb_pool_);
    if (d_fb_out_)  cudaFree(d_fb_out_);
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

    // Launch reset kernel for all instances in parallel
    nes_batch_reset<<<num_instances_, 1>>>(
        d_states_, d_prg_, prg_size_, d_chr_, chr_size_, num_instances_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    // Set mirroring for all instances via host memset pattern
    // Use cudaMemcpy2D to write the mirroring byte to the right offset in each state
    if (mirroring != MIRROR_HORIZONTAL) {
        size_t mirror_offset = offsetof(NESState, ppu) + offsetof(NESPPUState, mirroring);
        for (int i = 0; i < num_instances_; i++) {
            CUDA_CHECK(cudaMemcpy(
                reinterpret_cast<uint8_t*>(d_states_ + i) + mirror_offset,
                &mirroring, 1, cudaMemcpyHostToDevice));
        }
    }
}

// ---------------------------------------------------------------------------
// run_frame_all
// ---------------------------------------------------------------------------

void NESBatchGpu::run_frame_all() {
    nes_batch_run_frame<<<num_instances_, 1>>>(
        d_states_, d_prg_, prg_size_, d_chr_, chr_size_, num_instances_, d_fb_pool_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());
}

// ---------------------------------------------------------------------------
// run_frames_all (no sync between frames for benchmarking)
// ---------------------------------------------------------------------------

void NESBatchGpu::run_frames_all(int num_frames) {
    nes_batch_step_frames<<<num_instances_, 1>>>(
        d_states_, d_prg_, prg_size_, d_chr_, chr_size_, num_instances_, num_frames,
        d_fb_pool_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());
}

// ---------------------------------------------------------------------------
// get_framebuffers
// ---------------------------------------------------------------------------

void NESBatchGpu::get_framebuffers(uint32_t* host_output) {
    // Launch: one block per instance, 256 threads per block (one per pixel column)
    nes_batch_get_framebuffers<<<num_instances_, 256>>>(
        d_states_, d_fb_out_, num_instances_, d_fb_pool_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    size_t fb_total = (size_t)num_instances_ * NES_FRAMEBUFFER_SIZE * sizeof(uint32_t);
    CUDA_CHECK(cudaMemcpy(host_output, d_fb_out_, fb_total, cudaMemcpyDeviceToHost));
}

// ---------------------------------------------------------------------------
// get_state / set_state
// ---------------------------------------------------------------------------

void NESBatchGpu::get_state(int instance_idx, NESState& out) const {
    if (instance_idx < 0 || instance_idx >= num_instances_) {
        throw std::out_of_range("instance_idx out of range");
    }
    CUDA_CHECK(cudaMemcpy(&out, d_states_ + instance_idx,
                          sizeof(NESState), cudaMemcpyDeviceToHost));
}

void NESBatchGpu::set_state(int instance_idx, const NESState& state) {
    if (instance_idx < 0 || instance_idx >= num_instances_) {
        throw std::out_of_range("instance_idx out of range");
    }
    CUDA_CHECK(cudaMemcpy(d_states_ + instance_idx, &state,
                          sizeof(NESState), cudaMemcpyHostToDevice));
}
