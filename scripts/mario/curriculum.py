"""
scripts/mario/curriculum.py

课程学习调度器：管理训练阶段和关卡池的自动切换。

三个阶段：
  Phase 0: World 1（4 个关卡）       ← 热身，快速收敛
  Phase 1: World 1-4（16 个关卡）    ← 扩展泛化
  Phase 2: World 1-8（32 个关卡）    ← 全量泛化

升阶条件：
  当前阶段的最近 N 局平均通关率 >= threshold 时自动升阶

使用方法:
  scheduler = CurriculumScheduler()
  world, stage = scheduler.sample_level()
  scheduler.record_episode(flag_get=True)
  if scheduler.should_advance():
      scheduler.advance()
      new_pool = scheduler.current_pool
"""

import random
import collections
from typing import List, Tuple, Optional


# ── 关卡池定义 ────────────────────────────────────────────────────────────────

PHASE_POOLS: List[List[Tuple[int, int]]] = [
    # Phase 0: World 1 only
    [(1, 1), (1, 2), (1, 3), (1, 4)],

    # Phase 1: World 1-4
    [(w, s) for w in range(1, 5) for s in range(1, 5)],

    # Phase 2: All worlds (World 1-8，每世界 4 关)
    [(w, s) for w in range(1, 9) for s in range(1, 5)],
]

PHASE_NAMES = [
    "Phase 0 - World 1 only (warm-up)",
    "Phase 1 - World 1-4 (expansion)",
    "Phase 2 - World 1-8 (full generalization)",
]


# ── Curriculum Scheduler ──────────────────────────────────────────────────────

class CurriculumScheduler:
    """
    课程学习调度器。

    Args:
        advance_threshold:  升阶所需的最低平均通关率 (默认 0.6 = 60%)
        window_size:        滑动窗口大小，用于计算平均通关率 (默认 200 局)
        initial_phase:      起始阶段 (默认 0)
        min_episodes:       升阶前至少需要完成的 episode 数 (防止过早升阶)
    """

    def __init__(
        self,
        advance_threshold: float = 0.6,
        window_size: int = 200,
        initial_phase: int = 0,
        min_episodes: int = 500,
    ):
        self.advance_threshold = advance_threshold
        self.window_size = window_size
        self.phase = initial_phase
        self.min_episodes = min_episodes

        # 每个阶段独立的滑动窗口（存 0/1 表示失败/通关）
        self._windows = [
            collections.deque(maxlen=window_size)
            for _ in range(len(PHASE_POOLS))
        ]

        # 统计信息
        self.total_episodes = 0
        self.phase_episodes = 0   # 当前阶段已完成的 episode 数

    # ── 关卡采样 ──────────────────────────────────────────────────────────────

    @property
    def current_pool(self) -> List[Tuple[int, int]]:
        return PHASE_POOLS[self.phase]

    def sample_level(self) -> Tuple[int, int]:
        """从当前阶段的关卡池中均匀随机采样一个 (world, stage)。"""
        return random.choice(self.current_pool)

    # ── Episode 记录 ──────────────────────────────────────────────────────────

    def record_episode(self, flag_get: bool) -> None:
        """
        记录一局游戏结果。

        Args:
            flag_get: 是否通关（插到旗杆）
        """
        self._windows[self.phase].append(1 if flag_get else 0)
        self.total_episodes += 1
        self.phase_episodes += 1

    # ── 升阶逻辑 ─────────────────────────────────────────────────────────────

    @property
    def current_clear_rate(self) -> float:
        """当前阶段滑动窗口内的通关率。"""
        w = self._windows[self.phase]
        if not w:
            return 0.0
        return sum(w) / len(w)

    def should_advance(self) -> bool:
        """
        是否应该升阶。

        条件：
          1. 不是最后阶段
          2. 当前阶段已完成 min_episodes 局
          3. 滑动窗口满（已收集足够样本）
          4. 平均通关率 >= advance_threshold
        """
        if self.phase >= len(PHASE_POOLS) - 1:
            return False
        if self.phase_episodes < self.min_episodes:
            return False
        if len(self._windows[self.phase]) < self.window_size:
            return False
        return self.current_clear_rate >= self.advance_threshold

    def advance(self) -> int:
        """
        升阶到下一个课程阶段。

        Returns:
            新的阶段编号
        """
        if self.phase >= len(PHASE_POOLS) - 1:
            print("[Curriculum] Already at final phase, no advancement.")
            return self.phase

        old_phase = self.phase
        self.phase += 1
        self.phase_episodes = 0

        print(
            f"\n[Curriculum] *** PHASE ADVANCED ***\n"
            f"  {PHASE_NAMES[old_phase]}  →  {PHASE_NAMES[self.phase]}\n"
            f"  Clear rate that triggered: {self.current_clear_rate:.1%}\n"
            f"  New level pool size: {len(self.current_pool)}\n"
        )
        return self.phase

    def try_advance(self) -> bool:
        """检查并自动升阶，返回是否发生了升阶。"""
        if self.should_advance():
            self.advance()
            return True
        return False

    # ── 状态查询 ─────────────────────────────────────────────────────────────

    def status(self) -> str:
        window_size = len(self._windows[self.phase])
        return (
            f"Phase {self.phase}/{len(PHASE_POOLS)-1} | "
            f"{PHASE_NAMES[self.phase]} | "
            f"Clear rate: {self.current_clear_rate:.1%} "
            f"({window_size}/{self.window_size} samples) | "
            f"Phase episodes: {self.phase_episodes} | "
            f"Total: {self.total_episodes}"
        )

    def state_dict(self) -> dict:
        """保存调度器状态（用于 checkpoint）。"""
        return {
            "phase": self.phase,
            "total_episodes": self.total_episodes,
            "phase_episodes": self.phase_episodes,
            "windows": [list(w) for w in self._windows],
        }

    def load_state_dict(self, d: dict) -> None:
        """恢复调度器状态（从 checkpoint 加载时使用）。"""
        self.phase = d["phase"]
        self.total_episodes = d["total_episodes"]
        self.phase_episodes = d["phase_episodes"]
        for i, window_data in enumerate(d.get("windows", [])):
            self._windows[i] = collections.deque(
                window_data, maxlen=self.window_size
            )
        print(f"[Curriculum] Loaded state: {self.status()}")


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sched = CurriculumScheduler(
        advance_threshold=0.6,
        window_size=10,       # 测试用小窗口
        min_episodes=10,
    )

    print("初始状态:", sched.status())
    print("样本关卡:", [sched.sample_level() for _ in range(5)])

    # 模拟高通关率
    for i in range(15):
        sched.record_episode(flag_get=(i % 10 != 0))  # 90% 通关

    print("\n记录 15 局后:")
    print(sched.status())
    print("应该升阶?", sched.should_advance())
    advanced = sched.try_advance()
    print("已升阶:", advanced)
    print("新阶段:", sched.status())
    print("新关卡池大小:", len(sched.current_pool))