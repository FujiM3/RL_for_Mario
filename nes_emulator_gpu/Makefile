# Makefile for NES GPU Emulator
# Simple wrapper around CMake for convenience

BUILD_DIR := build
BUILD_TYPE ?= Debug

.PHONY: all configure build test clean help

all: build

# Configure CMake
configure:
	@echo "=== Configuring CMake ($(BUILD_TYPE)) ==="
	@mkdir -p $(BUILD_DIR)
	@cd $(BUILD_DIR) && cmake -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) ..

# Build project
build: configure
	@echo "=== Building project ==="
	@cmake --build $(BUILD_DIR) -j$(shell nproc)

# Run tests
test: build
	@echo "=== Running tests ==="
	@cd $(BUILD_DIR) && ctest --output-on-failure

# Clean build artifacts
clean:
	@echo "=== Cleaning build directory ==="
	@rm -rf $(BUILD_DIR)

# Release build
release:
	@$(MAKE) BUILD_TYPE=Release build

# Install (future)
install: release
	@echo "=== Installing (not yet implemented) ==="

# Help
help:
	@echo "NES GPU Emulator Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  make          - Build project (debug mode)"
	@echo "  make release  - Build project (release mode)"
	@echo "  make test     - Run all tests"
	@echo "  make clean    - Clean build directory"
	@echo "  make help     - Show this help"
	@echo ""
	@echo "Variables:"
	@echo "  BUILD_TYPE    - Debug or Release (default: Debug)"
	@echo ""
	@echo "Examples:"
	@echo "  make BUILD_TYPE=Release build"
	@echo "  make test"
