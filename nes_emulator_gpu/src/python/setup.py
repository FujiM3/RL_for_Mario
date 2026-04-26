"""
Build script for the nes_gpu Python extension (Phase 7).

Usage:
    cd nes_emulator_gpu/src/python
    python build.py          (recommended — uses nvcc directly, avoids CUDA version checks)
    python setup.py build_ext --inplace  (requires matching CUDA/PyTorch versions)

The extension links against the pre-built libnes_gpu_batch_lib.a static library.
Run 'cmake --build build' in the nes_emulator_gpu/ directory first, then this script.
"""

import os
import sys
import subprocess
import shutil
import sysconfig
from pathlib import Path

HERE      = Path(__file__).parent.resolve()
EMU_ROOT  = (HERE / "../..").resolve()
BUILD_DIR = (EMU_ROOT / "build").resolve()
LIB_DIR   = (BUILD_DIR / "lib").resolve()

# Verify static library exists
lib_path = LIB_DIR / "libnes_gpu_batch_lib.a"
if not lib_path.exists():
    print(f"ERROR: {lib_path} not found.")
    print("Please run: cmake --build build --target nes_gpu_batch_lib")
    sys.exit(1)

# Find pybind11 headers (from torch installation)
try:
    import torch
    torch_inc = Path(torch.__file__).parent / "include"
except ImportError:
    print("ERROR: torch not found in the current Python environment.")
    sys.exit(1)

pybind11_inc = torch_inc  # pybind11/ subdir lives here

# Find Python include directory
python_inc = Path(sysconfig.get_paths()["include"])

# Find Python library directory (for libpython)
py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
python_lib_dir = Path(sysconfig.get_config_var("LIBDIR") or "")
# Prefer the lib dir next to the Python executable
venv_lib = Path(sys.executable).parent.parent / "lib"

# Extension output name
ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")  # e.g. .cpython-310-x86_64-linux-gnu.so
out_so = HERE / f"nes_gpu{ext_suffix}"

# Build command
cmd = [
    "nvcc",
    "-arch=sm_70",
    "-std=c++17",
    "-O2",
    "--compiler-options", "-fPIC",
    f"-I{pybind11_inc}",
    f"-I{python_inc}",
    f"-I{EMU_ROOT}",
    f"-I{EMU_ROOT / 'src' / 'cuda'}",
    "--shared",
    "-o", str(out_so),
    str(HERE / "nes_gpu_py.cu"),
    f"-L{LIB_DIR}", "-lnes_gpu_batch_lib",
]

# Add Python library
if python_lib_dir.exists():
    cmd += [f"-L{python_lib_dir}", f"-l{py_ver}"]

print("Building nes_gpu extension with nvcc:")
print("  Output:", out_so)
print()

result = subprocess.run(cmd)
if result.returncode != 0:
    print("Build failed.")
    sys.exit(1)
print(f"Build succeeded: {out_so}")
