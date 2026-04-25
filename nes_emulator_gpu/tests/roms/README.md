# NES GPU模拟器 - 测试ROM

本目录存放用于测试和训练的ROM文件。

⚠️ **版权警告**: 此目录在.gitignore中，不会提交到Git仓库。

---

## 当前ROM清单

### CPU指令测试ROM (11个) ✅
来自 blargg's nes_instr_test

- `01-implied.nes` - Implied寻址模式
- `02-immediate.nes` - Immediate寻址
- `03-zero_page.nes` - Zero Page寻址
- `04-zp_xy.nes` - Zero Page X/Y
- `05-absolute.nes` - Absolute寻址
- `06-abs_xy.nes` - Absolute X/Y
- `07-ind_x.nes` - Indexed Indirect
- `08-ind_y.nes` - Indirect Indexed
- `09-branches.nes` - 分支指令
- `10-stack.nes` - 栈操作
- `11-special.nes` - 特殊指令

### 训练ROM ⚠️ 需自行获取
- `smb.nes` - Super Mario Bros (用于训练)

---

## 如何获取ROM

详见: [`../../docs/rom_setup_guide.md`](../../docs/rom_setup_guide.md)

---

## 使用方法

```bash
# 检查ROM
ls *.nes

# Phase 1: 运行CPU测试
../../build/nes_cpu_test 01-implied.nes

# Phase 2: 运行完整模拟器
../../build/nes_emulator smb.nes
```

---

**目录状态**: 11个CPU测试ROM ✅, SMB待提供 ⚠️
