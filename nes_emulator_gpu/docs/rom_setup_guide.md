# ROM文件获取指南

⚠️ **版权声明**: NES ROM文件受版权保护。本项目仅用于学术研究和教育目的。

---

## 必需的ROM文件

### 1. Super Mario Bros (测试和训练)
- **文件名**: `Super Mario Bros (E).nes` 或 `smb.nes`
- **MD5**: 811b027eaf99c2def7b933c5208636de (欧版)
- **Mapper**: 0 (NROM)
- **大小**: 40 KB (32KB PRG + 8KB CHR)

**合法获取途径**:
1. 如果您拥有原版卡带，可以使用Retrode等设备合法转储
2. 某些NES合集（如Nintendo Switch Online）允许研究用途
3. 联系版权方获取研究许可

**放置位置**: `tests/roms/smb.nes`

---

### 2. blargg's CPU Tests ✅ 公开可用
- **仓库**: https://github.com/christopherpow/nes-test-roms
- **许可**: 多数为公开域或MIT
- **关键测试集**:
  * nes_instr_test/rom_singles/ - 11个指令测试
  * cpu_exec_space/ - CPU执行空间测试

**已准备**: 通过 nes-test-roms 仓库获取

---

### 3. blargg's PPU Tests ✅ 公开可用
- **关键测试集**:
  * ppu_vbl_nmi/ - VBlank和NMI时序
  * sprite_hit_tests_2005.10.05/ - 精灵0命中检测
  * sprite_overflow_tests/ - 精灵溢出

**已准备**: 通过 nes-test-roms 仓库获取

---

## ROM目录结构

```
tests/
├── roms/                       # 自备ROM
│   └── smb.nes                # Super Mario Bros (需自行获取)
└── integration/
    └── nes-test-roms/         # 公开测试ROM集
        ├── nes_instr_test/    # CPU测试 (11个)
        ├── ppu_vbl_nmi/       # PPU时序测试
        └── ...                # 其他测试
```

---

## 验收检查

```bash
cd tests/integration/nes-test-roms
ls nes_instr_test/rom_singles/*.nes | wc -l   # 应显示 11
ls ppu_vbl_nmi/*.nes | wc -l                   # 应显示测试ROM

cd ../../roms
ls smb.nes                                     # (需用户提供)
```

---

**最后更新**: 2026-04-25  
**状态**: 公开测试ROM已就绪，SMB需用户自行提供
