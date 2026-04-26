# GPU性能剖析报告

**日期**: 2026-04-27  
**工具**: nvprof (API时间线) + nvcc --ptxas-options=-v (寄存器分析)  
**注**: 该服务器不允许硬件计数器访问 (ERR_NVGPUCTRPERM)，以下结论来自寄存器分析+理论计算+基准测试。

---

## 📊 寄存器使用分析

```
nvcc --ptxas-options=-v 输出：

nes_batch_run_frame:
  Used 32 registers, 0 bytes spill (stack=0, loads=0, stores=0)

nes_batch_step_frames:
  Used 32 registers, 0 bytes spill

nes_batch_reset:
  Used 14 registers, 0 bytes spill

nes_batch_get_framebuffers:
  Used 22 registers, 0 bytes spill
```

**结论**: 寄存器使用极低(32/255)，无寄存器溢出。寄存器**不是**性能瓶颈。

---

## 🔬 V100 SM占用率理论分析

V100规格: 80 SMs, 2048线程/SM, 64 warp/SM, 32块/SM, 65536寄存器/SM

### 不同Block Size下的占用率

| Block Size | Active线程/SM | Warp占用率 | Warp执行效率 | 合并访问 |
|-----------|-------------|-----------|------------|---------|
| 1 (当前)  | 32 (1.6%)   | 50%       | **3.1%**   | ✅ N/A  |
| 32        | 1,024 (50%) | 50%       | 100%       | ❌ 32×开销 |
| 64        | 2,048 (100%)| 100%      | 100%       | ❌ 32×开销 |
| 128       | 2,048 (100%)| 100%      | 100%       | ❌ 32×开销 |

### 关键发现：AoS布局下大Block Size适得其反

```
当warp中32个线程各自访问不同NESState（步长4504字节）时：

线程0: state[0].ppu.cycle   → 地址 A + 0×4504
线程1: state[1].ppu.cycle   → 地址 A + 1×4504
...
线程31: state[31].ppu.cycle → 地址 A + 31×4504

跨越范围: 31 × 4504 = 139,624 字节 >> 128字节 cache line
需要: 32次独立cache line加载 (vs 1次合并加载)
带宽开销: 32× 😱
```

**实测验证**: Block Size 1→128 导致 **2.4× 性能倒退** (25k→11k SPS)

---

## 📈 GPU饱和度分析

V100: 80 SMs × 32 blocks = **2,560个并发块**

| 实例数 | SM利用率 | 实测SPS | 加速比 |
|-------|---------|--------|--------|
| 500   | 20%     | 14,130 | 56×    |
| 1,000 | **39%** | 25,000 | 99×    |
| 2,000 | 78%     | 40,000 | 159×   |
| 2,560 | 100%    | ~44,000| ~175×  |
| 5,000 | 100%    | 46,000 | 183×   |
| 10,000| 100%    | 50,000 | 198×   |

**关键结论**: 1000实例时GPU仅39%饱和，5000+实例才能充分利用V100算力。

### 性能瓶颈：内存延迟 + GPU利用率

```
每个SM并发运行 ≤32 个块（各含1个NES实例）
每个"warp"只有1个活跃线程（31个slot闲置）
等效SM利用率: 39% (1000实例) × 3.1% (warp效率) ≈ 1.2% 理论利用率

但实际通过：多warp交织执行来隐藏内存延迟
→ 当一个块的线程等待内存时，调度另一个块
→ 32个并发warp提供足够的延迟隐藏
```

---

## ⏱️ API时间线分析 (nsys)

```
GPU活动占比（1000实例，10帧）：
  nes_batch_step_frames: 88.0%  (357ms avg per call)
  nes_batch_run_frame:   11.9%  (38ms avg per frame)
  nes_batch_reset:        0.1%  (0.1ms per reset)
  内存传输:               <0.1%

cudaDeviceSynchronize: 86% of CUDA API time (正常：GPU-bound工作负载)
cudaLaunchKernel: 2.3% of CUDA API time (kernel launch overhead可忽略)
```

**结论**: 99.9%时间在GPU计算，kernel launch overhead可忽略，无I/O瓶颈。

---

## 🎯 性能瓶颈总结

```
根本原因: Array-of-Structures (AoS) 状态布局 + 低GPU实例数

瓶颈层次:
1. 低实例数时 GPU SM未饱和 (1000实例=39% SM利用率)  ← 主要
2. AoS布局阻止多线程合并访问                        ← 架构限制  
3. NES顺序执行特性（指令间依赖链）                   ← 算法限制
```

---

## 🛣️ 优化路径

### 路径A: 增加环境数量（立即可用，推荐）
- 使用 **3000-5000 实例** 进行RL训练
- 性能: 170-190× speedup (超120×目标85-58%)
- 工作量: **0**（API已支持，改参数即可）

### 路径B: Structure-of-Arrays (SoA) 状态重构（高收益，高难度）
```
当前 AoS:
  state[0].ppu.cycle, state[1].ppu.cycle, ... (步长: 4504 bytes)

目标 SoA:
  ppu_cycles[0], ppu_cycles[1], ... (步长: 2 bytes, 完美合并!)

理论收益:
  - 支持 block size=32 → warp效率 100%
  - 支持共享内存缓存PRG ROM
  - 预计额外 50-100% 提升 @ 1000实例
  
工作量: 极大
  - 重构所有NESState/NESCPUState/NESPPUState为SoA
  - 修改所有设备函数参数签名
  - 重写所有状态访问模式
  - 估计: 200-500行代码变更 + 重新验证
```

### 路径C: 热点字段SoA（折中方案）
```
只将PPU内循环热点字段（cycle, scanline, mask, ctrl等~16字节）提取为SoA
其余字段保持AoS
理论收益: 30-50% @ 1000实例
工作量: 中等（100-200行）
```

---

## ✅ 当前状态与建议

| 目标 | 状态 | 建议 |
|------|------|------|
| 120× @ 1000实例 | ❌ 99-104× | 改用2000+实例 |
| 120× @ 2000实例 | ✅ 157-162× | **已满足** |
| 最大化吞吐量 | 198× @ 10000实例 | 生产RL用5000实例 |

**推荐配置**: RL训练用 **2048-4096 实例**，对应 155-180× 加速比。

---

## 📋 硬件限制说明

```
注: 该服务器不允许 nvprof --metrics 和 ncu (ERR_NVGPUCTRPERM)
以下指标无法直接测量:
  - achieved_occupancy (理论值: 50%)
  - global_load_efficiency (理论: ~3% AoS, ~100% SoA)
  - sm_efficiency (估计: ~40% @ 1000 inst)
  
建议: 在有权限的机器上运行 ncu --set=full 获得完整剖析数据。
```
