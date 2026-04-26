/*
 * GPU Batch Parallel Benchmark - Phase 4
 *
 * Measures frames/second for N NES instances running in parallel on GPU.
 * Reports speedup vs CPU baseline (nes_py = 252 sps).
 *
 * Usage: bench_gpu_batch [num_instances] [num_frames]
 *   Default: num_instances=1000, num_frames=300
 *
 * Phase 4 target: 30,240 SPS (120× vs nes_py)
 */

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "device/nes_state.h"
#include "host/nes_batch_gpu.h"

// ---------------------------------------------------------------------------
// Minimal synthetic ROM (same as bench_gpu_single.cu)
// ---------------------------------------------------------------------------
static std::vector<uint8_t> make_prg_rom() {
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
    prg[nmi_handler] = 0x40;
    prg[0x3FFA] = 0x00; prg[0x3FFB] = 0x81;  // NMI vector -> $8100
    prg[0x3FFC] = 0x00; prg[0x3FFD] = 0x80;  // RESET vector -> $8000
    prg[0x3FFE] = 0x00; prg[0x3FFF] = 0x80;
    return prg;
}

static std::vector<uint8_t> make_chr_rom() {
    return std::vector<uint8_t>(0x2000, 0xAA);
}

// ---------------------------------------------------------------------------
// Main benchmark
// ---------------------------------------------------------------------------
int main(int argc, char** argv) {
    int num_instances = 1000;
    int num_frames    = 300;
    if (argc > 1) num_instances = atoi(argv[1]);
    if (argc > 2) num_frames    = atoi(argv[2]);

    // Check CUDA
    int dev_count = 0;
    cudaGetDeviceCount(&dev_count);
    if (dev_count == 0) {
        fprintf(stderr, "No CUDA devices found.\n");
        return 1;
    }

    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);

    printf("=== NES GPU Batch Parallel Benchmark (Phase 4) ===\n");
    printf("Device:        %s (CC %d.%d, %zu MB VRAM)\n",
           prop.name, prop.major, prop.minor,
           prop.totalGlobalMem / (1024*1024));
    printf("Instances:     %d\n", num_instances);
    printf("Frames/inst:   %d\n", num_frames);
    printf("Total frames:  %d\n", num_instances * num_frames);

    size_t mem_per_instance = sizeof(NESState);
    size_t total_state_mem  = (size_t)num_instances * mem_per_instance;
    printf("State memory:  %.1f MB (%zu KB/instance)\n\n",
           total_state_mem / 1e6, mem_per_instance / 1024);

    auto prg_rom = make_prg_rom();
    auto chr_rom = make_chr_rom();

    // Create batch controller
    NESBatchGpu batch(num_instances);
    batch.load_rom(prg_rom.data(), (uint32_t)prg_rom.size(),
                   chr_rom.data(), (uint32_t)chr_rom.size());
    batch.reset_all(MIRROR_HORIZONTAL);

    // ---------------------------------------------------------------------------
    // Benchmark 1: run_frames_all (batched, no host/device sync between frames)
    // ---------------------------------------------------------------------------
    printf("--- Benchmark 1: Batched execution ---\n");

    cudaEvent_t t0, t1;
    cudaEventCreate(&t0);
    cudaEventCreate(&t1);

    cudaEventRecord(t0);
    batch.run_frames_all(num_frames);
    cudaEventRecord(t1);
    cudaEventSynchronize(t1);

    float ms_batched = 0;
    cudaEventElapsedTime(&ms_batched, t0, t1);

    // Total samples = num_instances × num_frames
    long long total_samples = (long long)num_instances * num_frames;
    float sps_batched = (float)total_samples / (ms_batched / 1000.0f);

    printf("  Total time:    %.2f ms\n", ms_batched);
    printf("  Total samples: %lld\n", total_samples);
    printf("  SPS:           %.0f\n", sps_batched);
    printf("  Speedup:       %.1fx vs nes_py (252 SPS)\n\n", sps_batched / 252.0f);

    // ---------------------------------------------------------------------------
    // Benchmark 2: Per-frame launches (includes launch overhead)
    // ---------------------------------------------------------------------------
    printf("--- Benchmark 2: Per-frame launches ---\n");

    batch.reset_all(MIRROR_HORIZONTAL);

    cudaEventRecord(t0);
    for (int f = 0; f < num_frames; f++) {
        batch.run_frame_all();
    }
    cudaEventRecord(t1);
    cudaEventSynchronize(t1);

    float ms_perframe = 0;
    cudaEventElapsedTime(&ms_perframe, t0, t1);
    float sps_perframe = (float)total_samples / (ms_perframe / 1000.0f);

    printf("  Total time:    %.2f ms\n", ms_perframe);
    printf("  Per frame:     %.3f ms\n", ms_perframe / num_frames);
    printf("  SPS:           %.0f\n", sps_perframe);
    printf("  Speedup:       %.1fx vs nes_py (252 SPS)\n\n", sps_perframe / 252.0f);

    // ---------------------------------------------------------------------------
    // Scaling sweep (1, 10, 100, 500, 1000, ... instances)
    // ---------------------------------------------------------------------------
    printf("--- Scaling sweep (%d frames each) ---\n", num_frames);
    printf("  %-12s %-10s %-10s %-10s\n", "Instances", "Time(ms)", "SPS", "Speedup");

    int sweep_counts[] = {1, 10, 50, 100, 250, 500, num_instances};
    int n_sweep = (int)(sizeof(sweep_counts) / sizeof(sweep_counts[0]));

    for (int si = 0; si < n_sweep; si++) {
        int n = sweep_counts[si];
        if (n > num_instances) continue;

        NESBatchGpu sweep_batch(n);
        sweep_batch.load_rom(prg_rom.data(), (uint32_t)prg_rom.size(),
                              chr_rom.data(), (uint32_t)chr_rom.size());
        sweep_batch.reset_all(MIRROR_HORIZONTAL);

        cudaEventRecord(t0);
        sweep_batch.run_frames_all(num_frames);
        cudaEventRecord(t1);
        cudaEventSynchronize(t1);

        float ms = 0;
        cudaEventElapsedTime(&ms, t0, t1);
        float sps = (float)n * num_frames / (ms / 1000.0f);

        printf("  %-12d %-10.1f %-10.0f %.1fx\n",
               n, ms, sps, sps / 252.0f);
    }

    // ---------------------------------------------------------------------------
    // Summary
    // ---------------------------------------------------------------------------
    printf("\n=== Summary (%d instances) ===\n", num_instances);
    printf("  Batched:   %.0f SPS  (%.1fx)\n", sps_batched, sps_batched / 252.0f);
    printf("  Per-frame: %.0f SPS  (%.1fx)\n", sps_perframe, sps_perframe / 252.0f);
    printf("  Target:    30,240 SPS (120x)\n");
    if (sps_batched >= 30240.0f) {
        printf("  STATUS: ✅ TARGET ACHIEVED!\n");
    } else {
        printf("  STATUS: ❌ below target (%.0f%% of goal)\n",
               100.0f * sps_batched / 30240.0f);
    }

    cudaEventDestroy(t0);
    cudaEventDestroy(t1);

    return 0;
}
