/*
 * NES GPU Batch - pybind11 Python Extension
 * Phase 7: Python interface for GpuMarioVecEnv
 *
 * Exposes NESBatchGpu C++ class to Python as 'nes_gpu.NESBatchGpu'.
 * Accepts/returns numpy uint8 arrays for zero-copy-friendly transfers.
 *
 * Build:  cd src/python && python setup.py build_ext --inplace
 * Import: import nes_gpu; batch = nes_gpu.NESBatchGpu(1000)
 */

// pybind11 and numpy — included BEFORE any CUDA-specific headers
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

// NES GPU batch API (has __global__ forward decls, requires nvcc)
#include "host/nes_batch_gpu.h"

namespace py = pybind11;

// Helper: convert python bytes → vector<uint8_t>
static std::vector<uint8_t> bytes_to_vec(const py::bytes& b) {
    std::string s(b);
    return std::vector<uint8_t>(s.begin(), s.end());
}

PYBIND11_MODULE(nes_gpu, m) {
    m.doc() = "NES GPU Batch Emulator — Phase 7 Python bindings (pybind11)";

    py::class_<NESBatchGpu>(m, "NESBatchGpu",
        "Runs N independent NES instances in parallel on the GPU.\n\n"
        "Typical RL workflow:\n"
        "  batch = NESBatchGpu(1000)\n"
        "  batch.load_rom(prg_bytes, chr_bytes)\n"
        "  batch.reset_all()\n"
        "  for step in range(T):\n"
        "      batch.set_buttons_batch(actions_u8)  # shape [N]\n"
        "      batch.run_frame_all()\n"
        "      obs = batch.get_obs_batch()           # shape [N,84,84] uint8\n"
        "      ram = batch.get_ram_batch()           # shape [N,2048] uint8\n")

        // Constructor
        .def(py::init<int>(), py::arg("num_instances"),
             "Create a batch emulator with num_instances parallel NES instances.")

        // ROM loading
        .def("load_rom",
             [](NESBatchGpu& self, py::bytes prg, py::bytes chr) {
                 auto prg_v = bytes_to_vec(prg);
                 auto chr_v = bytes_to_vec(chr);
                 self.load_rom(prg_v.data(), (uint32_t)prg_v.size(),
                               chr_v.data(), (uint32_t)chr_v.size());
             },
             py::arg("prg_data"), py::arg("chr_data"),
             "Load PRG and CHR ROM data (bytes objects from reading the ROM file).")

        // Reset
        .def("reset_all",
             [](NESBatchGpu& self, uint8_t mirroring) {
                 self.reset_all(mirroring);
             },
             py::arg("mirroring") = 0,
             "Reset all instances. mirroring: 0=horizontal (SMB), 1=vertical.")

        // Run frames
        .def("run_frame_all", &NESBatchGpu::run_frame_all,
             "Run exactly one NES frame for all instances in parallel.")

        .def("run_frames_all", &NESBatchGpu::run_frames_all,
             py::arg("num_frames"),
             "Run num_frames NES frames for all instances (no host sync between frames).")

        // Rendering
        .def("set_rendering_enabled", &NESBatchGpu::set_rendering_enabled,
             py::arg("enabled"),
             "Enable/disable PPU pixel rendering. Disable for reward-only loops (faster).")

        .def("rendering_enabled", &NESBatchGpu::rendering_enabled,
             "Return True if rendering is currently enabled.")

        // ---- Phase 7: RL interface ----

        .def("set_buttons_batch",
             [](NESBatchGpu& self, py::array_t<uint8_t, py::array::c_style> arr) {
                 auto info = arr.request();
                 self.set_buttons_batch(static_cast<const uint8_t*>(info.ptr),
                                        (int)info.size);
             },
             py::arg("buttons"),
             "Set joypad state for all instances.\n"
             "buttons: uint8 array shape [N], bit layout A|B|Sel|Start|Up|Down|L|R.")

        .def("get_obs_batch",
             [](NESBatchGpu& self) {
                 int N = self.num_instances();
                 auto result = py::array_t<uint8_t>({N, 84, 84});
                 self.get_obs_batch(static_cast<uint8_t*>(result.request().ptr));
                 return result;
             },
             "Render N×84×84 grayscale observations (bilinear from 240×256).\n"
             "Returns uint8 numpy array shape [N, 84, 84]. Requires rendering enabled.")

        .def("get_ram_batch",
             [](NESBatchGpu& self) {
                 int N = self.num_instances();
                 auto result = py::array_t<uint8_t>({N, 2048});
                 self.get_ram_batch(static_cast<uint8_t*>(result.request().ptr));
                 return result;
             },
             "Copy all CPU RAM to host.\n"
             "Returns uint8 numpy array shape [N, 2048].\n"
             "Useful RAM addresses: $006D=page, $0086=x_offset, $075A=lives, $07D7=stage_clear.")

        .def("reset_selected",
             [](NESBatchGpu& self, py::array_t<uint8_t, py::array::c_style> done_mask) {
                 auto info = done_mask.request();
                 self.reset_selected(static_cast<const uint8_t*>(info.ptr),
                                     (int)info.size);
             },
             py::arg("done_mask"),
             "Reset only instances where done_mask[i] != 0.\n"
             "done_mask: uint8 array shape [N] (1=reset, 0=keep).")

        // Framebuffers (RGBA32 debug output)
        .def("get_framebuffers",
             [](NESBatchGpu& self) {
                 int N = self.num_instances();
                 auto result = py::array_t<uint32_t>({N, 240, 256});
                 self.get_framebuffers(static_cast<uint32_t*>(result.request().ptr));
                 return result;
             },
             "Get RGBA32 framebuffers. Returns uint32 array [N, 240, 256].")

        // Utilities
        .def("num_instances", &NESBatchGpu::num_instances,
             "Return number of NES instances in the batch.");

    // Mirroring mode constants
    m.attr("MIRROR_HORIZONTAL") = py::int_(MIRROR_HORIZONTAL);
    m.attr("MIRROR_VERTICAL")   = py::int_(MIRROR_VERTICAL);
    m.attr("MIRROR_SINGLE_A")   = py::int_(MIRROR_SINGLE_A);
    m.attr("MIRROR_SINGLE_B")   = py::int_(MIRROR_SINGLE_B);
    m.attr("MIRROR_FOUR_SCREEN") = py::int_(MIRROR_FOUR_SCREEN);
}
