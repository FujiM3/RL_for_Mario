/*
 * GPU Single Instance Tests - Phase 3
 *
 * Tests that verify the GPU NES port produces correct output.
 *
 * Test strategy:
 *   1. Load a minimal test ROM (synthetic PRG + CHR)
 *   2. Run reset + frame on GPU
 *   3. Verify PPU state (VBlank set, NMI triggered)
 *   4. Verify framebuffer has non-zero output
 *
 * Note: Full correctness vs. CPU reference requires a real ROM comparison
 * (Phase 3 validation). These tests verify basic functionality.
 */

#include <gtest/gtest.h>
#include <cuda_runtime.h>
#include <cstring>
#include <cstdint>
#include <vector>

#include "device/nes_state.h"
// Device functions are compiled into nes_gpu_lib; only nes_state.h needed for struct types.

// Forward declarations for kernels
__global__ void nes_run_frame(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t);
__global__ void nes_reset(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t);
__global__ void nes_step_frames(NESState*, const uint8_t*, uint32_t, const uint8_t*, uint32_t, int);
__global__ void nes_get_framebuffer(const NESState* state, uint32_t* output);

// ---------------------------------------------------------------------------
// Helper: build a minimal NROM-128 (16KB PRG, 8KB CHR) test ROM
// ---------------------------------------------------------------------------

// Minimal PRG ROM that:
//   - Has RESET vector pointing to start of code
//   - Enables PPU rendering (writes to $2000, $2001)
//   - Loops forever waiting for NMI
static std::vector<uint8_t> make_test_prg_rom() {
    std::vector<uint8_t> prg(0x4000, 0xEA);  // Fill with NOP

    // Code starts at $C000 (address $8000 in 16KB mirrored PRG)
    uint16_t code_start = 0x0000;  // Relative to start of PRG

    // Assembly (hand-encoded):
    //   SEI              ; $78 - disable interrupts initially
    //   LDA #$90         ; $A9 $90 - enable NMI + background pattern $1000
    //   STA $2000        ; $8D $00 $20 - write PPUCTRL
    //   LDA #$1E         ; $A9 $1E - enable background + sprites
    //   STA $2001        ; $8D $01 $20 - write PPUMASK
    //   CLI              ; $58 - re-enable interrupts
    // loop:
    //   JMP loop         ; $4C XX $C0 - infinite loop

    uint8_t code[] = {
        0x78,             // SEI
        0xA9, 0x90,       // LDA #$90
        0x8D, 0x00, 0x20, // STA $2000
        0xA9, 0x1E,       // LDA #$1E
        0x8D, 0x01, 0x20, // STA $2001
        0x58,             // CLI
        // loop:
        0x4C, 0x0C, 0x80, // JMP $800C (loop back to JMP instruction)
    };

    // Copy code into PRG
    for (size_t i = 0; i < sizeof(code); i++) {
        prg[code_start + i] = code[i];
    }

    // NMI handler: RTI
    uint16_t nmi_handler = 0x0100;
    prg[nmi_handler] = 0x40;  // RTI

    // Set vectors (at end of PRG: $3FFA-$3FFF)
    uint16_t reset_addr = 0x8000;
    uint16_t nmi_addr   = 0x8100;
    prg[0x3FFA] = (uint8_t)(nmi_addr & 0xFF);
    prg[0x3FFB] = (uint8_t)(nmi_addr >> 8);
    prg[0x3FFC] = (uint8_t)(reset_addr & 0xFF);
    prg[0x3FFD] = (uint8_t)(reset_addr >> 8);
    prg[0x3FFE] = 0x00;  // IRQ vector
    prg[0x3FFF] = 0x80;

    return prg;
}

// Minimal CHR ROM: alternating pixels in tile 0
static std::vector<uint8_t> make_test_chr_rom() {
    std::vector<uint8_t> chr(0x2000, 0);

    // Tile 0: checkerboard pattern
    for (int row = 0; row < 8; row++) {
        chr[row]     = (row % 2) ? 0xAA : 0x55;  // lo plane
        chr[row + 8] = (row % 2) ? 0x55 : 0xAA;  // hi plane
    }

    return chr;
}

// ---------------------------------------------------------------------------
// Test fixture
// ---------------------------------------------------------------------------

class GPUSingleTest : public ::testing::Test {
protected:
    NESState*  d_state  = nullptr;
    uint8_t*   d_prg    = nullptr;
    uint8_t*   d_chr    = nullptr;
    NESState   h_state;

    std::vector<uint8_t> prg_rom;
    std::vector<uint8_t> chr_rom;

    void SetUp() override {
        // Check CUDA is available
        int count = 0;
        cudaError_t err = cudaGetDeviceCount(&count);
        if (err != cudaSuccess || count == 0) {
            GTEST_SKIP() << "No CUDA device available";
        }

        prg_rom = make_test_prg_rom();
        chr_rom = make_test_chr_rom();

        ASSERT_EQ(cudaMalloc(&d_state, sizeof(NESState)), cudaSuccess);
        ASSERT_EQ(cudaMemset(d_state, 0, sizeof(NESState)), cudaSuccess);
        ASSERT_EQ(cudaMalloc(&d_prg, prg_rom.size()), cudaSuccess);
        ASSERT_EQ(cudaMalloc(&d_chr, chr_rom.size()), cudaSuccess);

        ASSERT_EQ(cudaMemcpy(d_prg, prg_rom.data(), prg_rom.size(), cudaMemcpyHostToDevice), cudaSuccess);
        ASSERT_EQ(cudaMemcpy(d_chr, chr_rom.data(), chr_rom.size(), cudaMemcpyHostToDevice), cudaSuccess);

        // Set mirroring = horizontal (SMB default)
        uint8_t mir = MIRROR_HORIZONTAL;
        size_t mirror_offset = offsetof(NESState, ppu) + offsetof(NESPPUState, mirroring);
        ASSERT_EQ(cudaMemcpy(reinterpret_cast<uint8_t*>(d_state) + mirror_offset,
                             &mir, 1, cudaMemcpyHostToDevice), cudaSuccess);

        // Run reset
        nes_reset<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                             d_chr, (uint32_t)chr_rom.size());
        ASSERT_EQ(cudaGetLastError(), cudaSuccess);
        ASSERT_EQ(cudaDeviceSynchronize(), cudaSuccess);
    }

    void TearDown() override {
        if (d_state) cudaFree(d_state);
        if (d_prg)   cudaFree(d_prg);
        if (d_chr)   cudaFree(d_chr);
    }

    // Copy device state to host
    void sync_state() {
        ASSERT_EQ(cudaMemcpy(&h_state, d_state, sizeof(NESState), cudaMemcpyDeviceToHost), cudaSuccess);
    }

    void run_frame() {
        nes_run_frame<<<1, 1>>>(d_state, d_prg, (uint32_t)prg_rom.size(),
                                 d_chr, (uint32_t)chr_rom.size());
        ASSERT_EQ(cudaGetLastError(), cudaSuccess);
        ASSERT_EQ(cudaDeviceSynchronize(), cudaSuccess);
    }
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

TEST_F(GPUSingleTest, ResetSetsPC) {
    sync_state();
    // PC should be loaded from RESET vector ($FFFC-$FFFD)
    // Our ROM has reset vector at $8000
    EXPECT_EQ(h_state.cpu.PC, 0x8000u)
        << "CPU PC should be at RESET vector address $8000 after reset";
}

TEST_F(GPUSingleTest, ResetInitializesRegisters) {
    sync_state();
    EXPECT_EQ(h_state.cpu.SP, 0xFDu)  << "SP should be $FD after reset";
    EXPECT_EQ(h_state.cpu.A, 0u)      << "A should be 0 after reset";
    EXPECT_EQ(h_state.cpu.X, 0u)      << "X should be 0 after reset";
    EXPECT_EQ(h_state.cpu.Y, 0u)      << "Y should be 0 after reset";
    // I flag should be set (interrupt disable)
    EXPECT_TRUE(h_state.cpu.P & CPU_FLAG_I) << "I flag should be set after reset";
}

TEST_F(GPUSingleTest, ResetClearsPPU) {
    sync_state();
    EXPECT_EQ(h_state.ppu.scanline, 0)   << "PPU scanline should be 0 after reset";
    EXPECT_EQ(h_state.ppu.cycle, 0)      << "PPU cycle should be 0 after reset";
    EXPECT_EQ(h_state.ppu.frame_ready, 0) << "frame_ready should be 0 after reset";
}

TEST_F(GPUSingleTest, RunOneFrameCompletes) {
    run_frame();
    sync_state();

    // After running one frame, frame_ready should still be 0 (cleared at end)
    // More importantly, PPU should have advanced past scanline 0
    EXPECT_GT(h_state.cpu.total_cycles, 0u)
        << "CPU should have executed some cycles";
}

TEST_F(GPUSingleTest, VBlankOccursDuringFrame) {
    // After one frame, VBlank should have been triggered and cleared
    // PPU status VBlank bit (bit 7) is cleared when read, so we check
    // that the NMI handler was entered (CPU executed the RTI instruction)
    run_frame();
    sync_state();

    // The NMI handler runs RTI which doesn't change any register we can check.
    // Instead verify total_cycles > minimum expected for one frame.
    // One frame = ~29,780 CPU cycles minimum (no DMA stalls).
    EXPECT_GT(h_state.cpu.total_cycles, 20000u)
        << "One frame should take at least 20000 CPU cycles";
}

TEST_F(GPUSingleTest, FramebufferNotAllBlack) {
    // Run a frame - with rendering enabled, at least some pixels should be non-zero.
    // framebuffer now stores uint8_t palette indices; use nes_get_framebuffer to get RGBA.
    run_frame();

    uint32_t* d_rgba = nullptr;
    ASSERT_EQ(cudaMalloc(&d_rgba, NES_FRAMEBUFFER_SIZE * sizeof(uint32_t)), cudaSuccess);
    nes_get_framebuffer<<<240, 256>>>(d_state, d_rgba);
    ASSERT_EQ(cudaGetLastError(), cudaSuccess);
    ASSERT_EQ(cudaDeviceSynchronize(), cudaSuccess);

    std::vector<uint32_t> h_rgba(NES_FRAMEBUFFER_SIZE);
    ASSERT_EQ(cudaMemcpy(h_rgba.data(), d_rgba,
                         NES_FRAMEBUFFER_SIZE * sizeof(uint32_t),
                         cudaMemcpyDeviceToHost), cudaSuccess);
    cudaFree(d_rgba);

    int non_zero = 0;
    for (int i = 0; i < NES_FRAMEBUFFER_SIZE; i++) {
        if (h_rgba[i] != 0) non_zero++;
    }

    // NES_PALETTE_CONST[0] maps palette index 0 → non-zero RGBA (e.g. gray)
    EXPECT_GT(non_zero, 0) << "Framebuffer RGBA should have some non-zero pixels";
}

TEST_F(GPUSingleTest, MultipleFramesAdvanceState) {
    run_frame();
    sync_state();
    uint64_t cycles_after_1 = h_state.cpu.total_cycles;

    run_frame();
    sync_state();
    uint64_t cycles_after_2 = h_state.cpu.total_cycles;

    EXPECT_GT(cycles_after_2, cycles_after_1)
        << "Second frame should add more CPU cycles";

    // Second frame should be within 20% of first frame's cycles
    uint64_t frame1_cycles = cycles_after_1;
    uint64_t frame2_cycles = cycles_after_2 - cycles_after_1;
    EXPECT_NEAR((double)frame2_cycles, (double)frame1_cycles, frame1_cycles * 0.2)
        << "Each frame should take a consistent number of cycles";
}

TEST_F(GPUSingleTest, PPUMirroringIsSet) {
    sync_state();
    EXPECT_EQ(h_state.ppu.mirroring, MIRROR_HORIZONTAL)
        << "Mirroring should be horizontal (default)";
}

// ---------------------------------------------------------------------------
// PPU unit tests (run on device via small kernels defined in nes_frame_kernel.cu)
// ---------------------------------------------------------------------------

// Forward declarations for test helper kernels (defined in nes_frame_kernel.cu)
__global__ void test_ppu_register_write_read(NESPPUState* ppu);
__global__ void test_ppu_vblank(NESPPUState* ppu, const uint8_t* chr_rom);

TEST_F(GPUSingleTest, PPURegisterWriteWorks) {
    // Allocate a separate PPU state for unit testing
    NESPPUState* d_ppu;
    ASSERT_EQ(cudaMalloc(&d_ppu, sizeof(NESPPUState)), cudaSuccess);
    ASSERT_EQ(cudaMemset(d_ppu, 0, sizeof(NESPPUState)), cudaSuccess);

    test_ppu_register_write_read<<<1, 1>>>(d_ppu);
    ASSERT_EQ(cudaGetLastError(), cudaSuccess);
    ASSERT_EQ(cudaDeviceSynchronize(), cudaSuccess);

    NESPPUState h_ppu;
    ASSERT_EQ(cudaMemcpy(&h_ppu, d_ppu, sizeof(NESPPUState), cudaMemcpyDeviceToHost), cudaSuccess);

    EXPECT_EQ(h_ppu.ctrl, 0x90u) << "PPUCTRL should be $90";
    EXPECT_EQ(h_ppu.mask, 0x1Eu) << "PPUMASK should be $1E";
    EXPECT_TRUE(h_ppu.ctrl & 0x80u) << "NMI enable bit should be set";

    cudaFree(d_ppu);
}

TEST_F(GPUSingleTest, PPUVBlankTriggersNMI) {
    NESPPUState* d_ppu;
    ASSERT_EQ(cudaMalloc(&d_ppu, sizeof(NESPPUState)), cudaSuccess);
    ASSERT_EQ(cudaMemset(d_ppu, 0, sizeof(NESPPUState)), cudaSuccess);

    test_ppu_vblank<<<1, 1>>>(d_ppu, d_chr);
    ASSERT_EQ(cudaGetLastError(), cudaSuccess);
    ASSERT_EQ(cudaDeviceSynchronize(), cudaSuccess);

    NESPPUState h_ppu;
    ASSERT_EQ(cudaMemcpy(&h_ppu, d_ppu, sizeof(NESPPUState), cudaMemcpyDeviceToHost), cudaSuccess);

    EXPECT_EQ(h_ppu.scanline, 241) << "Should be at scanline 241";
    EXPECT_EQ(h_ppu.cycle, 1)     << "Should be at cycle 1";
    EXPECT_TRUE(h_ppu.status & 0x80u) << "VBlank flag should be set";
    EXPECT_TRUE(h_ppu.nmi_flag)       << "NMI flag should be set";

    cudaFree(d_ppu);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
