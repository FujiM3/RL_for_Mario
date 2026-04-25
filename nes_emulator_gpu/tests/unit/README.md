# NES GPU模拟器 - 单元测试

本目录包含单元测试程序。

## 测试列表

### test_cuda.cu
CUDA环境验证测试，确保GPU编译和运行正常。

**编译运行**:
```bash
nvcc test_cuda.cu -o test_cuda
./test_cuda
```

**预期输出**:
```
=== CUDA Environment Test ===
Device: Tesla V100-PCIE-32GB
Compute Capability: 7.0
...
✅ CUDA test passed!
```

---

## Phase 1测试 (待添加)

- `test_cpu_registers.c` - 6502寄存器测试
- `test_addressing_modes.c` - 13种寻址模式测试
- `test_instructions.c` - 所有指令测试
- ...

---

## 运行所有测试

```bash
# 编译所有测试
make tests

# 运行所有测试
make test

# 运行特定测试
./test_cuda
./test_cpu_registers
```
