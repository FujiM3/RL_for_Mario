# Phase 4 Work Log 003 — Framebuffer Pointer Optimization Analysis

**Date**: 2026-04-27  
**Task**: Move framebuffer from inline NESState array → external pointer to reduce state size

---

## Optimization Goal

| Metric | Before | After |
|--------|--------|-------|
| NESState size | 65,944 bytes (~64 KB) | 4,504 bytes (~4.5 KB) |
| 1000 instances state mem | ~64 MB >> V100 L2 (6 MB) | ~4.5 MB < V100 L2 (6 MB) |
| Framebuffer pool (1000) | inline in state | separate 60 MB pool |

**Hypothesis**: With states fitting in V100 L2 cache, repeated state accesses (CPU/PPU registers,
counters, nametables) during frame simulation would get L2 hits → lower latency → higher SPS.

---

## Implementation

### Key Changes
- `nes_state.h`: `uint8_t framebuffer[61440]` → `uint8_t* framebuffer` (8-byte pointer)
- `ppu_device.cuh::ppu_reset`: removed inline zero loop, replaced with `ppu->framebuffer = nullptr`
- `nes_frame_kernel.cu`: `nes_run_frame/nes_step_frames` accept `uint8_t* framebuf` param; set pointer before frame
- `nes_batch_kernel.cu`: batch kernels accept `uint8_t* fb_pool`; each instance sets `fb_pool + idx * 61440`
- `nes_gpu.cu/nes_batch_gpu.cu`: allocate separate framebuffer pools; pass to kernels

### Bug Fixed
`ppu_reset` was zeroing through the pointer with `ppu->framebuffer[i] = 0` after `cudaMemset(state, 0)` 
left `framebuffer = nullptr`. Fixed by setting `ppu->framebuffer = nullptr` instead.

---

## Benchmark Results

### Before optimization (baseline)
| Instances | SPS    | Speedup |
|-----------|--------|---------|
| 1,000     | 25-27k | 99-107× |
| 2,000     | 41-43k | 164-171× |
| 5,000     | 48-49k | 191-196× |

### After pointer optimization
| Instances | SPS    | Speedup |
|-----------|--------|---------|
| 1,000     | 24-26k | 95-104× |
| 2,000     | 38-40k | 152-161× |
| 5,000     | 44-47k | 176-187× |

---

## Analysis

**Result: ~5-10% performance regression**, counter to the hypothesis.

### Why the optimization didn't help (or hurt):

1. **GPU streaming is already efficient**: Each thread processes one NES instance sequentially.
   The GPU's memory coalescing and prefetching handles large sequential state access well,
   even when states are 64 KB apart. L2 thrashing is less of a problem than on CPU.

2. **Pointer indirection adds overhead**: Every `ppu->framebuffer[y*256 + x]` now requires:
   - Load pointer `ppu->framebuffer` (from state, now in L2 — fast)
   - Access `framebuffer[offset]` (from fb_pool — global memory)
   vs. old: compute inline address directly (single load from state)
   
   The old code could compute the framebuffer address as `&state.ppu.framebuffer[offset]` 
   with a single base pointer + constant offset. The new code adds a pointer load.

3. **Framebuffer dominates memory bandwidth**: PPU writes ~61K bytes per frame to framebuffer.
   Framebuffer access is the bottleneck regardless of where it lives — it's always global memory.

4. **L2 state benefit is offset**: The state fits in L2 (~4.5 MB for 1000 instances), 
   but since the workload is compute-bound (CPU/PPU simulation), not state-access-bound,
   the cache improvement is smaller than expected.

### Conclusion

The pointer optimization is **architecturally sound** (smaller state, cleaner design) but does not
improve throughput. The performance target (120×) is achieved at 2000+ instances regardless.

Kept as-is since:
- Tests all pass (18/18)
- Code is cleaner (state is smaller, framebuffer allocation is explicit)
- No correctness issues
- Performance still exceeds 120× target at 2000+ instances

---

## Test Status

```
nes_gpu_tests:       10/10 PASSED ✅
nes_gpu_batch_tests:  8/8  PASSED ✅
Total:               18/18 PASSED ✅
```
