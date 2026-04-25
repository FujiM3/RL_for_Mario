#include "memory.h"

NESMemory::NESMemory() {
    reset();
    
    // Set default callbacks
    ppu_read_callback = default_read;
    ppu_write_callback = default_write;
    apu_read_callback = default_read;
    apu_write_callback = default_write;
    prg_read_callback = default_read;
    prg_write_callback = default_write;
}

NESMemory::~NESMemory() {
}

void NESMemory::reset() {
    // Clear internal RAM
    std::memset(ram, 0, sizeof(ram));
    
    // Clear SRAM (some games expect this)
    std::memset(sram, 0, sizeof(sram));
}

uint8_t NESMemory::read(uint16_t addr) {
    // $0000-$1FFF: Internal RAM and mirrors
    if (addr < 0x2000) {
        // RAM mirrors: $0800-$1FFF map to $0000-$07FF
        return ram[addr & 0x07FF];
    }
    
    // $2000-$3FFF: PPU registers and mirrors
    if (addr < 0x4000) {
        // PPU registers mirror every 8 bytes
        uint16_t ppu_addr = 0x2000 + (addr & 0x0007);
        return ppu_read_callback(ppu_addr);
    }
    
    // $4000-$401F: APU and IO registers
    if (addr < 0x4020) {
        return apu_read_callback(addr);
    }
    
    // $4020-$5FFF: Expansion ROM (rare, usually open bus)
    if (addr < 0x6000) {
        return 0; // Open bus behavior (simplified)
    }
    
    // $6000-$7FFF: SRAM (battery-backed)
    if (addr < 0x8000) {
        return sram[addr - 0x6000];
    }
    
    // $8000-$FFFF: PRG ROM (managed by mapper)
    return prg_read_callback(addr);
}

void NESMemory::write(uint16_t addr, uint8_t value) {
    // $0000-$1FFF: Internal RAM and mirrors
    if (addr < 0x2000) {
        // RAM mirrors: $0800-$1FFF map to $0000-$07FF
        ram[addr & 0x07FF] = value;
        return;
    }
    
    // $2000-$3FFF: PPU registers and mirrors
    if (addr < 0x4000) {
        // PPU registers mirror every 8 bytes
        uint16_t ppu_addr = 0x2000 + (addr & 0x0007);
        ppu_write_callback(ppu_addr, value);
        return;
    }
    
    // $4000-$401F: APU and IO registers
    if (addr < 0x4020) {
        apu_write_callback(addr, value);
        return;
    }
    
    // $4020-$5FFF: Expansion ROM (rare)
    if (addr < 0x6000) {
        // Ignore writes to expansion ROM area
        return;
    }
    
    // $6000-$7FFF: SRAM (battery-backed)
    if (addr < 0x8000) {
        sram[addr - 0x6000] = value;
        return;
    }
    
    // $8000-$FFFF: PRG ROM (mapper may handle bank switching)
    prg_write_callback(addr, value);
}

// Callback setters
void NESMemory::set_ppu_read_callback(std::function<uint8_t(uint16_t)> callback) {
    ppu_read_callback = callback ? callback : default_read;
}

void NESMemory::set_ppu_write_callback(std::function<void(uint16_t, uint8_t)> callback) {
    ppu_write_callback = callback ? callback : default_write;
}

void NESMemory::set_apu_read_callback(std::function<uint8_t(uint16_t)> callback) {
    apu_read_callback = callback ? callback : default_read;
}

void NESMemory::set_apu_write_callback(std::function<void(uint16_t, uint8_t)> callback) {
    apu_write_callback = callback ? callback : default_write;
}

void NESMemory::set_prg_read_callback(std::function<uint8_t(uint16_t)> callback) {
    prg_read_callback = callback ? callback : default_read;
}

void NESMemory::set_prg_write_callback(std::function<void(uint16_t, uint8_t)> callback) {
    prg_write_callback = callback ? callback : default_write;
}
