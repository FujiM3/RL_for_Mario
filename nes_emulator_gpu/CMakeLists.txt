cmake_minimum_required(VERSION 3.14)
project(NES_GPU_Emulator VERSION 0.1.0 LANGUAGES CXX)

# C++17 required
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra -pedantic")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -DDEBUG")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG -march=native")

# Output directories
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# Include directories
include_directories(${PROJECT_SOURCE_DIR}/src/reference)

# Source files (will be populated as we implement)
set(CPU_SOURCES
    # src/reference/cpu/cpu_6502.cpp
    # src/reference/cpu/instructions.cpp
    # src/reference/cpu/addressing.cpp
    # src/reference/cpu/interrupts.cpp
)

set(COMMON_SOURCES
    # src/reference/common/memory.cpp
    # src/reference/common/mapper0.cpp
)

# CPU Reference Implementation Library
if(CPU_SOURCES)
    add_library(nes_cpu_ref STATIC ${CPU_SOURCES} ${COMMON_SOURCES})
    target_include_directories(nes_cpu_ref PUBLIC 
        ${PROJECT_SOURCE_DIR}/src/reference
        ${PROJECT_SOURCE_DIR}/src/reference/common
    )
else()
    # Create library with just the source files we have
    add_library(nes_cpu_ref STATIC 
        src/reference/cpu/cpu_6502.cpp
        src/reference/cpu/addressing.cpp
        src/reference/cpu/instructions.cpp
        src/reference/cpu/opcode_table.cpp
        src/reference/common/memory.cpp
        src/reference/common/mapper0.cpp
        src/reference/ppu/ppu.cpp
    )
    target_include_directories(nes_cpu_ref PUBLIC 
        ${PROJECT_SOURCE_DIR}/src/reference
        ${PROJECT_SOURCE_DIR}/src/reference/common
    )
endif()

# Google Test setup
include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
)
# For Windows: Prevent overriding the parent project's compiler/linker settings
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

# Enable testing
enable_testing()
include(GoogleTest)

# Unit tests (will be added as we implement)
set(TEST_SOURCES
    tests/unit/test_types.cpp
    tests/unit/test_cpu_registers.cpp
    tests/unit/test_cpu_6502.cpp
    tests/unit/test_addressing.cpp
    tests/unit/test_memory.cpp
    tests/unit/test_instructions.cpp
    tests/unit/test_ppu_registers.cpp
    tests/unit/test_background.cpp
    tests/unit/test_rendering_integration.cpp
    tests/unit/test_sprites.cpp
    tests/unit/test_scrolling.cpp
    tests/unit/test_scroll_rendering.cpp
)

# Create test executable when test sources exist
if(TEST_SOURCES)
    add_executable(nes_tests ${TEST_SOURCES})
    target_link_libraries(nes_tests 
        GTest::gtest_main
        GTest::gmock
    )
    
    # Link CPU library if it exists
    if(TARGET nes_cpu_ref)
        target_link_libraries(nes_tests nes_cpu_ref)
    endif()
    
    # Discover tests
    gtest_discover_tests(nes_tests)
endif()

# Print configuration
message(STATUS "=== NES GPU Emulator Configuration ===")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ compiler: ${CMAKE_CXX_COMPILER}")
message(STATUS "C++ standard: C++${CMAKE_CXX_STANDARD}")
message(STATUS "Compiler flags: ${CMAKE_CXX_FLAGS}")
message(STATUS "====================================")
