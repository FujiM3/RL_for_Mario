#ifndef NES_PPU_H
#define NES_PPU_H

#include <cstdint>
#include <functional>

namespace nes {

/**
 * NES PPU (Picture Processing Unit) - 2C02
 * 
 * Responsibilities:
 * - Render 256x240 pixel frames
 * - Background rendering (32x30 tiles)
 * - Sprite rendering (up to 64 sprites, 8 per scanline)
 * - Scanline timing (261 scanlines per frame, 341 cycles per scanline)
 * - VBlank NMI generation
 * 
 * Memory Map:
 * - $0000-$1FFF: Pattern Tables (CHR ROM, from mapper)
 * - $2000-$2FFF: Name Tables (VRAM, 2KB + mirroring)
 * - $3F00-$3F1F: Palette RAM
 * - OAM: 256 bytes (64 sprites × 4 bytes)
 */
class PPU {
public:
    PPU();
    ~PPU() = default;

    // CPU-visible register interface ($2000-$2007)
    uint8_t read_register(uint16_t addr);
    void write_register(uint16_t addr, uint8_t value);

    // OAM DMA ($4014) - CPU writes 256 bytes from CPU memory to OAM
    void oam_dma(const uint8_t* cpu_memory, uint8_t page);

    // Tick PPU by 1 cycle (PPU runs 3x faster than CPU)
    void tick();

    // Frame completion
    bool is_frame_ready() const { return frame_ready; }
    void clear_frame_ready() { frame_ready = false; }
    const uint32_t* get_framebuffer() const { return framebuffer; }

    // NMI status
    bool nmi_triggered() const { return nmi_flag; }
    void clear_nmi() { nmi_flag = false; }

    // Set CHR ROM callback (provided by mapper)
    void set_chr_callback(std::function<uint8_t(uint16_t)> read_cb) {
        chr_read = read_cb;
    }

    // Set mirroring mode (from mapper)
    enum Mirroring {
        HORIZONTAL = 0,  // Super Mario Bros uses this
        VERTICAL = 1,
        SINGLE_SCREEN_A = 2,
        SINGLE_SCREEN_B = 3,
        FOUR_SCREEN = 4
    };
    void set_mirroring(Mirroring mode) { mirroring = mode; }

private:
    // ========== PPU Registers (CPU-visible) ==========
    
    // $2000 PPUCTRL
    uint8_t ctrl;
    // bits:
    //   0-1: Base nametable (0=$2000, 1=$2400, 2=$2800, 3=$2C00)
    //     2: VRAM increment (0=+1, 1=+32)
    //     3: Sprite pattern table (0=$0000, 1=$1000)
    //     4: Background pattern table (0=$0000, 1=$1000)
    //     5: Sprite size (0=8x8, 1=8x16)
    //     6: PPU master/slave (unused)
    //     7: Generate NMI at VBlank (0=off, 1=on)

    // $2001 PPUMASK
    uint8_t mask;
    // bits:
    //     0: Grayscale
    //     1: Show leftmost 8 pixels of background
    //     2: Show leftmost 8 pixels of sprites
    //     3: Show background
    //     4: Show sprites
    //     5: Emphasize red
    //     6: Emphasize green
    //     7: Emphasize blue

    // $2002 PPUSTATUS (read-only)
    uint8_t status;
    // bits:
    //   0-4: Least significant bits of last write (open bus)
    //     5: Sprite overflow
    //     6: Sprite 0 Hit
    //     7: VBlank started (cleared on read)

    // $2003 OAMADDR
    uint8_t oam_addr;

    // $2004 OAMDATA - read/write OAM

    // $2005 PPUSCROLL - written twice (X then Y)
    
    // $2006 PPUADDR - written twice (high then low byte)
    
    // $2007 PPUDATA - read/write PPU memory

    // ========== Internal Registers ==========
    
    // Sprite rendering state
    struct ActiveSprite {
        uint8_t x;
        uint8_t y;
        uint8_t tile;
        uint8_t attr;
        uint8_t oam_index;
        // OPTIMIZATION: Pre-fetched pattern data (avoid CHR reads during rendering)
        uint16_t pattern;  // Pre-computed pattern data for current scanline
    };
    ActiveSprite active_sprites[8];
    int active_sprite_count;
    
    // v: Current VRAM address (15 bits)
    uint16_t v;
    
    // t: Temporary VRAM address (15 bits)
    uint16_t t;
    
    // x: Fine X scroll (3 bits)
    uint8_t x;
    
    // w: Write toggle (1 bit) - false=first write, true=second write
    bool w;

    // Internal data buffer for PPUDATA reads
    uint8_t read_buffer;

    // ========== PPU Memory ==========
    
    // VRAM (2KB) - Name Tables
    uint8_t vram[2048];
    
    // Palette RAM (32 bytes)
    // $3F00-$3F0F: Background palettes (4 palettes × 4 colors)
    // $3F10-$3F1F: Sprite palettes (4 palettes × 4 colors)
    uint8_t palette[32];
    
    // OAM (Object Attribute Memory) - 256 bytes
    // 64 sprites × 4 bytes each:
    //   Byte 0: Y position - 1
    //   Byte 1: Tile index
    //   Byte 2: Attributes (palette, priority, flip)
    //   Byte 3: X position
    uint8_t oam[256];

    // ========== External Memory Access ==========
    
    // CHR ROM read callback (provided by mapper)
    std::function<uint8_t(uint16_t)> chr_read;
    
    // Mirroring mode
    Mirroring mirroring;

    // ========== Rendering State ==========
    
    // Framebuffer (256×240 pixels, RGBA8888)
    uint32_t framebuffer[256 * 240];
    
    // Current scanline (0-260)
    int scanline;
    
    // Current cycle within scanline (0-340)
    int cycle;
    
    // Frame ready flag
    bool frame_ready;
    
    // NMI flag
    bool nmi_flag;

    // ========== Helper Functions ==========
    
    // Read from PPU address space
    uint8_t ppu_read(uint16_t addr);
    
    // Write to PPU address space
    void ppu_write(uint16_t addr, uint8_t value);
    
    // OPTIMIZATION: Fast-path memory access (inline, no full address decoding)
    // These bypass ppu_read() for hot rendering paths where address range is known
    
    // Fast nametable read (addr must be in $2000-$3EFF range)
    inline uint8_t read_nametable_fast(uint16_t addr) {
        return vram[mirror_nametable(addr)];
    }
    
    // Fast palette read (index 0-31)
    inline uint8_t read_palette_fast(uint8_t index) {
        index &= 0x1F;
        // Palette mirroring: $10, $14, $18, $1C mirror to $00, $04, $08, $0C
        if ((index & 0x13) == 0x10) {
            index &= 0x0F;
        }
        return palette[index];
    }
    
    // Mirror nametable address based on mirroring mode
    uint16_t mirror_nametable(uint16_t addr);
    
    // Increment VRAM address based on PPUCTRL bit 2
    void increment_v();
    
    // ========== Background Rendering ==========
    
    // Render background pixel at specific position
    void render_background_pixel(int x, int y);
    
    // Render background tile (8 pixels at once) - OPTIMIZED
    void render_background_tile(int tile_x, int y);
    
    // Render using v register (hardware-accurate scrolling)
    void render_pixel_from_v(int screen_x, int screen_y);
    
    // Get tile index from name table
    uint8_t get_nametable_tile(int nt_x, int nt_y);
    
    // Get tile from v register (for scrolling)
    uint8_t get_tile_from_v();
    
    // Get attribute (palette) from attribute table
    uint8_t get_attribute_palette(int nt_x, int nt_y);
    
    // Get attribute from v register
    uint8_t get_attribute_from_v();
    
    // Get pattern (tile graphics) from CHR
    void get_pattern_tile(uint8_t tile_index, uint8_t fine_y, uint8_t& lo, uint8_t& hi);
    
    // Get final color from palette
    uint32_t get_background_color(uint8_t palette_idx, uint8_t pixel);
    
    // Scrolling helpers (for accurate hardware emulation)
    void increment_coarse_x();   // Increment horizontal position in v
    void increment_fine_y();     // Increment vertical position in v  
    void copy_horizontal_bits(); // Copy horizontal bits from t to v
    void copy_vertical_bits();   // Copy vertical bits from t to v
    
    // ========== Sprite Rendering ==========
    
    // Evaluate sprites for current scanline
    void evaluate_sprites();
    
    // Render sprite pixel at specific position
    void render_sprite_pixel(int x, int y);
    
    // Get sprite pattern with flip support
    uint16_t get_sprite_pattern(uint8_t tile, int fine_y, bool vflip);
    
    // Get sprite color from palette
    uint32_t get_sprite_color(uint8_t palette_idx, uint8_t pixel);
};

} // namespace nes

#endif // NES_PPU_H
