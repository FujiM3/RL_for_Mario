/*
 * GPU Single Instance Benchmark - Phase 3
 *
 * Measures frames-per-second for one NES instance running on GPU.
 * Reports speedup vs CPU baseline (nes_py = 252 sps).
 *
 * Expected results for Phase 3 (single instance, 1 GPU thread):
 *   - Likely SLOWER than CPU due to GPU launch overhead
 *   - Proves correctness of the port before Phase 4 scaling
 *
 * Phase 4 target (1000 parallel instances):
 *   - Conservative: 30,000 sps (120× speedup)
 *   - Optimistic:  120,000 sps (480× speedup)
 */

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <vector>

#include "device/nes_state.h"
// Device functions are in nes_gpu_lib; only nes_state.h needed for struct types.

// Forward declarations for kernels
__global__ void nes_run_frame(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t, uint8_t*);
__global__ void nes_reset(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t);
__global__ void nes_step_frames(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t, int, uint8_t*);

// ---------------------------------------------------------------------------
// Build minimal test ROM (same as in test_gpu_single.cu)
// ---------------------------------------------------------------------------
static std::vector<uint8_t> make_bench_prg_rom() {
    std::vector<uint8_t> prg(0x4000, 0xEA);

    uint8_t code[] = {
        0x78,
        0xA9, 0x90, 0x8D, 0x00, 0x20,
        0xA9, 0x1E, 0x8D, 0x01, 0x20,
        0x58,
        0x4C, 0x0C, 0x80,
    };
    for (size_t i = 0; i < sizeof(code); i++) prg[i] = code[i];

    uint16_t nmi_handler = 0x0100;
    prg[nmi_handler] = 0x40;  // RTI

    uint16_t reset_addr = 0x8000;
    uint16_t nmi_addr   = 0x8100;
    prg[0x3FFA] = (uint8_t)(nmi_addr & 0xFF);
    prg[0x3FFB] = (uint8_t)(nmi_addr >> 8);
    prg[0x3FFC] = (uint8_t)(reset_addr & 0xFF);
    prg[0x3FFD] = (uint8_t)(reset_addr >> 8);
    prg[0x3FFE] = 0x00;
    prg[0x3FFF] = 0x80;

    return prg;
}

static std::vector<uint8_t> make_bench_chr_rom() {
    std::vector<uint8_t> chr(0x2000, 0xAA);
    return chr;
}

// ---------------------------------------------------------------------------
// CUDA error check helper
// ---------------------------------------------------------------------------
#define CUDA_CHECK(x) do { \
    cudaError_t e = (x); \
    if (e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(e)); \
        exit(1); \
    } \
} while(0)

// ---------------------------------------------------------------------------
// Main benchmark
// ---------------------------------------------------------------------------
int main(int argc, char** argv) {
    // Parse args
    int num_frames = 600;   // Default: 10 seconds at 60fps
    if (argc > 1) num_frames = atoi(argv[1]);

    // Select GPU
    int dev_count = 0;
    CUDA_CHECK(cudaGetDeviceCount(&dev_count));
    if (dev_count == 0) {
        fprintf(stderr, "No CUDA devices found.\n");
        return 1;
    }

    cudaDeviceProp prop;
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0));
    printf("=== NES GPU Single Instance Benchmark ===\n");
    printf("Device: %s (CC %d.%d, %zu MB VRAM)\n",
           prop.name, prop.major, prop.minor,
           prop.totalGlobalMem / (1024*1024));
    printf("Frames: %d\n\n", num_frames);

    // Build ROM
    auto prg_rom = make_bench_prg_rom();
    auto chr_rom = make_bench_chr_rom();

    // Allocate device memory
    NESState* d_state;
    uint8_t*  d_prg;
    uint8_t*  d_chr;
    uint8_t*  d_fb;

    CUDA_CHECK(cudaMalloc(&d_state, sizeof(NESState)));
    CUDA_CHECK(cudaMemset(d_state, 0, sizeof(NESState)));
    CUDA_CHECK(cudaMalloc(&d_prg, prg_rom.size()));
    CUDA_CHECK(cudaMalloc(&d_chr, chr_rom.size()));
    CUDA_CHECK(cudaMalloc(&d_fb, NES_FRAMEBUFFER_SIZE));
    CUDA_CHECK(cudaMemcpy(d_prg, prg_rom.data(), prg_rom.size(), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_chr, chr_rom.data(), chr_rom.size(), cudaMemcpyHostToDevice));

    // Set mirroring
    uint8_t mir = MIRROR_HORIZONTAL;
    size_t mirror_offset = offsetof(NESState, ppu) + offsetof(NESPPUState, mirroring);
    CUDA_CHECK(cudaMemcpy(reinterpret_cast<uint8_t*>(d_state) + mirror_offset,
                          &mir, 1, cudaMemcpyHostToDevice));

    // Reset
    nes_reset<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                         d_chr, (uint32_t)chr_rom.size());
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    // ---------------------------------------------------------------------------
    // Benchmark 1: Individual frame launches (includes launch overhead)
    // ---------------------------------------------------------------------------
    printf("--- Benchmark 1: Individual frame launches ---\n");

    cudaEvent_t t_start, t_stop;
    CUDA_CHECK(cudaEventCreate(&t_start));
    CUDA_CHECK(cudaEventCreate(&t_stop));

    CUDA_CHECK(cudaEventRecord(t_start));
    for (int i = 0; i < num_frames; i++) {
        nes_run_frame<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                                 d_chr, (uint32_t)chr_rom.size(), d_fb);
    }
    CUDA_CHECK(cudaEventRecord(t_stop));
    CUDA_CHECK(cudaDeviceSynchronize());
    CUDA_CHECK(cudaGetLastError());

    float elapsed_ms = 0;
    CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, t_start, t_stop));

    float elapsed_s = elapsed_ms / 1000.0f;
    float sps_individual = (float)num_frames / elapsed_s;

    printf("  Total time: %.2f ms for %d frames\n", elapsed_ms, num_frames);
    printf("  Per-frame:  %.3f ms\n", elapsed_ms / num_frames);
    printf("  SPS (samples/second): %.1f\n", sps_individual);
    printf("  Speedup vs nes_py (252 sps): %.2fx\n\n", sps_individual / 252.0f);

    // ---------------------------------------------------------------------------
    // Benchmark 2: Batched frames (no launch overhead between frames)
    // ---------------------------------------------------------------------------
    printf("--- Benchmark 2: Batched frame execution ---\n");

    // Reset again for consistent starting state
    nes_reset<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                         d_chr, (uint32_t)chr_rom.size());
    CUDA_CHECK(cudaDeviceSynchronize());
    CUDA_CHECK(cudaMemcpy(reinterpret_cast<uint8_t*>(d_state) + mirror_offset,
                          &mir, 1, cudaMemcpyHostToDevice));

    CUDA_CHECK(cudaEventRecord(t_start));
    nes_step_frames<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                               d_chr, (uint32_t)chr_rom.size(), num_frames, d_fb);
    CUDA_CHECK(cudaEventRecord(t_stop));
    CUDA_CHECK(cudaDeviceSynchronize());
    CUDA_CHECK(cudaGetLastError());

    float elapsed_batched_ms = 0;
    CUDA_CHECK(cudaEventElapsedTime(&elapsed_batched_ms, t_start, t_stop));

    float sps_batched = (float)num_frames / (elapsed_batched_ms / 1000.0f);

    printf("  Total time: %.2f ms for %d frames\n", elapsed_batched_ms, num_frames);
    printf("  Per-frame:  %.3f ms\n", elapsed_batched_ms / num_frames);
    printf("  SPS (samples/second): %.1f\n", sps_batched);
    printf("  Speedup vs nes_py (252 sps): %.2fx\n\n", sps_batched / 252.0f);

    // ---------------------------------------------------------------------------
    // Summary
    // ---------------------------------------------------------------------------
    printf("=== Summary ===\n");
    printf("Phase 3 (single instance, 1 GPU thread):\n");
    printf("  Launch-per-frame:   %.1f SPS  (%.2fx)\n",
           sps_individual, sps_individual / 252.0f);
    printf("  Batched execution:  %.1f SPS  (%.2fx)\n",
           sps_batched, sps_batched / 252.0f);
    printf("\nNote: Single instance is expected to be slower than CPU.\n");
    printf("Phase 4 target: 30,000 SPS (120x) with 1000 parallel instances.\n");

    // ---------------------------------------------------------------------------
    // Cleanup
    // ---------------------------------------------------------------------------
    cudaEventDestroy(t_start);
    cudaEventDestroy(t_stop);
    cudaFree(d_state);
    cudaFree(d_prg);
    cudaFree(d_chr);
    cudaFree(d_fb);

    return 0;
}
