# Phase 4 Work Log 001 - GPU Batch Parallel (Initial Implementation)

## Goal
Run N independent NES instances in parallel on the GPU. One CUDA block per instance, one thread per block (preserves Phase 3 correctness).

## Files Created

| File | Purpose |
|------|---------|
| `src/cuda/kernels/nes_batch_kernel.cu` | Batch kernels: nes_batch_run_frame, nes_batch_reset, nes_batch_step_frames, nes_batch_get_framebuffers |
| `src/cuda/host/nes_batch_gpu.h` | NESBatchGpu host class declaration |
| `src/cuda/host/nes_batch_gpu.cu` | NESBatchGpu implementation |
| `tests/cuda/test_gpu_batch.cu` | 8 batch GPU integration tests |
| `benchmarks/bench_gpu_batch.cu` | Batch benchmark with scaling sweep |

## Test Results

**8/8 GPU batch tests passing:**
```
[ PASSED ] 8 tests
  - CreateBatchOf100 ✅
  - LoadRomAndResetAll ✅
  - AllInstancesResetToPCVector ✅
  - RunOneFrameAllInstances ✅
  - AllInstancesProduceSameFramebuffer ✅
  - VBlankSetAfterFrame ✅
  - SetStateDifferentiatesInstances ✅
  - Batch1000InstancesRunFrame ✅
```

## Benchmark Results (Tesla V100-PCIE-32GB)

```
=== 1000 Instances, 300 Frames Each ===
  Batched execution:  23,343 SPS  (92.6× vs nes_py 252 SPS)
  Per-frame launches: 26,061 SPS (103.4× vs nes_py 252 SPS)
  Target:             30,240 SPS (120×)
  Status: ❌ 77% of target

Scaling sweep (300 frames):
  1 instance:    28 SPS   (0.1×)
  10 instances:  276 SPS  (1.1×)
  50 instances:  1,378 SPS (5.5×)
  100 instances: 2,756 SPS (10.9×)
  250 instances: 6,870 SPS (27.3×)
  500 instances: 13,588 SPS (53.9×)
  1000 instances: 23,404 SPS (92.9×)
```

## Bottleneck Analysis

**Root cause: Framebuffer dominates memory per instance.**

```
NESState size: 244 KB per instance
  - Framebuffer: 240×256×4 = 245,760 bytes (240 KB) = 98% of state
  - CPU state: ~2 KB
  - PPU state (non-FB): ~2 KB

1000 instances × 244 KB = 244 MB total device memory used for NES states
```

With 1000 parallel GPU threads, each thread has 244KB of data to read/write:
- **Memory bandwidth**: V100 has 900 GB/s peak; with 1000 threads × 244KB active = 244MB per frame
  - At 35ms/frame, active bandwidth = 244MB / 0.035s ≈ 7 GB/s (just 0.8% of V100 peak!)
  - But L2 cache is only 6MB — state doesn't fit in cache → global memory latency dominates
- **warp divergence**: 1000 threads, each doing different NES opcodes per cycle
  - V100 warp size = 32; 1000 instances = 32 warps
  - Each warp has 32 NES instances likely at different PC values → severe divergence in CPU opcode switch

## Key Optimization Opportunities for Phase 4 Cont.

### 1. Reduce Framebuffer from uint32_t to uint8_t (palette index)
- Current: 240×256×4 = 240KB per instance
- After: 240×256×1 = 60KB per instance → 4× state reduction
- 1000 instances: 244MB → 62MB
- Impact: ~4× less memory pressure → significantly better cache utilization

### 2. Increase Instance Count
- With 60KB state, we can fit more instances in GPU cache
- Try 2000-4000 instances for better GPU utilization

### 3. SoA (Structure of Arrays) Memory Layout
- Current: AoS layout → poor coalescing when accessing same field across instances
- SoA: all CPU.A values together, all CPU.X values together, etc.
- Better memory coalescing for batch operations

### 4. Shared Memory for Read-Only Data
- CHR ROM (8KB) + PRG ROM (16KB) = 24KB per SM
- V100 has 64KB shared memory per SM
- Store CHR ROM in shared memory for warp-level sharing

## Phase 4 Status: Baseline Complete

The basic parallelization works and achieves 92-103×. Reaching 120× requires the framebuffer optimization above.
