# Phase 4 Work Log 002 - Framebuffer Optimization + Performance Results

## Goal
Reduce NESState memory footprint from 244KB → 64KB to improve GPU cache utilization and throughput.

## Optimization: uint8_t Framebuffer (Palette Index Storage)

**Problem:** 98% of NESState was the framebuffer (`uint32_t[61440]` = 240KB RGBA pixels).

**Solution:** Store palette indices (`uint8_t[61440]` = 60KB) during rendering. Convert to RGBA only at output time.

### Files Changed

| File | Change |
|------|--------|
| `src/cuda/device/nes_state.h` | `framebuffer` type: `uint32_t[61440]` → `uint8_t[61440]` |
| `src/cuda/device/ppu_device.cuh` | Added `ppu_get_background_palette_index()`, bg/sprite write palette index |
| `src/cuda/kernels/nes_frame_kernel.cu` | `nes_get_framebuffer` converts palette index → RGBA32 via `NES_PALETTE_CONST` |
| `src/cuda/kernels/nes_batch_kernel.cu` | `nes_batch_get_framebuffers` converts palette index → RGBA32 |
| `src/cuda/host/nes_gpu.cu` | `get_framebuffer()` now calls `nes_get_framebuffer` kernel instead of direct memcpy |
| `tests/cuda/test_gpu_single.cu` | `FramebufferNotAllBlack` updated to use `nes_get_framebuffer` kernel for RGBA check |

## State Size After Optimization

```
NESState:     65,944 bytes (~64 KB)
NESCPUState:   2,072 bytes
NESPPUState:  63,868 bytes
  framebuffer: 61,440 bytes (1 byte/pixel palette index)
```

**Before:** ~244KB → **After:** ~64KB (3.8× reduction)

## Test Results

All tests passing after optimization:
- Phase 3: **10/10 GPU single tests passing** ✅
- Phase 4: **8/8 GPU batch tests passing** ✅

## Benchmark Results

| Instances | SPS (batched) | SPS (per-frame) | Speedup vs nes_py |
|-----------|---------------|-----------------|-------------------|
| 1         | 29            | —               | 0.1×              |
| 100       | 2,834         | —               | 11.2×             |
| 500       | 14,153        | —               | 56.2×             |
| 1,000     | 24,980        | 27,089          | 99.1× / 107.5×    |
| 2,000     | 41,409        | 43,158          | **164.3× / 171.3×** |
| 5,000     | 48,263        | 49,422          | 191.5× / 196.1×   |
| 10,000    | 48,501        | 49,887          | 192.5× / 198.0×   |

**Peak throughput: ~50,000 SPS ≈ 198× speedup vs nes_py (252 SPS baseline)**
**Target (120×) achieved at ~1,200 instances. 2,000 instances yields 171×. Peak ~198×.**

## Performance Analysis

- 120× target exceeded at ~1,200 instances (memory bandwidth limited above)
- Peak performance ~198× at 5,000–10,000 instances
- V100 32GB VRAM supports up to ~460,000 instances (64KB each), but throughput saturates ~50k SPS
- Bottleneck at large scales: memory bandwidth (state too large for L2 at 1000+ instances)
- Further optimization options: eliminate framebuffer from state (store bitmask only), SoA layout

## Summary

Phase 4 complete. GPU batch emulator achieves:
- **10×–200× speedup** depending on batch size
- 120× target exceeded at ~1,200 instances
- Peak ~198× at 5,000+ instances
