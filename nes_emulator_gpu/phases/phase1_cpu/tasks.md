# Phase 1 - 详细任务清单

**创建日期**: 2026-04-25  
**最后更新**: 2026-04-25

---

## 任务1.1: 6502寄存器和基础架构 (预计2-3天)

### 1.1.1 定义基础类型 ⏳
- [ ] 创建 `src/reference/common/types.h`
- [ ] 定义 uint8_t, uint16_t 别名
- [ ] 定义状态标志位枚举
- [ ] 创建 Makefile / CMakeLists.txt

**产出**: `types.h`, 编译系统

### 1.1.2 实现寄存器模型 ⏳
- [ ] 创建 `src/reference/cpu/registers.h`
- [ ] 实现:
  - [ ] A (累加器)
  - [ ] X, Y (索引寄存器)
  - [ ] SP (栈指针, 初始0xFD)
  - [ ] PC (程序计数器)
  - [ ] P (状态寄存器, 8个标志位)
- [ ] 实现标志位操作函数 (set/clear/test)

**产出**: `registers.h`, 单元测试

### 1.1.3 创建CPU类骨架 ⏳
- [ ] 创建 `src/reference/cpu/cpu_6502.h`
- [ ] 定义CPU类接口:
  - [ ] `reset()` - 复位
  - [ ] `step()` - 执行一条指令
  - [ ] `read(addr)` / `write(addr, data)` - 内存访问
  - [ ] `tick()` - CPU周期计数
- [ ] 创建 `src/reference/cpu/cpu_6502.cpp` 空实现

**产出**: CPU类框架

---

## 任务1.2: 寻址模式实现 (预计3-4天)

### 1.2.1 创建寻址模式框架 ⏳
- [ ] 创建 `src/reference/cpu/addressing.h`
- [ ] 定义寻址模式枚举
- [ ] 定义统一的寻址接口

### 1.2.2 实现13种寻址模式 ⏳
- [ ] **Implied** - 隐含寻址 (无操作数)
- [ ] **Accumulator** - 累加器寻址
- [ ] **Immediate** - 立即数寻址 `#$nn`
- [ ] **Zero Page** - 零页寻址 `$nn`
- [ ] **Zero Page, X** - 零页X索引 `$nn,X`
- [ ] **Zero Page, Y** - 零页Y索引 `$nn,Y`
- [ ] **Absolute** - 绝对寻址 `$nnnn`
- [ ] **Absolute, X** - 绝对X索引 `$nnnn,X`
- [ ] **Absolute, Y** - 绝对Y索引 `$nnnn,Y`
- [ ] **Relative** - 相对寻址 (分支指令)
- [ ] **Indirect** - 间接寻址 `($nnnn)` (JMP专用)
- [ ] **Indexed Indirect** - X索引间接 `($nn,X)`
- [ ] **Indirect Indexed** - 间接Y索引 `($nn),Y`

### 1.2.3 单元测试 ⏳
- [ ] 创建 `tests/unit/test_addressing_modes.cpp`
- [ ] 每种模式至少3个测试用例

**产出**: `addressing.h/cpp`, 单元测试

---

## 任务1.3: 指令实现 (预计7-10天)

### 1.3.1 加载/存储指令 ⏳
- [ ] LDA (Load Accumulator) - 5种寻址
- [ ] LDX (Load X) - 5种寻址
- [ ] LDY (Load Y) - 5种寻址
- [ ] STA (Store Accumulator) - 7种寻址
- [ ] STX (Store X) - 3种寻址
- [ ] STY (Store Y) - 3种寻址

### 1.3.2 传送指令 ⏳
- [ ] TAX, TAY, TXA, TYA
- [ ] TSX, TXS

### 1.3.3 算术指令 ⏳
- [ ] ADC (Add with Carry) - 8种寻址
  - [ ] 实现十进制模式 (BCD, NES不用但为完整性)
- [ ] SBC (Subtract with Carry) - 8种寻址
- [ ] INC (Increment Memory) - 4种寻址
- [ ] INX, INY (Increment X/Y)
- [ ] DEC (Decrement Memory) - 4种寻址
- [ ] DEX, DEY (Decrement X/Y)

### 1.3.4 逻辑指令 ⏳
- [ ] AND - 8种寻址
- [ ] EOR (Exclusive OR) - 8种寻址
- [ ] ORA (OR with Accumulator) - 8种寻址
- [ ] BIT (Bit Test) - 2种寻址

### 1.3.5 移位/旋转指令 ⏳
- [ ] ASL (Arithmetic Shift Left) - 5种寻址
- [ ] LSR (Logical Shift Right) - 5种寻址
- [ ] ROL (Rotate Left) - 5种寻址
- [ ] ROR (Rotate Right) - 5种寻址

### 1.3.6 比较指令 ⏳
- [ ] CMP (Compare Accumulator) - 8种寻址
- [ ] CPX (Compare X) - 3种寻址
- [ ] CPY (Compare Y) - 3种寻址

### 1.3.7 分支指令 ⏳
- [ ] BCC (Branch if Carry Clear)
- [ ] BCS (Branch if Carry Set)
- [ ] BEQ (Branch if Equal)
- [ ] BMI (Branch if Minus)
- [ ] BNE (Branch if Not Equal)
- [ ] BPL (Branch if Plus)
- [ ] BVC (Branch if Overflow Clear)
- [ ] BVS (Branch if Overflow Set)

### 1.3.8 跳转/子程序指令 ⏳
- [ ] JMP (Jump) - Absolute / Indirect
- [ ] JSR (Jump to Subroutine)
- [ ] RTS (Return from Subroutine)
- [ ] RTI (Return from Interrupt)

### 1.3.9 栈操作指令 ⏳
- [ ] PHA (Push Accumulator)
- [ ] PHP (Push Processor Status)
- [ ] PLA (Pull Accumulator)
- [ ] PLP (Pull Processor Status)

### 1.3.10 标志位操作指令 ⏳
- [ ] CLC (Clear Carry)
- [ ] CLD (Clear Decimal)
- [ ] CLI (Clear Interrupt Disable)
- [ ] CLV (Clear Overflow)
- [ ] SEC (Set Carry)
- [ ] SED (Set Decimal)
- [ ] SEI (Set Interrupt Disable)

### 1.3.11 其他指令 ⏳
- [ ] BRK (Break)
- [ ] NOP (No Operation)

### 1.3.12 非官方指令 (部分NES游戏需要) ⏳
- [ ] LAX (LDA + TAX)
- [ ] SAX (STA & STX)
- [ ] DCP (DEC + CMP)
- [ ] ISC (INC + SBC)
- [ ] RLA (ROL + AND)
- [ ] RRA (ROR + ADC)
- [ ] SLO (ASL + ORA)
- [ ] SRE (LSR + EOR)

**产出**: `instructions.cpp`, ~60条指令实现

---

## 任务1.4: 内存映射 (预计2-3天)

### 1.4.1 实现NES内存映射 ⏳
- [ ] 创建 `src/reference/common/memory.h/cpp`
- [ ] 实现内存区域:
  - [ ] $0000-$07FF: 内部RAM (2KB)
  - [ ] $0800-$1FFF: RAM镜像 (×3)
  - [ ] $2000-$2007: PPU寄存器
  - [ ] $2008-$3FFF: PPU寄存器镜像
  - [ ] $4000-$401F: APU和IO寄存器
  - [ ] $6000-$7FFF: SRAM (电池供电RAM)
  - [ ] $8000-$FFFF: PRG ROM

### 1.4.2 实现Mapper 0 (NROM) ⏳
- [ ] 创建 `src/reference/common/mapper0.h/cpp`
- [ ] 支持16KB / 32KB PRG ROM
- [ ] 固定地址映射（无bank switching）
- [ ] ROM加载器

**产出**: 内存系统，Mapper 0

---

## 任务1.5: 中断处理 (预计1-2天)

### 1.5.1 实现中断机制 ⏳
- [ ] 创建 `src/reference/cpu/interrupts.cpp`
- [ ] 实现 NMI (Non-Maskable Interrupt)
  - [ ] PPU触发（$FFFA/$FFFB向量）
- [ ] 实现 IRQ (Interrupt Request)
  - [ ] 可屏蔽中断（$FFFE/$FFFF向量）
  - [ ] 检查I标志位
- [ ] 实现 Reset
  - [ ] 初始化CPU状态（$FFFC/$FFFD向量）

**产出**: 中断系统

---

## 任务1.6: 测试验证 (预计3-4天)

### 1.6.1 单元测试 ⏳
- [ ] 完成所有单元测试
- [ ] 代码覆盖率 > 80%
- [ ] 所有测试通过

### 1.6.2 CPU指令测试ROM ⏳
- [ ] 运行 `01-implied.nes` ✅/❌
- [ ] 运行 `02-immediate.nes` ✅/❌
- [ ] 运行 `03-zero_page.nes` ✅/❌
- [ ] 运行 `04-zp_xy.nes` ✅/❌
- [ ] 运行 `05-absolute.nes` ✅/❌
- [ ] 运行 `06-abs_xy.nes` ✅/❌
- [ ] 运行 `07-ind_x.nes` ✅/❌
- [ ] 运行 `08-ind_y.nes` ✅/❌
- [ ] 运行 `09-branches.nes` ✅/❌
- [ ] 运行 `10-stack.nes` ✅/❌
- [ ] 运行 `11-special.nes` ✅/❌

### 1.6.3 性能测试 ⏳
- [ ] Benchmark: CPU执行1百万条指令耗时
- [ ] 确保无内存泄漏 (valgrind)

**产出**: 完整的测试报告

---

## 📊 任务统计

- **子任务总数**: 约100项
- **已完成**: 0
- **进行中**: 0
- **待开始**: 100

---

**下一步**: 开始任务1.1 - 创建基础架构
