#include "cpu/addressing.h"
#include "cpu/cpu_6502.h"

// Implied: No operand
AddressingResult Addressing::implied(CPU6502& cpu) {
    AddressingResult result;
    // No operand, no address
    return result;
}

// Accumulator: Operate on accumulator
AddressingResult Addressing::accumulator(CPU6502& cpu) {
    AddressingResult result;
    // No address needed, operates on A register
    return result;
}

// Immediate: #$nn
AddressingResult Addressing::immediate(CPU6502& cpu) {
    AddressingResult result;
    result.is_immediate = true;
    result.value = cpu.read(cpu.get_registers().PC++);
    return result;
}

// Zero Page: $nn
AddressingResult Addressing::zero_page(CPU6502& cpu) {
    AddressingResult result;
    u8 addr_low = cpu.read(cpu.get_registers().PC++);
    result.address = addr_low;  // Zero page: $00nn
    return result;
}

// Zero Page, X: $nn,X
AddressingResult Addressing::zero_page_x(CPU6502& cpu) {
    AddressingResult result;
    u8 addr_low = cpu.read(cpu.get_registers().PC++);
    // Wrap around within zero page
    result.address = (addr_low + cpu.get_registers().X) & 0xFF;
    return result;
}

// Zero Page, Y: $nn,Y
AddressingResult Addressing::zero_page_y(CPU6502& cpu) {
    AddressingResult result;
    u8 addr_low = cpu.read(cpu.get_registers().PC++);
    // Wrap around within zero page
    result.address = (addr_low + cpu.get_registers().Y) & 0xFF;
    return result;
}

// Absolute: $nnnn
AddressingResult Addressing::absolute(CPU6502& cpu) {
    AddressingResult result;
    result.address = cpu.read_word(cpu.get_registers().PC);
    cpu.get_registers().PC += 2;
    return result;
}

// Absolute, X: $nnnn,X
AddressingResult Addressing::absolute_x(CPU6502& cpu) {
    AddressingResult result;
    u16 base_addr = cpu.read_word(cpu.get_registers().PC);
    cpu.get_registers().PC += 2;
    result.address = base_addr + cpu.get_registers().X;
    result.page_crossed = page_crossed(base_addr, result.address);
    return result;
}

// Absolute, Y: $nnnn,Y
AddressingResult Addressing::absolute_y(CPU6502& cpu) {
    AddressingResult result;
    u16 base_addr = cpu.read_word(cpu.get_registers().PC);
    cpu.get_registers().PC += 2;
    result.address = base_addr + cpu.get_registers().Y;
    result.page_crossed = page_crossed(base_addr, result.address);
    return result;
}

// Relative: Branch offset (signed byte)
AddressingResult Addressing::relative(CPU6502& cpu) {
    AddressingResult result;
    s8 offset = (s8)cpu.read(cpu.get_registers().PC++);
    u16 base_addr = cpu.get_registers().PC;
    result.address = base_addr + offset;
    result.page_crossed = page_crossed(base_addr, result.address);
    return result;
}

// Indirect: ($nnnn) - JMP only
AddressingResult Addressing::indirect(CPU6502& cpu) {
    AddressingResult result;
    u16 ptr_addr = cpu.read_word(cpu.get_registers().PC);
    cpu.get_registers().PC += 2;
    
    // 6502 bug: If ptr_addr is at page boundary (e.g., $xxFF),
    // high byte is fetched from $xx00 instead of $(xx+1)00
    if ((ptr_addr & 0xFF) == 0xFF) {
        u8 lo = cpu.read(ptr_addr);
        u8 hi = cpu.read(ptr_addr & 0xFF00);  // Wrap to start of page
        result.address = (u16(hi) << 8) | lo;
    } else {
        result.address = cpu.read_word(ptr_addr);
    }
    
    return result;
}

// Indexed Indirect: ($nn,X)
AddressingResult Addressing::indexed_indirect(CPU6502& cpu) {
    AddressingResult result;
    u8 zero_page_addr = cpu.read(cpu.get_registers().PC++);
    u8 ptr_addr = (zero_page_addr + cpu.get_registers().X) & 0xFF;
    
    // Read pointer from zero page (wraps within zero page)
    u8 lo = cpu.read(ptr_addr);
    u8 hi = cpu.read((ptr_addr + 1) & 0xFF);
    result.address = (u16(hi) << 8) | lo;
    
    return result;
}

// Indirect Indexed: ($nn),Y
AddressingResult Addressing::indirect_indexed(CPU6502& cpu) {
    AddressingResult result;
    u8 zero_page_addr = cpu.read(cpu.get_registers().PC++);
    
    // Read pointer from zero page
    u8 lo = cpu.read(zero_page_addr);
    u8 hi = cpu.read((zero_page_addr + 1) & 0xFF);
    u16 base_addr = (u16(hi) << 8) | lo;
    
    // Add Y register
    result.address = base_addr + cpu.get_registers().Y;
    result.page_crossed = page_crossed(base_addr, result.address);
    
    return result;
}
