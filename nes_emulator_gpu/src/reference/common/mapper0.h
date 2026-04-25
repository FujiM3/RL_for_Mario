#ifndef NES_EMULATOR_MAPPER0_H
#define NES_EMULATOR_MAPPER0_H

#include <cstdint>
#include <vector>

// Mapper 0 (NROM) - Simplest NES mapper
// Used by games like: Super Mario Bros, Donkey Kong, Ice Climber
//
// PRG ROM: 16KB or 32KB
//   - 16KB: Mirrored at $8000-$BFFF and $C000-$FFFF
//   - 32KB: Continuous $8000-$FFFF
//
// CHR ROM: 8KB at $0000-$1FFF (PPU address space)
//
// No bank switching - fixed address mapping

class Mapper0 {
public:
    // Constructor: takes PRG ROM and CHR ROM data
    Mapper0(const std::vector<uint8_t>& prg_data, const std::vector<uint8_t>& chr_data);
    ~Mapper0();
    
    // PRG ROM read ($8000-$FFFF in CPU address space)
    uint8_t read_prg(uint16_t addr);
    
    // PRG ROM write (usually ignored, but some games use for RAM)
    void write_prg(uint16_t addr, uint8_t value);
    
    // CHR ROM read ($0000-$1FFF in PPU address space)
    uint8_t read_chr(uint16_t addr);
    
    // CHR ROM write (only if CHR RAM)
    void write_chr(uint16_t addr, uint8_t value);
    
    // Query mapper info
    size_t get_prg_size() const { return prg_rom.size(); }
    size_t get_chr_size() const { return chr_rom.size(); }
    bool is_32kb_prg() const { return prg_rom.size() == 32 * 1024; }
    bool has_chr_ram() const { return is_chr_ram; }
    
    // Reset mapper state
    void reset();
    
private:
    std::vector<uint8_t> prg_rom;  // 16KB or 32KB
    std::vector<uint8_t> chr_rom;  // 8KB CHR ROM or CHR RAM
    bool is_chr_ram;               // true if CHR RAM instead of ROM
    
    // PRG ROM size mask for address calculation
    uint16_t prg_mask;
};

#endif // NES_EMULATOR_MAPPER0_H
