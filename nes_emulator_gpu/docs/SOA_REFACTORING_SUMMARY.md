# SoA Refactoring Summary (Phase 5)

## Overview

Phase 5 refactored the batch NES emulator from **Array-of-Structures (AoS)** to
**Structure-of-Arrays (SoA)** memory layout. This is a classical GPU optimization
that exploits coalesced memory access — when 32 threads in a warp access the same
field of 32 different NES instances, those 32 values must be contiguous in memory
for the hardware to load them in a single cache-line transaction.

## Problem: AoS Memory Layout (Phase 4)

**Old layout:**
```
NESState states[N];   // 4504 bytes per struct
// states[0].ppu.cycle at offset 0
// states[1].ppu.cycle at offset 4504
// states[31].ppu.cycle at offset 31 × 4504 = 139,624
```

When 32 threads each access `states[idx].ppu.cycle`:
- Thread 0 loads from address `A`
- Thread 1 loads from address `A + 4504`
- Thread 31 loads from address `A + 31 × 4504 = A + 139,624`
- Span: **139 KB** → **32 separate cache-line transactions** (32× bandwidth waste)
- Warp utilization: ~3% (each transaction serves only 1 of 32 threads)
- This forced `<<<N, 1>>>` (one instance per block) to avoid performance collapse

## Solution: SoA Memory Layout (Phase 5)

**New layout:**
```c
struct NESBatchStatesSoA {
    int*     ppu_cycle[N];   // All cycle values contiguous
    int*     ppu_scanline[N];
    uint8_t* cpu_A[N];
    // ... 25 separate scalar arrays
    uint8_t* cpu_ram;        // [N × 2048] AoS-within-batch (random access anyway)
    uint8_t* ppu_vram;       // [N × 2048]
    // ...
};
```

When 32 threads each access `soa->ppu_cycle[idx]`:
- All 32 values at `soa->ppu_cycle + idx * 4`
- Contiguous span: **128 bytes = 1 cache line = 1 transaction**
- Warp utilization: **100%** (all 32 threads served in 1 transaction)
- Enables `<<<ceil(N/32), 32>>>` (32 threads per block = full warp coalescing)

## Implementation Details

### Key Design: Load-Process-Store Pattern

Each kernel follows:
1. **Load** scalar fields from SoA into local `NESCPUState`/`NESPPUState` structs
2. **Set array pointers** from SoA backing arrays (no 2KB RAM copy!)
3. **Run frame** using existing `cpu_step`/`ppu_tick` device functions (unchanged)
4. **Store** scalar fields back to SoA
5. Array writes during frame go directly to SoA memory via pointers → no writeback needed

```cuda
__global__ void nes_batch_run_frame(NESBatchStatesSoA* soa, ...) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= soa->num_instances) return;

    NESCPUState cpu;
    NESPPUState ppu;
    soa_load_cpu(soa, idx, &cpu);   // Coalesced reads (1 transaction per field)
    soa_load_ppu(soa, idx, &ppu);   // cpu.ram = soa->cpu_ram + idx*2048 (ptr only)

    // ... run frame using cpu_step, ppu_tick ...

    soa_store_cpu(soa, idx, &cpu);  // Coalesced writes
    soa_store_ppu(soa, idx, &ppu);
}
```

### NESState Struct Shrinkage

| | Phase 4 (AoS) | Phase 5 (SoA) |
|--|--|--|
| `NESCPUState` | 2072B (includes `ram[2048]`) | ~40B (pointer + scalars) |
| `NESPPUState` | 2432B (includes vram/oam/palette embedded) | ~80B (pointers + scalars) |
| `NESState` | **4504B** | **~120B** |
| 1000 instances total | 4.4 MB | 0.1 MB (scalars only) |

### Large Arrays: AoS-Within-Batch (Intentional)

CPU RAM, PPU VRAM, OAM, palette are kept as AoS-within-batch:
- `cpu_ram`: instance `i`'s RAM at `cpu_ram + i*2048`
- These are accessed randomly (address-dependent instruction execution)
- AoS vs SoA doesn't help random-access patterns
- Separating them would waste memory bandwidth on transpose

### Block Size Change

| Phase | Grid | Block | Reason |
|-------|------|-------|--------|
| Phase 4 | `<<<N, 1>>>` | 1 thread | AoS: 32 threads = 32× bandwidth |
| Phase 5 | `<<<ceil(N/32), 32>>>` | 32 threads (1 warp) | SoA: 32 threads = 1 cache line |

### Files Modified

| File | Change |
|------|--------|
| `src/cuda/device/nes_state.h` | Embedded arrays → pointers (struct: 4504B → ~120B) |
| `src/cuda/device/nes_batch_states_soa.h` | **New**: SoA struct + `soa_load/store` helpers |
| `src/cuda/kernels/nes_batch_kernel.cu` | Rewritten: SoA + 32-thread blocks |
| `src/cuda/kernels/nes_frame_kernel.cu` | `nes_reset` takes explicit array ptrs + mirroring |
| `src/cuda/host/nes_batch_gpu.h` | SoA device member pointers, updated forward decls |
| `src/cuda/host/nes_batch_gpu.cu` | `alloc_soa()`, SoA struct build, updated launch configs |
| `src/cuda/host/nes_gpu.h/.cu` | Single-instance allocates separate array buffers |
| `tests/cuda/test_gpu_single.cu` | Allocate array buffers, new `nes_reset` signature |
| `benchmarks/bench_gpu_single.cu` | Same `nes_reset` signature update |

### Bug Fix: Mirroring Race Condition

**Before (Phase 4):**
```cpp
// Host: write mirroring via offsetof BEFORE kernel
cudaMemcpy(d_state + offsetof(NESState, ppu.mirroring), &mir, 1, ...);
// Kernel: always overwrote with MIRROR_HORIZONTAL
ppu_reset(&state->ppu);  // ppu_reset doesn't touch mirroring
state->ppu.mirroring = MIRROR_HORIZONTAL;  // BUG: always overwrote!
```

**After (Phase 5):**
```cuda
__global__ void nes_reset(..., uint8_t mirroring, ...) {
    ppu_reset(&state->ppu);
    state->ppu.mirroring = mirroring;  // Correct: uses kernel parameter
    cpu_reset(&state->cpu, ...);
}
```

## Performance Results

Tested on **Tesla V100-PCIE-32GB** (CC 7.0, 32 GB VRAM):

| Instances | SPS | Speedup vs nes_py (252 SPS) | Per-frame |
|-----------|-----|------------------------------|-----------|
| 100       | 3,121   | 12.4×   | 32ms |
| 500       | 15,600  | 61.9×   | 32ms |
| 1,000     | 31,215  | **123.9×** ✅ | 32ms |
| 2,000     | 62,389  | 247.6×  | 32ms |
| 5,000     | 146,972 | 583.2×  | 34ms |
| 10,000    | 246,250 | 977.2×  | 41ms |
| **20,000**| **290,933** | **1154.5×** 🏆 | 71ms |
| 40,000    | 118,261 | 469×    | 349ms (VRAM bandwidth saturated) |

**Phase 5 target: 120× @ 1000 instances → Achieved 123.9× ✅**

### Performance Analysis

**Why it saturates at ~20,000 instances:**
- Per-instance VRAM footprint:
  - `ppu_framebuffer`: 61,440 B (240×256 pixels)  
  - `cpu_ram`: 2,048 B
  - `ppu_vram`: 2,048 B
  - Other arrays: ~300 B
  - **Total ≈ 66 KB/instance**
- 20,000 × 66 KB = **1.32 GB active data** (approaching L2 cache limit)
- At 40,000 instances: 2.64 GB → constant cache misses → bandwidth saturation

**Why 1000–10000 is near-linear:**
- SoA scalar arrays: 100 B × 10,000 = 1 MB → fits in L2 cache
- Frame computation dominates (not memory bandwidth)
- Perfect warp utilization: 32 threads × coalesced loads = minimal traffic

## Theoretical Analysis

| Access Pattern | Phase 4 (AoS) | Phase 5 (SoA) |
|----------------|---------------|---------------|
| 32-thread scalar load | 32 cache lines (32× overhead) | 1 cache line (ideal) |
| Warp utilization | ~3% (1/32) | 100% |
| Struct span (32 threads) | 4504 × 32 = 144 KB | 120 × 32 = 3840 B |
| Block size | 1 (forced) | 32 (full warp) |

## Comparison with Phase 4

| Metric | Phase 4 | Phase 5 | Improvement |
|--------|---------|---------|-------------|
| Speedup @ 1000 inst | 99–104× | **123.9×** | +25% |
| Speedup @ 2000 inst | 157–162× | **247.6×** | +55% |
| Peak speedup | ~162× | **1154×** | 7.1× |
| Peak instances | ~2000 | ~20,000 | 10× |
| Block size | 1 | 32 | 32× warp util |
| State memory @ 1000 | 4.4 MB | 0.1 MB | 44× smaller |
