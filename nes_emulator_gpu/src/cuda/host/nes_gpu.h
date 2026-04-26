#pragma once

/*
 * NES GPU Host Interface - Phase 3
 *
 * C++ host-side wrapper around the CUDA kernel.
 * Manages device memory allocation, ROM transfer, kernel launch,
 * and framebuffer retrieval.
 *
 * Usage:
 *   NESGpu emu;
 *   emu.load_rom(prg_rom, prg_size, chr_rom, chr_size);
 *   emu.reset();
 *   emu.run_frame();
 *   auto* fb = emu.get_framebuffer();  // 256x240 RGBA pixels
 */

#include <cstdint>
#include <stdexcept>
#include <string>

// Forward declarations (avoid including CUDA headers in .h)
struct NESState;

class NESGpu {
public:
    NESGpu();
    ~NESGpu();

    // Disable copy/move (manages device resources)
    NESGpu(const NESGpu&) = delete;
    NESGpu& operator=(const NESGpu&) = delete;

    // Load ROM data into device memory.
    // Must be called before reset().
    // mirroring: 0=horizontal, 1=vertical, 2=single_A, 3=single_B
    void load_rom(const uint8_t* prg_rom, uint32_t prg_size,
                  const uint8_t* chr_rom, uint32_t chr_size,
                  uint8_t mirroring = 0);

    // Reset CPU and PPU (runs nes_reset kernel).
    void reset();

    // Run one complete frame (runs nes_run_frame kernel).
    // Returns the number of CPU cycles executed.
    void run_frame();

    // Run N frames back-to-back (no host<->device sync between frames).
    // Faster for benchmarking.
    void run_frames(int n);

    // Retrieve rendered framebuffer from device to host.
    // Returns pointer to 256×240 RGBA8888 pixels (host memory).
    // Pointer is valid until the next call to get_framebuffer() or destructor.
    const uint32_t* get_framebuffer();

    // Access raw device state pointer (for advanced use / testing)
    NESState* device_state() const { return d_state_; }

    // Get device pointers to ROM (for kernel launch in tests/benchmarks)
    const uint8_t* device_prg_rom() const { return d_prg_rom_; }
    const uint8_t* device_chr_rom() const { return d_chr_rom_; }
    uint32_t prg_size() const { return prg_size_; }
    uint32_t chr_size() const { return chr_size_; }
    uint8_t mirroring() const { return mirroring_; }

    // Performance: elapsed ms for last run_frame() call
    float last_frame_ms() const { return last_frame_ms_; }

private:
    void cuda_check(int err, const char* file, int line);

    NESState*  d_state_  = nullptr;    // Device: NES state (~250KB)
    uint8_t*   d_prg_rom_ = nullptr;   // Device: PRG ROM
    uint8_t*   d_chr_rom_ = nullptr;   // Device: CHR ROM
    uint32_t*  d_framebuf_ = nullptr;  // Device: temp framebuffer copy
    uint32_t*  h_framebuf_ = nullptr;  // Host:   framebuffer staging

    uint32_t prg_size_ = 0;
    uint32_t chr_size_ = 0;
    uint8_t  mirroring_ = 0;

    float last_frame_ms_ = 0.0f;

    bool loaded_ = false;
    bool reset_done_ = false;

    // CUDA events for timing
    void* ev_start_ = nullptr;
    void* ev_stop_  = nullptr;
};
