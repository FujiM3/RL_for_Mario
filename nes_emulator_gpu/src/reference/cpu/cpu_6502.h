#ifndef NES_CPU_6502_H
#define NES_CPU_6502_H

#include "common/types.h"
#include "cpu/registers.h"
#include <functional>

// Forward declarations
class NESMemory;

// 6502 CPU Emulator
class CPU6502 {
public:
    // Constructor
    CPU6502();
    
    // Destructor
    ~CPU6502();
    
    // === Core Operations ===
    
    // Reset CPU to power-up state
    void reset();
    
    // Execute one instruction
    // Returns: number of cycles consumed
    u8 step();
    
    // Get total cycles executed
    u64 get_cycles() const { return total_cycles; }
    
    // === Memory Access ===
    
    // Set memory read callback
    void set_read_callback(std::function<u8(u16)> callback);
    
    // Set memory write callback
    void set_write_callback(std::function<void(u16, u8)> callback);
    
    // Read byte from memory
    u8 read(u16 addr);
    
    // Write byte to memory
    void write(u16 addr, u8 value);
    
    // Read 16-bit word (little-endian)
    u16 read_word(u16 addr);
    
    // === Interrupt Handling ===
    
    // Trigger NMI (Non-Maskable Interrupt)
    void trigger_nmi();
    
    // Trigger IRQ (Interrupt Request)
    void trigger_irq();
    
    // === Register Access (for debugging/testing) ===
    
    CPU6502Registers& get_registers() { return regs; }
    const CPU6502Registers& get_registers() const { return regs; }
    
    // === Stack Operations (Public for instructions) ===
    
    void push_byte(u8 value) { push(value); }
    u8 pop_byte() { return pop(); }
    void push_word_public(u16 value) { push_word(value); }
    u16 pop_word_public() { return pop_word(); }
    
    // === Interrupt Trigger (Public for BRK instruction) ===
    
    void trigger_brk();
    
private:
    // === Internal State ===
    
    CPU6502Registers regs;           // CPU registers
    u64 total_cycles;                // Total cycles executed
    u8 cycles_remaining;             // Cycles remaining for current instruction
    
    // Interrupt flags
    bool nmi_pending;
    bool irq_pending;
    
    // Memory callbacks
    std::function<u8(u16)> read_callback;
    std::function<void(u16, u8)> write_callback;
    
    // === Stack Operations ===
    
    // Push byte to stack
    void push(u8 value);
    
    // Push 16-bit word to stack (little-endian)
    void push_word(u16 value);
    
    // Pop byte from stack
    u8 pop();
    
    // Pop 16-bit word from stack (little-endian)
    u16 pop_word();
    
    // === Interrupt Handling (Internal) ===
    
    // Handle pending interrupts
    void handle_interrupts();
    
    // Execute NMI sequence
    void execute_nmi();
    
    // Execute IRQ sequence
    void execute_irq();
    
    // === Instruction Execution (To be implemented) ===
    
    // Fetch and decode next instruction
    u8 fetch_and_execute();
    
    // Execute instruction by opcode
    // Returns: number of cycles consumed
    u8 execute_opcode(u8 opcode);
};

#endif // NES_CPU_6502_H
