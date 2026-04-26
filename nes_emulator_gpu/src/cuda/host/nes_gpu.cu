/*
 * NES GPU Host Implementation - Phase 3
 *
 * Implements the NESGpu class (nes_gpu.h).
 * Handles device memory management, kernel launches, and framebuffer transfer.
 */

#include "host/nes_gpu.h"
#include "device/nes_state.h"

#include <cuda_runtime.h>
#include <cstring>
#include <cstdio>
#include <stdexcept>

// Forward declarations for kernels (defined in nes_frame_kernel.cu)
__global__ void nes_run_frame(NESState* state,
                               const uint8_t* prg_rom, uint32_t prg_size,
                               const uint8_t* chr_rom, uint32_t chr_size);

__global__ void nes_reset(NESState* state,
                           const uint8_t* prg_rom, uint32_t prg_size,
                           const uint8_t* chr_rom, uint32_t chr_size);

__global__ void nes_step_frames(NESState* state,
                                 const uint8_t* prg_rom, uint32_t prg_size,
                                 const uint8_t* chr_rom, uint32_t chr_size,
                                 int num_frames);

// Macro for CUDA error checking
#define CUDA_CHECK(x) cuda_check(static_cast<int>(x), __FILE__, __LINE__)

void NESGpu::cuda_check(int err, const char* file, int line) {
    if (err != 0) {  // cudaSuccess == 0
        char buf[256];
        snprintf(buf, sizeof(buf), "CUDA error %d at %s:%d: %s",
                 err, file, line, cudaGetErrorString((cudaError_t)err));
        throw std::runtime_error(buf);
    }
}

// ---------------------------------------------------------------------------
// Constructor / Destructor
// ---------------------------------------------------------------------------

NESGpu::NESGpu() {
    // Allocate host framebuffer (256×240 RGBA8888)
    h_framebuf_ = new uint32_t[NES_FRAMEBUFFER_SIZE];

    // Create CUDA timing events
    CUDA_CHECK(cudaEventCreate(reinterpret_cast<cudaEvent_t*>(&ev_start_)));
    CUDA_CHECK(cudaEventCreate(reinterpret_cast<cudaEvent_t*>(&ev_stop_)));
}

NESGpu::~NESGpu() {
    // Free device memory
    if (d_state_)   cudaFree(d_state_);
    if (d_prg_rom_) cudaFree(d_prg_rom_);
    if (d_chr_rom_) cudaFree(d_chr_rom_);
    if (d_framebuf_) cudaFree(d_framebuf_);

    // Free host memory
    delete[] h_framebuf_;

    // Destroy timing events
    if (ev_start_) cudaEventDestroy(reinterpret_cast<cudaEvent_t>(ev_start_));
    if (ev_stop_)  cudaEventDestroy(reinterpret_cast<cudaEvent_t>(ev_stop_));
}

// ---------------------------------------------------------------------------
// load_rom
// ---------------------------------------------------------------------------

void NESGpu::load_rom(const uint8_t* prg_rom, uint32_t prg_size,
                       const uint8_t* chr_rom, uint32_t chr_size,
                       uint8_t mirroring) {
    prg_size_  = prg_size;
    chr_size_  = chr_size;
    mirroring_ = mirroring;

    // Allocate and upload PRG ROM
    if (d_prg_rom_) { CUDA_CHECK(cudaFree(d_prg_rom_)); d_prg_rom_ = nullptr; }
    CUDA_CHECK(cudaMalloc(&d_prg_rom_, prg_size));
    CUDA_CHECK(cudaMemcpy(d_prg_rom_, prg_rom, prg_size, cudaMemcpyHostToDevice));

    // Allocate and upload CHR ROM (may be empty for CHR RAM games)
    if (d_chr_rom_) { CUDA_CHECK(cudaFree(d_chr_rom_)); d_chr_rom_ = nullptr; }
    if (chr_size > 0 && chr_rom != nullptr) {
        CUDA_CHECK(cudaMalloc(&d_chr_rom_, chr_size));
        CUDA_CHECK(cudaMemcpy(d_chr_rom_, chr_rom, chr_size, cudaMemcpyHostToDevice));
    }

    // Allocate NES state
    if (d_state_) { CUDA_CHECK(cudaFree(d_state_)); d_state_ = nullptr; }
    CUDA_CHECK(cudaMalloc(&d_state_, sizeof(NESState)));
    CUDA_CHECK(cudaMemset(d_state_, 0, sizeof(NESState)));

    // Allocate device framebuffer copy target
    if (d_framebuf_) { CUDA_CHECK(cudaFree(d_framebuf_)); d_framebuf_ = nullptr; }
    CUDA_CHECK(cudaMalloc(&d_framebuf_, NES_FRAMEBUFFER_SIZE * sizeof(uint32_t)));

    loaded_ = true;
    reset_done_ = false;
}

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

void NESGpu::reset() {
    if (!loaded_) throw std::runtime_error("NESGpu::reset() called before load_rom()");

    // Set mirroring in device state before reset kernel runs
    // We do this by directly writing the mirroring field
    // Offset of ppu within NESState = sizeof(NESCPUState)
    uint8_t mir = mirroring_;
    size_t ppu_offset = offsetof(NESState, ppu);
    size_t mirror_offset = ppu_offset + offsetof(NESPPUState, mirroring);
    CUDA_CHECK(cudaMemcpy(reinterpret_cast<uint8_t*>(d_state_) + mirror_offset,
                          &mir, 1, cudaMemcpyHostToDevice));

    nes_reset<<<1, 1>>>(d_state_, d_prg_rom_, prg_size_, d_chr_rom_, chr_size_);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    reset_done_ = true;
}

// ---------------------------------------------------------------------------
// run_frame
// ---------------------------------------------------------------------------

void NESGpu::run_frame() {
    if (!reset_done_) throw std::runtime_error("NESGpu::run_frame() called before reset()");

    cudaEventRecord(reinterpret_cast<cudaEvent_t>(ev_start_));

    nes_run_frame<<<1, 1>>>(d_state_, d_prg_rom_, prg_size_, d_chr_rom_, chr_size_);
    CUDA_CHECK(cudaGetLastError());

    cudaEventRecord(reinterpret_cast<cudaEvent_t>(ev_stop_));
    CUDA_CHECK(cudaDeviceSynchronize());

    cudaEventElapsedTime(&last_frame_ms_,
                         reinterpret_cast<cudaEvent_t>(ev_start_),
                         reinterpret_cast<cudaEvent_t>(ev_stop_));
}

// ---------------------------------------------------------------------------
// run_frames (benchmark-friendly: no host/device sync between frames)
// ---------------------------------------------------------------------------

void NESGpu::run_frames(int n) {
    if (!reset_done_) throw std::runtime_error("NESGpu::run_frames() called before reset()");

    cudaEventRecord(reinterpret_cast<cudaEvent_t>(ev_start_));

    nes_step_frames<<<1, 1>>>(d_state_, d_prg_rom_, prg_size_, d_chr_rom_, chr_size_, n);
    CUDA_CHECK(cudaGetLastError());

    cudaEventRecord(reinterpret_cast<cudaEvent_t>(ev_stop_));
    CUDA_CHECK(cudaDeviceSynchronize());

    cudaEventElapsedTime(&last_frame_ms_,
                         reinterpret_cast<cudaEvent_t>(ev_start_),
                         reinterpret_cast<cudaEvent_t>(ev_stop_));
    last_frame_ms_ /= (float)n;  // Average per frame
}

// ---------------------------------------------------------------------------
// get_framebuffer
// ---------------------------------------------------------------------------

const uint32_t* NESGpu::get_framebuffer() {
    if (!d_state_) return nullptr;

    // Copy framebuffer from device NESState directly
    size_t ppu_offset = offsetof(NESState, ppu);
    size_t fb_offset = ppu_offset + offsetof(NESPPUState, framebuffer);

    CUDA_CHECK(cudaMemcpy(h_framebuf_,
                          reinterpret_cast<const uint8_t*>(d_state_) + fb_offset,
                          NES_FRAMEBUFFER_SIZE * sizeof(uint32_t),
                          cudaMemcpyDeviceToHost));
    return h_framebuf_;
}
