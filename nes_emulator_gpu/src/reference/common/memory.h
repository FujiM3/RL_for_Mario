#ifndef NES_EMULATOR_MEMORY_H
#define NES_EMULATOR_MEMORY_H

#include <cstdint>
#include <functional>
#include <cstring>

// NES memory map implementation
// $0000-$07FF: Internal RAM (2KB)
// $0800-$1FFF: RAM mirrors (×3)
// $2000-$2007: PPU registers
// $2008-$3FFF: PPU register mirrors
// $4000-$401F: APU and IO registers
// $6000-$7FFF: SRAM (battery-backed)
// $8000-$FFFF: PRG ROM (managed by mapper)

class NESMemory {
public:
    NESMemory();
    ~NESMemory();
    
    // Read/write interface
    uint8_t read(uint16_t addr);
    void write(uint16_t addr, uint8_t value);
    
    // PPU register callbacks ($2000-$2007)
    void set_ppu_read_callback(std::function<uint8_t(uint16_t)> callback);
    void set_ppu_write_callback(std::function<void(uint16_t, uint8_t)> callback);
    
    // APU/IO register callbacks ($4000-$401F)
    void set_apu_read_callback(std::function<uint8_t(uint16_t)> callback);
    void set_apu_write_callback(std::function<void(uint16_t, uint8_t)> callback);
    
    // PRG ROM callbacks ($8000-$FFFF) - managed by mapper
    void set_prg_read_callback(std::function<uint8_t(uint16_t)> callback);
    void set_prg_write_callback(std::function<void(uint16_t, uint8_t)> callback);
    
    // Direct RAM access for testing/debugging
    uint8_t* get_ram() { return ram; }
    uint8_t* get_sram() { return sram; }
    
    // Reset memory
    void reset();
    
private:
    // Internal RAM (2KB)
    uint8_t ram[0x0800];  // $0000-$07FF
    
    // Battery-backed SRAM (8KB)
    uint8_t sram[0x2000]; // $6000-$7FFF
    
    // Callback functions
    std::function<uint8_t(uint16_t)> ppu_read_callback;
    std::function<void(uint16_t, uint8_t)> ppu_write_callback;
    
    std::function<uint8_t(uint16_t)> apu_read_callback;
    std::function<void(uint16_t, uint8_t)> apu_write_callback;
    
    std::function<uint8_t(uint16_t)> prg_read_callback;
    std::function<void(uint16_t, uint8_t)> prg_write_callback;
    
    // Helper: default read returns 0
    static uint8_t default_read(uint16_t addr) { return 0; }
    
    // Helper: default write does nothing
    static void default_write(uint16_t addr, uint8_t value) {}
};

#endif // NES_EMULATOR_MEMORY_H
