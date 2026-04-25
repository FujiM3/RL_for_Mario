#include <stdio.h>
#include <cuda_runtime.h>

__global__ void hello_kernel() {
    printf("Hello from GPU thread %d in block %d\n", threadIdx.x, blockIdx.x);
}

int main() {
    int device;
    cudaGetDevice(&device);
    
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, device);
    
    printf("=== CUDA Environment Test ===\n");
    printf("Device: %s\n", prop.name);
    printf("Compute Capability: %d.%d\n", prop.major, prop.minor);
    printf("Total Global Memory: %.2f GB\n", prop.totalGlobalMem / 1e9);
    printf("Multiprocessors: %d\n", prop.multiProcessorCount);
    printf("Max Threads per Block: %d\n", prop.maxThreadsPerBlock);
    printf("Warp Size: %d\n", prop.warpSize);
    
    printf("\nLaunching test kernel...\n");
    hello_kernel<<<2, 4>>>();
    cudaDeviceSynchronize();
    
    printf("\n✅ CUDA test passed!\n");
    return 0;
}
