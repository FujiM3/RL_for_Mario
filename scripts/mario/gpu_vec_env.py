"""
scripts/mario/gpu_vec_env.py

GPU-accelerated vectorized Super Mario Bros environment — Phase 7.

Replaces MarioVecEnv (nes_py CPU, 252 SPS × 16 envs) with a CUDA batch
emulator capable of 1000+ parallel instances on a single GPU.

Interface is compatible with MarioVecEnv:
  env = GpuMarioVecEnv(num_envs=1000)
  obs = env.reset()                     # (N, 4, 84, 84) uint8
  obs, rew, done, info = env.step(a)    # a: (N,) int, 7 actions (SIMPLE_MOVEMENT)
  env.close()

Key differences from MarioVecEnv:
  - All NES simulation runs on GPU (one CUDA thread per instance)
  - No subprocess overhead — observations fetched with cudaMemcpy
  - Frame stack of 4 implemented in host numpy (4 × N × 84 × 84 uint8)
  - Default frame skip: 4 (matches nes_py wrappers)
  - Reward = x-position delta / 40; death = -15; flag = +15
  - Done on: lives < initial_lives OR stage_clear_flag set
  - Stage always World 1-1 (ROM reset vector default)

SIMPLE_MOVEMENT joypad bitmask (bit layout: A|B|Sel|Start|Up|Down|L|R):
  0: []                  → 0x00
  1: ['right']           → 0x80
  2: ['right', 'A']      → 0x81
  3: ['right', 'B']      → 0x82
  4: ['right', 'A', 'B'] → 0x83
  5: ['A']               → 0x01
  6: ['left']            → 0x40

Mario RAM addresses used:
  $006D: page number (high byte of x-position)
  $0086: x-offset within page (low byte of x-position)
  $075A: lives (initial value varies; we track delta)
  $07D7: stage clear flag (0x80 when cleared)
"""

import os
import sys
import struct
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import numpy as np

# GPU emulator Python extension
# The .so is built in nes_emulator_gpu/src/python/ — add to sys.path
_NES_GPU_PY_DIR = Path(__file__).parent.parent.parent / "nes_emulator_gpu" / "src" / "python"
if str(_NES_GPU_PY_DIR) not in sys.path:
    sys.path.insert(0, str(_NES_GPU_PY_DIR))

try:
    import nes_gpu
except ImportError as e:
    raise ImportError(
        f"Could not import nes_gpu extension ({e}).\n"
        f"Build it first:\n"
        f"  cd {_NES_GPU_PY_DIR}\n"
        f"  python setup.py\n"
    ) from e

# ---------------------------------------------------------------------------
# ROM Loading
# ---------------------------------------------------------------------------

# Standard SMB ROM location from gym-super-mario-bros installation
_SMB_ROM_DEFAULT = (
    Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages" / "gym_super_mario_bros" / "_roms" / "super-mario-bros.nes"
)

def _load_nes_rom(rom_path: Optional[str] = None) -> Tuple[bytes, bytes, int]:
    """
    Parse iNES ROM file → (prg_data, chr_data, mirroring).

    Args:
        rom_path: path to .nes file; auto-detects gym-super-mario-bros if None.

    Returns:
        prg_data:  PRG ROM bytes
        chr_data:  CHR ROM bytes
        mirroring: MIRROR_HORIZONTAL(0) or MIRROR_VERTICAL(1)
    """
    if rom_path is None:
        # Try venv site-packages
        candidates = [
            _SMB_ROM_DEFAULT,
            Path(__file__).parent.parent.parent / "roms" / "super-mario-bros.nes",
        ]
        # Also search venv relative to python executable
        venv_rom = Path(sys.executable).parent.parent / "lib" / \
                   f"python{sys.version_info.major}.{sys.version_info.minor}" / \
                   "site-packages" / "gym_super_mario_bros" / "_roms" / "super-mario-bros.nes"
        candidates.append(venv_rom)
        for cand in candidates:
            if cand.exists():
                rom_path = str(cand)
                break
        if rom_path is None:
            raise FileNotFoundError(
                "super-mario-bros.nes not found. Install gym-super-mario-bros or pass rom_path."
            )

    with open(rom_path, "rb") as f:
        data = f.read()

    if data[:4] != b"NES\x1a":
        raise ValueError(f"{rom_path} is not a valid iNES ROM (missing header magic)")

    prg_banks = data[4]   # 16KB units
    chr_banks = data[5]   # 8KB units
    flags6    = data[6]
    mirroring = int(flags6 & 1)  # bit0: 0=horizontal, 1=vertical

    header_size = 16
    trainer_size = 512 if (flags6 & 0x04) else 0
    prg_offset = header_size + trainer_size
    prg_size = prg_banks * 16384
    chr_size = chr_banks * 8192

    prg_data = data[prg_offset: prg_offset + prg_size]
    chr_data = data[prg_offset + prg_size: prg_offset + prg_size + chr_size]
    return bytes(prg_data), bytes(chr_data), mirroring

# ---------------------------------------------------------------------------
# SIMPLE_MOVEMENT → joypad bitmask
# ---------------------------------------------------------------------------

# Joypad bit layout: A=0, B=1, Sel=2, Start=3, Up=4, Down=5, Left=6, Right=7
_SIMPLE_MOVEMENT_BITMASK = np.array([
    0x00,  # 0: [] (no-op)
    0x80,  # 1: right
    0x81,  # 2: right + A
    0x82,  # 3: right + B
    0x83,  # 4: right + A + B
    0x01,  # 5: A
    0x40,  # 6: left
], dtype=np.uint8)

NUM_ACTIONS = len(_SIMPLE_MOVEMENT_BITMASK)  # 7

# ---------------------------------------------------------------------------
# Title skip boot constants
# ---------------------------------------------------------------------------
# From power-on, each instance needs ~286 NES frames before gameplay begins:
#   Phase 1 (frames 0-35):  alternate START/NO-BTN → game timer starts at ~frame 32
#   Phase 2 (frames 36-285): NO-BTN → world-display countdown finishes, Mario drops in
#
# boot_frames counts DOWN from BOOT_FRAMES_TOTAL → 0.
# Instances with boot_frames > 0 are "booting" and receive overridden buttons.
_BOOT_FRAMES_TOTAL  = 286  # total frames from power-on to ready
_BOOT_FRAMES_SETTLE = 250  # boot_frames threshold: above → phase 1 (START), at/below → phase 2 (NO-BTN)
_START_BTN          = np.uint8(0x08)   # joypad START bit

# ---------------------------------------------------------------------------
# RAM address constants
# ---------------------------------------------------------------------------
_RAM_PAGE        = 0x006D   # x-scroll page (high byte)
_RAM_X_OFFSET    = 0x0086   # x offset within page
_RAM_LIVES       = 0x075A   # Mario lives
_RAM_STAGE_CLEAR = 0x07D7   # stage clear flag (0x80 = cleared)

# ---------------------------------------------------------------------------
# GpuMarioVecEnv
# ---------------------------------------------------------------------------

class GpuMarioVecEnv:
    """
    GPU-accelerated vectorized Super Mario Bros environment.

    Runs N NES instances in parallel on the GPU. Orders of magnitude faster
    than MarioVecEnv (nes_py) for large N.

    Args:
        num_envs:     number of parallel NES instances
        rom_path:     path to super-mario-bros.nes (auto-detected if None)
        frame_skip:   NES frames per RL step (default: 4)
        frame_stack:  frames to stack as observation (default: 4)
        render:       if True, allocate GPU framebuffer for pixel data
    """

    def __init__(
        self,
        num_envs: int = 1000,
        rom_path: Optional[str] = None,
        frame_skip: int = 4,
        frame_stack: int = 4,
        render: bool = True,
    ):
        self.num_envs   = num_envs
        self.frame_skip  = frame_skip
        self.frame_stack = frame_stack

        # Load ROM
        prg_data, chr_data, mirroring = _load_nes_rom(rom_path)

        # Create GPU batch emulator
        self._mirroring = mirroring  # stored for use in reset()
        self._batch = nes_gpu.NESBatchGpu(num_envs)
        self._batch.load_rom(prg_data, chr_data)
        self._batch.set_rendering_enabled(render)
        # Note: reset_all is called inside reset() along with the title skip

        # Frame stack buffer: (frame_stack, N, 84, 84) uint8
        self._frame_buf = np.zeros(
            (frame_stack, num_envs, 84, 84), dtype=np.uint8
        )

        # Per-instance tracking
        self._prev_x      = np.zeros(num_envs, dtype=np.int32)
        self._init_lives  = np.zeros(num_envs, dtype=np.int32)
        self._boot_frames = np.zeros(num_envs, dtype=np.int32)  # >0 = booting

        # Gym-style space info
        self.observation_space_shape = (frame_stack, 84, 84)
        self.action_space_n = NUM_ACTIONS

        print(
            f"[GpuVecEnv] Created {num_envs} GPU NES instances | "
            f"obs: {self.observation_space_shape} | "
            f"actions: {NUM_ACTIONS} (SIMPLE_MOVEMENT)"
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_obs_and_ram(self) -> Tuple[np.ndarray, np.ndarray]:
        """Fetch one obs frame + RAM from GPU."""
        obs_frame = self._batch.get_obs_batch()   # (N, 84, 84) uint8
        ram       = self._batch.get_ram_batch()   # (N, 2048) uint8
        return obs_frame, ram

    def _extract_x_pos(self, ram: np.ndarray) -> np.ndarray:
        """x-position = page * 256 + x_offset."""
        return (ram[:, _RAM_PAGE].astype(np.int32) * 256
                + ram[:, _RAM_X_OFFSET].astype(np.int32))

    def _extract_lives(self, ram: np.ndarray) -> np.ndarray:
        return ram[:, _RAM_LIVES].astype(np.int32)

    def _extract_stage_clear(self, ram: np.ndarray) -> np.ndarray:
        return (ram[:, _RAM_STAGE_CLEAR] == 0x80)

    def _push_frame(self, obs_frame: np.ndarray) -> None:
        """Push new frame into stack (oldest frame dropped)."""
        # frame_buf[0] = oldest, frame_buf[-1] = newest
        self._frame_buf = np.roll(self._frame_buf, shift=-1, axis=0)
        self._frame_buf[-1] = obs_frame  # (N, 84, 84)

    def _stacked_obs(self) -> np.ndarray:
        """Return (N, frame_stack, 84, 84) uint8 — current frame stack."""
        # frame_buf is (frame_stack, N, H, W); transpose to (N, frame_stack, H, W)
        return self._frame_buf.transpose(1, 0, 2, 3).copy()

    # ── Public interface ──────────────────────────────────────────────────────

    def reset(self) -> np.ndarray:
        """
        Reset all instances, run title skip, and return initial observations.

        Runs _BOOT_FRAMES_TOTAL NES frames to skip the title/world-display screens
        so that all instances start in live gameplay. This takes ~9 seconds for
        N=2048 but is called only once per training run.

        Returns:
            obs: (N, frame_stack, 84, 84) uint8
        """
        self._batch.reset_all(self._mirroring)
        self._boot_frames[:] = 0

        N = self.num_envs
        start_arr = np.full(N, _START_BTN, dtype=np.uint8)
        no_btn    = np.zeros(N, dtype=np.uint8)

        # Phase 1: 36 frames of alternating START/NO-BTN  (timer starts ~frame 32)
        for f in range(_BOOT_FRAMES_TOTAL - _BOOT_FRAMES_SETTLE):
            btn = start_arr if (f % 4 < 2) else no_btn
            self._batch.set_buttons_batch(btn)
            self._batch.run_frame_all()

        # Phase 2: _BOOT_FRAMES_SETTLE frames of NO-BTN  (world display counts down)
        # Use run_frames_all to avoid per-frame sync overhead where possible.
        self._batch.set_buttons_batch(no_btn)
        self._batch.run_frames_all(_BOOT_FRAMES_SETTLE)

        # Fetch observation + RAM after skip
        obs_frame, ram = self._get_obs_and_ram()
        self._frame_buf[:] = obs_frame[np.newaxis]  # broadcast to all stack slots
        self._prev_x      = self._extract_x_pos(ram)
        self._init_lives  = self._extract_lives(ram)

        return self._stacked_obs()

    def step(
        self, actions: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        """
        Step all instances with given actions.

        Booting instances (recently reset) automatically receive START/NO-BTN
        overrides until their title skip completes.

        Args:
            actions: (N,) int array of SIMPLE_MOVEMENT indices (0–6)

        Returns:
            obs:     (N, 4, 84, 84) uint8 — stacked grayscale observations
            rewards: (N,) float32
            dones:   (N,) bool
            infos:   list of N dicts
        """
        actions    = np.asarray(actions, dtype=np.int32)
        player_btn = _SIMPLE_MOVEMENT_BITMASK[actions]  # (N,) uint8

        prev_boot = self._boot_frames.copy()

        # Compute effective buttons for this step (once per step, not per-frame).
        # Booting instances get START (phase 1) or NO-BTN (phase 2) overrides.
        eff_buttons = player_btn.copy()
        booting = self._boot_frames > 0
        if booting.any():
            phase1 = booting & (self._boot_frames > _BOOT_FRAMES_SETTLE)
            eff_buttons[phase1]  = _START_BTN      # title screen: press START
            eff_buttons[booting & ~phase1] = np.uint8(0x00)  # settle: no button

        self._batch.set_buttons_batch(eff_buttons)  # single CUDA upload per step

        # Run all frame_skip NES frames in a single kernel launch (1 sync instead of 4)
        self._batch.run_frames_all(self.frame_skip)

        # Advance boot counters (decrement by frame_skip, clamp to 0)
        if booting.any():
            self._boot_frames[booting] = np.maximum(
                0, self._boot_frames[booting] - self.frame_skip
            )

        # Get observation + RAM
        obs_frame, ram = self._get_obs_and_ram()
        self._push_frame(obs_frame)

        cur_x       = self._extract_x_pos(ram)
        cur_lives   = self._extract_lives(ram)
        stage_clear = self._extract_stage_clear(ram)

        # Instances that just finished booting — initialise their tracking
        just_ready = (prev_boot > 0) & (self._boot_frames <= 0)
        if just_ready.any():
            self._init_lives[just_ready] = cur_lives[just_ready]
            self._prev_x[just_ready]     = cur_x[just_ready]

        # Done detection — suppress for booting instances
        booting = self._boot_frames > 0
        died        = (cur_lives < self._init_lives) & ~booting
        stage_clear = stage_clear & ~booting
        dones       = died | stage_clear

        # Compute rewards (0 for booting instances — no meaningful x progress yet)
        x_delta  = (cur_x - self._prev_x).astype(np.float32)
        x_delta[booting] = 0.0
        rewards  = x_delta / 40.0
        rewards[died]        -= 15.0
        rewards[stage_clear] += 15.0

        # Build infos
        infos = [
            {
                "x_pos":    int(cur_x[i]),
                "lives":    int(cur_lives[i]),
                "flag_get": bool(stage_clear[i]),
            }
            for i in range(self.num_envs)
        ]

        # Auto-reset done instances — they enter the boot sequence
        if dones.any():
            done_mask = dones.astype(np.uint8)
            self._batch.reset_selected(done_mask)
            self._boot_frames[dones] = _BOOT_FRAMES_TOTAL
            # Reset tracking; init_lives will be set when boot completes
            self._prev_x[dones] = 0

        # Update x tracking for active (non-booting, non-done) instances
        active = ~booting & ~dones
        self._prev_x[active] = cur_x[active]

        return self._stacked_obs(), rewards.astype(np.float32), dones, infos

    def close(self) -> None:
        """Release GPU resources."""
        del self._batch
        print(f"[GpuVecEnv] Closed {self.num_envs} GPU instances.")

    def __len__(self) -> int:
        return self.num_envs

    def __repr__(self) -> str:
        return f"GpuMarioVecEnv(num_envs={self.num_envs}, frame_skip={self.frame_skip})"


# ---------------------------------------------------------------------------
# Episode-tracking stats wrapper (for training loop compatibility)
# ---------------------------------------------------------------------------

class GpuMarioVecEnvStats:
    """
    Wraps GpuMarioVecEnv with per-episode reward and length tracking.

    Adds ``info["episode"] = {"r": float, "l": int, "flag_get": bool}`` to the
    info dict of every instance whose episode ends in a given step.  This
    matches the interface expected by ``train_ppo_finetune.py`` (originally
    written for MarioVecEnv / RecordEpisodeStatistics).

    All other attributes and methods are forwarded transparently.
    """

    def __init__(self, *args, **kwargs):
        self._env = GpuMarioVecEnv(*args, **kwargs)
        self.num_envs                 = self._env.num_envs
        self.observation_space_shape  = self._env.observation_space_shape
        self.action_space_n           = self._env.action_space_n
        self.frame_skip               = self._env.frame_skip
        self.frame_stack              = self._env.frame_stack

        # Cumulative accumulators — reset on episode end (matching done=True)
        self._ep_rewards = np.zeros(self.num_envs, dtype=np.float64)
        self._ep_lengths = np.zeros(self.num_envs, dtype=np.int32)

    def reset(self) -> np.ndarray:
        self._ep_rewards[:] = 0.0
        self._ep_lengths[:] = 0
        return self._env.reset()

    def step(
        self, actions: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        obs, rewards, dones, infos = self._env.step(actions)

        self._ep_rewards += rewards
        self._ep_lengths += 1

        for i in range(self.num_envs):
            if dones[i]:
                infos[i]["episode"] = {
                    "r":        float(self._ep_rewards[i]),
                    "l":        int(self._ep_lengths[i]),
                    "flag_get": infos[i]["flag_get"],
                }
                self._ep_rewards[i] = 0.0
                self._ep_lengths[i] = 0

        return obs, rewards, dones, infos

    def close(self) -> None:
        self._env.close()

    def __len__(self) -> int:
        return self.num_envs

    def __repr__(self) -> str:
        return f"GpuMarioVecEnvStats({self._env!r})"


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import time

    print("=== GpuMarioVecEnv Smoke Test ===")
    env = GpuMarioVecEnv(num_envs=100)

    print("\nReset (runs title skip — ~9s for N=2048, faster for N=100)...")
    t_reset = time.time()
    obs = env.reset()
    print(f"  Reset done in {time.time()-t_reset:.1f}s")
    print(f"  obs.shape = {obs.shape}, dtype = {obs.dtype}")

    print("\nRunning 200 random steps...")
    t0 = time.time()
    total_done = 0
    for step in range(200):
        actions = np.random.randint(0, NUM_ACTIONS, size=env.num_envs)
        obs, rewards, dones, infos = env.step(actions)
        total_done += dones.sum()
        if step % 50 == 0:
            print(f"  Step {step:3d}: obs={obs.shape} max_x={max(i['x_pos'] for i in infos):4d} "
                  f"dones={dones.sum()}")

    elapsed = time.time() - t0
    fps = 200 * env.num_envs * env.frame_skip / elapsed
    print(f"\n200 steps × {env.num_envs} envs × {env.frame_skip} frame_skip in {elapsed:.2f}s")
    print(f"NES frames/s: {fps:.0f}  (nes_py baseline ~4000)")
    print(f"Total episodes: {total_done}")

    env.close()
    print("\nSMOKE TEST PASSED")
