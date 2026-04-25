# GPU原型验证计划

**目标**: 在投入更多时间到Phase 2之前，验证GPU架构可行性  
**预计时间**: 3-5天  
**决策点**: 基于性能数据决定是否继续完整PPU实现

---

## 🎯 验证目标

### 核心问题
1. **并行效率**: 1000个NES实例在GPU上能达到多少sps？
2. **Warp divergence**: CPU指令的分支是否导致严重性能损失？
3. **内存带宽**: PPU渲染的随机访问是否成为瓶颈？
4. **架构选择**: 1 env = 1 warp还是1 block？

### 成功标准
- **最低目标**: >10,000 sps (40倍基线)
- **期望目标**: >30,000 sps (120倍基线)
- **理想目标**: >100,000 sps (400倍基线)

---

## 📋 实现步骤

### Day 1-2: 最小GPU NES实现

#### 阶段1: GPU CPU模拟器 (1天)
**文件**: `src/cuda/kernels/cpu_kernel.cu`

**实现内容**:
```cuda
// 每个warp处理1个NES实例
__global__ void nes_step_kernel(
    NESState* states,      // [num_envs]
    uint8_t* actions,      // [num_envs]
    float* rewards,        // [num_envs]
    bool* dones,           // [num_envs]
    int num_envs
) {
    int env_id = blockIdx.x * (blockDim.x / 32) + (threadIdx.x / 32);
    if (env_id >= num_envs) return;
    
    // 每个warp执行一个NES实例
    NESState* state = &states[env_id];
    
    // 执行CPU指令
    for (int i = 0; i < STEPS_PER_CALL; i++) {
        cpu_execute(state);
    }
    
    // 更新输出
    rewards[env_id] = calculate_reward(state);
    dones[env_id] = check_done(state);
}
```

**简化策略**:
- ✅ 保留: 6502 CPU完整实现 (已有)
- ✅ 保留: PPU timing + 寄存器 (已有)
- ❌ 跳过: PPU完整渲染 (用fake render)
- ❌ 跳过: APU音频

**测试目标**: 验证CPU在GPU上能跑

#### 阶段2: 最小PPU实现 (0.5天)
```cuda
__device__ void ppu_tick_minimal(PPUState* ppu) {
    // 仅timing + VBlank
    ppu->cycle++;
    if (ppu->cycle > 340) {
        ppu->cycle = 0;
        ppu->scanline++;
        
        if (ppu->scanline == 241) {
            ppu->vblank = true;
        } else if (ppu->scanline > 260) {
            ppu->scanline = 0;
        }
    }
}

__device__ void ppu_render_fake(PPUState* ppu, uint8_t* output) {
    // 选项A: 返回黑屏
    // memset(output, 0, 256*240);
    
    // 选项B: 返回VRAM原始数据 (for RL agent)
    // memcpy(output, ppu->vram, 2048);
    
    // 选项C: 简化tile map
    memcpy(output, ppu->vram, 960); // 32×30 nametable
}
```

#### 阶段3: Python接口 (0.5天)
**文件**: `src/python/nes_gpu_env.py`

```python
import torch
from typing import Tuple

class NESEnvGPU:
    def __init__(self, num_envs: int = 1000, device='cuda:0'):
        self.num_envs = num_envs
        self.device = device
        
        # Allocate GPU memory
        self.states = torch.empty((num_envs, STATE_SIZE), dtype=torch.uint8, device=device)
        self.rewards = torch.zeros(num_envs, dtype=torch.float32, device=device)
        self.dones = torch.zeros(num_envs, dtype=torch.bool, device=device)
        
        # Load CUDA kernel
        self._load_kernel()
    
    def step(self, actions: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # actions: [num_envs] on GPU
        self.kernel(self.states, actions, self.rewards, self.dones, self.num_envs)
        
        # Return obs (VRAM dump), rewards, dones
        obs = self.extract_observations()
        return obs, self.rewards, self.dones
    
    def reset(self, env_ids: torch.Tensor = None):
        if env_ids is None:
            env_ids = torch.arange(self.num_envs, device=self.device)
        # Reset specified envs
        self.reset_kernel(self.states, env_ids, len(env_ids))
```

---

### Day 3-4: 性能测试与分析

#### 测试1: 基准吞吐量
**目标**: 测量纯执行速度（无渲染）

```python
import time

env = NESEnvGPU(num_envs=1000)
actions = torch.randint(0, 8, (1000,), device='cuda')

# Warmup
for _ in range(100):
    env.step(actions)

# Benchmark
torch.cuda.synchronize()
start = time.time()
for _ in range(1000):
    env.step(actions)
torch.cuda.synchronize()
elapsed = time.time() - start

sps = (1000 * 1000) / elapsed
print(f"Steps/sec: {sps:.0f}")
```

**预期结果**:
- 无渲染: >100,000 sps ✅
- 简化渲染: >30,000 sps ✅
- 完整渲染: >10,000 sps ❓

#### 测试2: Profiling分析
**工具**: NVIDIA Nsight Compute

```bash
ncu --set full -o profile python benchmark.py
```

**关注指标**:
- Warp execution efficiency (目标 >70%)
- Branch efficiency (目标 >80%)
- Memory throughput (目标 <50% peak)
- Occupancy (目标 >60%)

#### 测试3: 扩展性测试
**目标**: 找到最优env数量

```python
for num_envs in [100, 500, 1000, 2000, 5000, 10000]:
    env = NESEnvGPU(num_envs=num_envs)
    sps = benchmark(env)
    print(f"{num_envs} envs: {sps:.0f} sps")
```

---

### Day 5: 决策与文档

#### 性能评估矩阵

| 场景 | SPS | 决策 |
|------|-----|------|
| >100K sps | 🎉 | 继续Phase 2完整实现 |
| 30K-100K sps | ✅ | 继续，但考虑简化渲染 |
| 10K-30K sps | ⚠️ | 重新评估架构 |
| <10K sps | ❌ | 考虑放弃GPU方案 |

#### 决策树

```
测试结果
    ├─ >30K sps
    │   ├─ Warp divergence <20%
    │   │   → 继续完整Phase 2实现
    │   └─ Warp divergence >20%
    │       → 优化CPU指令实现 (减少分支)
    │
    ├─ 10K-30K sps
    │   ├─ 瓶颈在PPU渲染
    │   │   → 简化PPU (fake render)
    │   └─ 瓶颈在CPU执行
    │       → 优化指令dispatch
    │
    └─ <10K sps
        → 考虑混合方案 (GPU训练 + CPU模拟)
```

---

## 🛠️ 技术细节

### GPU Memory Layout (SoA)

```cpp
struct NESStateGPU {
    // CPU State (per-env arrays)
    uint8_t* cpu_ram;        // [num_envs][2048]
    uint16_t* cpu_pc;        // [num_envs]
    uint8_t* cpu_a;          // [num_envs]
    uint8_t* cpu_x;          // [num_envs]
    uint8_t* cpu_y;          // [num_envs]
    uint8_t* cpu_sp;         // [num_envs]
    uint8_t* cpu_flags;      // [num_envs]
    
    // PPU State (minimal)
    uint8_t* ppu_vram;       // [num_envs][2048]
    uint8_t* ppu_oam;        // [num_envs][256]
    uint8_t* ppu_palette;    // [num_envs][32]
    uint8_t* ppu_ctrl;       // [num_envs]
    uint8_t* ppu_mask;       // [num_envs]
    uint16_t* ppu_scanline;  // [num_envs]
    uint16_t* ppu_cycle;     // [num_envs]
    
    // ROM (shared across all envs)
    uint8_t* prg_rom;        // [32KB] - shared
    uint8_t* chr_rom;        // [8KB] - shared
};
```

**内存计算**:
- 单env: ~5KB (RAM + VRAM + registers)
- 1000 envs: ~5MB
- ROM shared: 40KB
- Total: ~5MB (非常小！)

### Warp协作策略

```cuda
// 方案A: 每个warp独立执行一个NES
__device__ void cpu_execute_warp_solo(NESState* state, int lane_id) {
    if (lane_id == 0) {
        // Only lane 0 does work
        cpu_step(state);
    }
}
// Warp efficiency: ~3% (浪费31个线程)

// 方案B: warp内线程协作
__device__ void cpu_execute_warp_coop(NESState* state, int lane_id) {
    // 不同lane处理不同任务
    if (lane_id < 8) {
        // Lanes 0-7: 执行指令
        cpu_step_parallel(state, lane_id);
    } else if (lane_id < 16) {
        // Lanes 8-15: PPU渲染
        ppu_render_parallel(state, lane_id - 8);
    }
    __syncwarp();
}
// Warp efficiency: ~50%

// 方案C: 每个线程一个env (忽略warp概念)
__global__ void nes_step_thread_per_env(NESState* states, int num_envs) {
    int env_id = blockIdx.x * blockDim.x + threadIdx.x;
    if (env_id >= num_envs) return;
    
    cpu_step(&states[env_id]);
    ppu_tick(&states[env_id]);
}
// Warp efficiency: 100%, but branch divergence可能高
```

**推荐**: 先测试方案C (最简单), 然后优化

---

## 📊 预期成果

### 交付物
1. **代码**:
   - `src/cuda/kernels/cpu_kernel.cu` (~500行)
   - `src/python/nes_gpu_env.py` (~200行)
   - `benchmarks/gpu_prototype/benchmark.py` (~100行)

2. **性能报告**:
   - `docs/gpu_prototype_benchmark.md`
   - Nsight Compute profile截图
   - 性能-env数量曲线图

3. **架构决策**:
   - `docs/gpu_architecture_decision.md`
   - 是否继续Phase 2完整实现
   - 如果是，选择哪种并行策略

### 决策点
**如果GPU原型成功 (>30K sps)**:
→ 回到Phase 2，完成Task 2.3-2.6
→ 但可能调整渲染策略 (简化或可选)

**如果GPU原型失败 (<10K sps)**:
→ 重新评估项目目标
→ 考虑替代方案:
  - CPU多核 + 简化模拟器
  - GPU加速RL训练 (不加速模拟)
  - 混合方案

---

## 🎯 下一步行动

1. ✅ **今天**: 完成Task 2.2集成 ✅
2. ⏳ **明天**: 开始GPU原型实现
3. 📊 **3-5天后**: 性能评估 + 架构决策
4. 🔀 **基于数据**: 决定是否继续Phase 2

---

## 📚 参考资料

- [cuLE Source](https://github.com/NVlabs/cule) - Atari GPU模拟器
- [CUDA Best Practices](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/)
- [Nsight Compute Profiling](https://docs.nvidia.com/nsight-compute/)
- 我们的研究: `docs/gpu_emulator_research.md`
- 渲染分析: `docs/rendering_architecture_analysis.md`
