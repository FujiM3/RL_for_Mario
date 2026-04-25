#include "mapper0.h"
#include <stdexcept>
#include <cstring>

Mapper0::Mapper0(const std::vector<uint8_t>& prg_data, const std::vector<uint8_t>& chr_data)
    : prg_rom(prg_data), chr_rom(chr_data), is_chr_ram(false) {
    
    // Validate PRG ROM size (must be 16KB or 32KB)
    if (prg_rom.size() != 16 * 1024 && prg_rom.size() != 32 * 1024) {
        throw std::runtime_error("Mapper 0: PRG ROM must be 16KB or 32KB");
    }
    
    // Validate CHR data size
    if (chr_rom.empty()) {
        // No CHR ROM - use CHR RAM instead
        chr_rom.resize(8 * 1024, 0);
        is_chr_ram = true;
    } else if (chr_rom.size() != 8 * 1024) {
        throw std::runtime_error("Mapper 0: CHR ROM must be 8KB");
    }
    
    // Calculate PRG mask for mirroring
    // 16KB: mask = 0x3FFF (mirrors $8000-$BFFF to $C000-$FFFF)
    // 32KB: mask = 0x7FFF (no mirroring)
    prg_mask = static_cast<uint16_t>(prg_rom.size() - 1);
}

Mapper0::~Mapper0() {
}

void Mapper0::reset() {
    // Mapper 0 has no internal state to reset
    // CHR RAM is NOT cleared on reset (games may rely on this)
}

uint8_t Mapper0::read_prg(uint16_t addr) {
    // PRG ROM is mapped to $8000-$FFFF
    // Subtract $8000 to get offset into ROM
    uint16_t offset = (addr - 0x8000) & prg_mask;
    return prg_rom[offset];
}

void Mapper0::write_prg(uint16_t addr, uint8_t value) {
    // Mapper 0 typically has no PRG RAM
    // Writes to PRG ROM area are ignored
    // (Some homebrew games might use this for testing, but it's a no-op)
}

uint8_t Mapper0::read_chr(uint16_t addr) {
    // CHR ROM/RAM is mapped to $0000-$1FFF in PPU address space
    if (addr >= 0x2000) {
        return 0; // Out of range
    }
    return chr_rom[addr];
}

void Mapper0::write_chr(uint16_t addr, uint8_t value) {
    // Only allow writes if using CHR RAM
    if (addr >= 0x2000) {
        return; // Out of range
    }
    
    if (is_chr_ram) {
        chr_rom[addr] = value;
    }
    // If CHR ROM, writes are ignored
}

