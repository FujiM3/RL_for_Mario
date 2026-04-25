#include "cpu/cpu_6502.h"
#include "cpu/instructions.h"
#include "cpu/addressing.h"
#include <stdexcept>

// Constructor
CPU6502::CPU6502() 
    : total_cycles(0)
    , cycles_remaining(0)
    , nmi_pending(false)
    , irq_pending(false)
{
    // Initialize with default memory callbacks (throw error)
    read_callback = [](u16 addr) -> u8 {
        throw std::runtime_error("CPU read callback not set");
        return 0;
    };
    
    write_callback = [](u16 addr, u8 value) {
        throw std::runtime_error("CPU write callback not set");
    };
}

// Destructor
CPU6502::~CPU6502() {
}

// Reset CPU to power-up state
void CPU6502::reset() {
    regs.reset();
    
    // Load PC from RESET vector
    regs.PC = read_word(Memory::RESET_VECTOR);
    
    // Reset state
    total_cycles = 0;
    cycles_remaining = 0;
    nmi_pending = false;
    irq_pending = false;
}

// Execute one instruction
u8 CPU6502::step() {
    // Handle pending interrupts
    handle_interrupts();
    
    // Fetch and execute instruction
    u8 cycles = fetch_and_execute();
    
    // Update total cycles
    total_cycles += cycles;
    
    return cycles;
}

// === Memory Access ===

void CPU6502::set_read_callback(std::function<u8(u16)> callback) {
    read_callback = callback;
}

void CPU6502::set_write_callback(std::function<void(u16, u8)> callback) {
    write_callback = callback;
}

u8 CPU6502::read(u16 addr) {
    return read_callback(addr);
}

void CPU6502::write(u16 addr, u8 value) {
    write_callback(addr, value);
}

u16 CPU6502::read_word(u16 addr) {
    u8 lo = read(addr);
    u8 hi = read(addr + 1);
    return (u16(hi) << 8) | lo;
}

// === Stack Operations ===

void CPU6502::push(u8 value) {
    write(regs.stack_addr(), value);
    regs.push_stack();
}

void CPU6502::push_word(u16 value) {
    push((value >> 8) & 0xFF);  // Push high byte first
    push(value & 0xFF);          // Then low byte
}

u8 CPU6502::pop() {
    regs.pop_stack();
    return read(regs.stack_addr());
}

u16 CPU6502::pop_word() {
    u8 lo = pop();
    u8 hi = pop();
    return (u16(hi) << 8) | lo;
}

// === Interrupt Handling ===

void CPU6502::trigger_nmi() {
    nmi_pending = true;
}

void CPU6502::trigger_irq() {
    irq_pending = true;
}

// Trigger BRK instruction (software interrupt)
void CPU6502::trigger_brk() {
    // BRK is like a software interrupt
    // PC already advanced past BRK opcode, push PC
    push_word(regs.PC);
    push(regs.get_status_brk());  // B flag set for software interrupt
    regs.set_interrupt(true);
    regs.PC = read_word(Memory::IRQ_VECTOR);
}

void CPU6502::handle_interrupts() {
    if (nmi_pending) {
        execute_nmi();
        nmi_pending = false;
    } else if (irq_pending && !regs.get_interrupt()) {
        // IRQ only if I flag is clear
        execute_irq();
        irq_pending = false;
    }
}

void CPU6502::execute_nmi() {
    // Push PC and status to stack
    push_word(regs.PC);
    push(regs.get_status_irq());  // B flag clear for hardware interrupt
    
    // Set interrupt disable flag
    regs.set_interrupt(true);
    
    // Load PC from NMI vector
    regs.PC = read_word(Memory::NMI_VECTOR);
    
    // NMI takes 7 cycles
    total_cycles += 7;
}

void CPU6502::execute_irq() {
    // Push PC and status to stack
    push_word(regs.PC);
    push(regs.get_status_irq());  // B flag clear for hardware interrupt
    
    // Set interrupt disable flag
    regs.set_interrupt(true);
    
    // Load PC from IRQ vector
    regs.PC = read_word(Memory::IRQ_VECTOR);
    
    // IRQ takes 7 cycles
    total_cycles += 7;
}

// === Instruction Execution ===

u8 CPU6502::fetch_and_execute() {
    // Fetch opcode
    u8 opcode = read(regs.PC++);
    
    // Execute instruction
    return execute_opcode(opcode);
}

u8 CPU6502::execute_opcode(u8 opcode) {
    const OpcodeInfo& info = OPCODE_TABLE[opcode];
    
    // Get addressing result based on mode
    AddressingResult addr_result;
    
    switch (info.mode) {
        case AddressingMode::Implied:
            addr_result = Addressing::implied(*this);
            break;
        case AddressingMode::Accumulator:
            addr_result = Addressing::accumulator(*this);
            break;
        case AddressingMode::Immediate:
            addr_result = Addressing::immediate(*this);
            break;
        case AddressingMode::ZeroPage:
            addr_result = Addressing::zero_page(*this);
            break;
        case AddressingMode::ZeroPageX:
            addr_result = Addressing::zero_page_x(*this);
            break;
        case AddressingMode::ZeroPageY:
            addr_result = Addressing::zero_page_y(*this);
            break;
        case AddressingMode::Absolute:
            addr_result = Addressing::absolute(*this);
            break;
        case AddressingMode::AbsoluteX:
            addr_result = Addressing::absolute_x(*this);
            break;
        case AddressingMode::AbsoluteY:
            addr_result = Addressing::absolute_y(*this);
            break;
        case AddressingMode::Relative:
            addr_result = Addressing::relative(*this);
            break;
        case AddressingMode::Indirect:
            addr_result = Addressing::indirect(*this);
            break;
        case AddressingMode::IndexedIndirect:
            addr_result = Addressing::indexed_indirect(*this);
            break;
        case AddressingMode::IndirectIndexed:
            addr_result = Addressing::indirect_indexed(*this);
            break;
        default:
            throw std::runtime_error("Unknown addressing mode");
    }
    
    // Execute instruction
    info.execute(*this, addr_result);
    
    // Calculate cycles (base + extra if page crossed)
    u8 cycles = info.cycles;
    if (info.extra_cycle_on_page && addr_result.page_crossed) {
        cycles++;
    }
    
    return cycles;
}
