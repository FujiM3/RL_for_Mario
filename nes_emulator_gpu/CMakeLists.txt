cmake_minimum_required(VERSION 3.16)

# Detect CUDA compiler before project() declaration
if(NOT DEFINED CMAKE_CUDA_COMPILER)
    find_program(NVCC_EXE nvcc PATHS /usr/local/cuda/bin)
    if(NVCC_EXE)
        set(CMAKE_CUDA_COMPILER ${NVCC_EXE})
    endif()
endif()

# Determine project languages
if(CMAKE_CUDA_COMPILER)
    project(NES_GPU_Emulator VERSION 0.1.0 LANGUAGES CXX CUDA)
else()
    project(NES_GPU_Emulator VERSION 0.1.0 LANGUAGES CXX)
endif()

# C++17 required
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# CUDA settings (Tesla V100: Compute Capability 7.0)
set(CMAKE_CUDA_STANDARD 14)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_ARCHITECTURES 70)

# Compiler flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra -pedantic")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -DDEBUG")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG -march=native")

# CUDA compiler flags
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xcompiler -Wall")
set(CMAKE_CUDA_FLAGS_DEBUG "-g -G -O0")
set(CMAKE_CUDA_FLAGS_RELEASE "-O3 -DNDEBUG")

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

# ============================================================================
# CUDA: Phase 3 GPU Single Instance
# ============================================================================

find_package(CUDAToolkit QUIET HINTS /usr/local/cuda)

if(CUDAToolkit_FOUND OR CMAKE_CUDA_COMPILER)
    message(STATUS "CUDA found: ${CUDAToolkit_VERSION} at ${CUDAToolkit_ROOT_DIR}")

    # Include directories for CUDA code
    set(CUDA_INCLUDE_DIRS
        ${PROJECT_SOURCE_DIR}/src/cuda
        ${PROJECT_SOURCE_DIR}/src/reference
    )

    # GPU library: host interface + kernels
    add_library(nes_gpu_lib STATIC
        src/cuda/host/nes_gpu.cu
        src/cuda/kernels/nes_frame_kernel.cu
    )
    target_include_directories(nes_gpu_lib PUBLIC ${CUDA_INCLUDE_DIRS})
    set_target_properties(nes_gpu_lib PROPERTIES
        CUDA_SEPARABLE_COMPILATION ON
    )
    if(CUDAToolkit_FOUND)
        target_link_libraries(nes_gpu_lib CUDA::cudart)
    else()
        target_link_libraries(nes_gpu_lib ${CUDA_LIBRARIES})
    endif()

    # CUDA integration tests
    if(EXISTS ${PROJECT_SOURCE_DIR}/tests/cuda/test_gpu_single.cu)
        add_executable(nes_gpu_tests tests/cuda/test_gpu_single.cu)
        target_include_directories(nes_gpu_tests PRIVATE ${CUDA_INCLUDE_DIRS})
        set_target_properties(nes_gpu_tests PROPERTIES
            CUDA_SEPARABLE_COMPILATION ON
        )
        if(CUDAToolkit_FOUND)
            target_link_libraries(nes_gpu_tests nes_gpu_lib GTest::gtest_main CUDA::cudart)
        else()
            target_link_libraries(nes_gpu_tests nes_gpu_lib GTest::gtest_main ${CUDA_LIBRARIES})
        endif()
        gtest_discover_tests(nes_gpu_tests)
        message(STATUS "CUDA tests: enabled")
    endif()

    # GPU benchmark
    if(EXISTS ${PROJECT_SOURCE_DIR}/benchmarks/bench_gpu_single.cu)
        add_executable(bench_gpu_single benchmarks/bench_gpu_single.cu)
        target_include_directories(bench_gpu_single PRIVATE ${CUDA_INCLUDE_DIRS})
        set_target_properties(bench_gpu_single PROPERTIES
            CUDA_SEPARABLE_COMPILATION ON
        )
        if(CUDAToolkit_FOUND)
            target_link_libraries(bench_gpu_single nes_gpu_lib CUDA::cudart)
        else()
            target_link_libraries(bench_gpu_single nes_gpu_lib ${CUDA_LIBRARIES})
        endif()
        message(STATUS "GPU benchmark: enabled")
    endif()

    # ============================================================================
    # CUDA: Phase 4 GPU Batch Parallel
    # ============================================================================

    # Batch GPU library: adds batch kernels + host class
    add_library(nes_gpu_batch_lib STATIC
        src/cuda/host/nes_batch_gpu.cu
        src/cuda/kernels/nes_batch_kernel.cu
    )
    target_include_directories(nes_gpu_batch_lib PUBLIC ${CUDA_INCLUDE_DIRS})
    set_target_properties(nes_gpu_batch_lib PROPERTIES
        CUDA_SEPARABLE_COMPILATION ON
    )
    if(CUDAToolkit_FOUND)
        target_link_libraries(nes_gpu_batch_lib CUDA::cudart)
    else()
        target_link_libraries(nes_gpu_batch_lib ${CUDA_LIBRARIES})
    endif()

    # Batch GPU tests
    if(EXISTS ${PROJECT_SOURCE_DIR}/tests/cuda/test_gpu_batch.cu)
        add_executable(nes_gpu_batch_tests tests/cuda/test_gpu_batch.cu)
        target_include_directories(nes_gpu_batch_tests PRIVATE ${CUDA_INCLUDE_DIRS})
        set_target_properties(nes_gpu_batch_tests PROPERTIES
            CUDA_SEPARABLE_COMPILATION ON
        )
        if(CUDAToolkit_FOUND)
            target_link_libraries(nes_gpu_batch_tests nes_gpu_batch_lib GTest::gtest_main CUDA::cudart)
        else()
            target_link_libraries(nes_gpu_batch_tests nes_gpu_batch_lib GTest::gtest_main ${CUDA_LIBRARIES})
        endif()
        gtest_discover_tests(nes_gpu_batch_tests)
        message(STATUS "CUDA batch tests: enabled")
    endif()

    # Batch GPU benchmark
    if(EXISTS ${PROJECT_SOURCE_DIR}/benchmarks/bench_gpu_batch.cu)
        add_executable(bench_gpu_batch benchmarks/bench_gpu_batch.cu)
        target_include_directories(bench_gpu_batch PRIVATE ${CUDA_INCLUDE_DIRS})
        set_target_properties(bench_gpu_batch PROPERTIES
            CUDA_SEPARABLE_COMPILATION ON
        )
        if(CUDAToolkit_FOUND)
            target_link_libraries(bench_gpu_batch nes_gpu_batch_lib CUDA::cudart)
        else()
            target_link_libraries(bench_gpu_batch nes_gpu_batch_lib ${CUDA_LIBRARIES})
        endif()
        message(STATUS "GPU batch benchmark: enabled")
    endif()

else()
    message(STATUS "CUDA not found - skipping GPU targets")
endif()

# ============================================================================
# Print configuration
# ============================================================================
message(STATUS "=== NES GPU Emulator Configuration ===")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ compiler: ${CMAKE_CXX_COMPILER}")
message(STATUS "C++ standard: C++${CMAKE_CXX_STANDARD}")
message(STATUS "CUDA found: ${CUDAToolkit_FOUND}")
if(CUDAToolkit_FOUND)
    message(STATUS "CUDA version: ${CUDAToolkit_VERSION}")
    message(STATUS "CUDA architectures: ${CMAKE_CUDA_ARCHITECTURES}")
endif()
message(STATUS "====================================")
