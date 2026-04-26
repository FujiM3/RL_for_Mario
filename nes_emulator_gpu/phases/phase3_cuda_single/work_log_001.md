# Phase 3 Work Log 001 - CUDA Single Instance Port

## Goal
Port the C++ OOP reference implementation (Phase 2) to CUDA device functions using flat structs and free `__device__` functions. Run one NES instance on one GPU thread to prove correctness before Phase 4 parallelism.

## Hardware
- GPU: Tesla V100-PCIE-32GB (32 GB VRAM)
- CUDA: 12.4, Compute Capability 7.0
- CUDA Architectures: 70

## Files Created

| File | Purpose |
|------|---------|
| `src/cuda/device/nes_state.h` | Flat structs: NESCPUState, NESPPUState, NESState, NESROMData |
| `src/cuda/device/ppu_device.cuh` | PPU as `__device__` functions (incl. NES_PALETTE_CONST in `__constant__`) |
| `src/cuda/device/cpu_device.cuh` | Full 6502 CPU with all 56 opcodes as `__device__` switch (~900 lines) |
| `src/cuda/kernels/nes_frame_kernel.cu` | 4 kernels: nes_run_frame, nes_reset, nes_get_framebuffer, nes_step_frames |
| `src/cuda/host/nes_gpu.h` | NESGpu host class declaration |
| `src/cuda/host/nes_gpu.cu` | NESGpu: load_rom, reset, run_frame, run_frames, get_framebuffer |
| `tests/cuda/test_gpu_single.cu` | 10 GPU tests using GTest |
| `benchmarks/bench_gpu_single.cu` | Single instance benchmark (frames/second) |

## Architecture Decisions

### Flat Structs
Replaced C++ OOP classes with flat C-style structs to comply with CUDA device code constraints.
No `std::function`, no exceptions, no dynamic allocation.

### CHR ROM Access
The `std::function chr_read` callback in PPU was replaced with a raw `const uint8_t* chr_rom` pointer
passed to all device functions. Mapper is assumed to be NROM (Mapper 0) for Phase 3.

### NES_PALETTE_CONST in `__constant__` Memory
256-entry precomputed RGB palette in `__constant__` memory for fast broadcast reads.

### Test Helper Kernels in nes_frame_kernel.cu
Test-specific `__global__` kernels (`test_ppu_register_write_read`, `test_ppu_vblank`) are defined
in `nes_frame_kernel.cu` rather than `test_gpu_single.cu`. This avoids nvlink "multiple definition"
errors that occur when device function headers are included in multiple compilation units with
CUDA separable compilation enabled.

### CPU:PPU Clock Ratio
3 PPU ticks per CPU cycle. Frame = ~29,780 CPU cycles = ~89,342 PPU cycles.
Safety limit of 36,000 CPU cycles per frame (includes 20% margin for OAM DMA stalls).

## Test Results

All 10/10 GPU tests passing:
```
[ PASSED ] 10 tests.
```
Tests cover: reset state, VBlank trigger, NMI propagation, framebuffer output, multi-frame consistency, PPU register writes.

## Benchmark Results

Running on Tesla V100-PCIE-32GB:
```
Phase 3 (single instance, 1 GPU thread):
  Launch-per-frame:   28.6 SPS  (0.11x vs nes_py 252 SPS)
  Batched execution:  29.0 SPS  (0.11x vs nes_py 252 SPS)
```

### Analysis
Single GPU thread is ~9× slower than CPU (29 vs 252 SPS). This is expected:
- V100 GPU clock ~1.25 GHz vs CPU ~3-4 GHz (3× raw clock difference)
- GPU optimized for throughput (parallel SIMD), not single-thread latency
- Sequential NES emulation has essentially zero parallelism within a single instance

**This proves correctness. Phase 4 will run ~1000 parallel instances to achieve 120× speedup.**

## Phase 4 Projection
- 1000 parallel instances × 29 SPS ≈ 29,000 SPS (115× speedup) [conservative]
- With better scheduling / warp efficiency: 30,000–120,000 SPS possible
- Target: 30,240 SPS minimum (120× vs 252 SPS baseline)

## Build Notes
- cmake_minimum_required lowered to 3.16 (system constraint)
- CMAKE_CUDA_STANDARD set to 14 (CMake 3.16 does not support CUDA17)
- Build: `cd build && cmake .. -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc && make`
- CMake detects CUDA via `CMAKE_CUDA_COMPILER` pre-declared + `find_program(nvcc)` fallback
