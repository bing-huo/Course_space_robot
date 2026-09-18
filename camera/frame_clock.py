# -*- coding: utf-8 -*-
"""
FrameClock —— 统一时间基准（对应 P0.3.a）

────────────────────────────────────────────────────────────────
第一学期的写法是：

    curr_t = len(h_t) / real_fps

问题在于 h_t 只在**检测成功**时才 append。一旦丢帧或丢检测，
这个"时间"就停在原地、甚至倒退，速度会被算错——而速度正是本学期
两项考核指标里的一项。

本模块把时间来源集中到一处，三种来源任选：

    source="device"  相机硬件时间戳（最准，前提是相机支持）
    source="host"    主机 perf_counter()（默认，永远可用）
    source="file"    按文件帧率推算（**只用于 v1 素材回归测试**）

无论哪种来源，输出都保证**单调不减**，且丢帧时不会停住。
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

# 硬件时间戳可能的单位（秒），自检时在候选里取最近的一个
_TS_UNIT_CANDIDATES = (1e-9, 1e-6, 1e-3)

# 海康相机硬件时间戳的默认单位；单位测不出来时用它兜底
_DEFAULT_TS_UNIT_S = 1e-9


@dataclass
class ClockStats:
    """诊断信息，bench 与日志都用它。"""
    n_frames: int = 0
    frame_id_gaps: int = 0              # FrameID 跳变次数 ≈ 丢帧次数
    missing_frames: int = 0             # 累计丢了多少帧（按 FrameID 差值求和）
    non_monotonic: int = 0              # 时间戳回退次数
    ts_unit_s: Optional[float] = None   # 自检出的硬件时间戳单位

    @property
    def lost_ratio(self) -> float:
        """丢失帧占比 = 丢掉的帧数 / 本该有的帧数。"""
        expected = self.n_frames + self.missing_frames
        return self.missing_frames / expected if expected else 0.0

    def summary(self) -> str:
        unit = f"{self.ts_unit_s:.0e} s" if self.ts_unit_s else "未测定"
        return (f"帧数 {self.n_frames}｜丢帧 {self.missing_frames} 帧"
                f"（{self.lost_ratio * 100:.2f}%）｜时间戳回退 {self.non_monotonic} 次"
                f"｜硬件时间戳单位 {unit}")


class FrameClock:
    """帧时间基准。

    典型用法::

        clock = FrameClock(source="host")
        for frame in cam.frames():
            t = clock.tick(frame.frame_id, frame.device_ts)
            ...          # t 是秒，单调不减

    :param source:    "device" / "host" / "file"
    :param fps:       标称帧率。file 源必填；device 源用于反推时间戳单位
    :param ts_unit_s: 已知的硬件时间戳单位，给了就不自检
    """

    def __init__(self, source: str = "host", fps: Optional[float] = None,
                 ts_unit_s: Optional[float] = None) -> None:
        if source not in ("device", "host", "file"):
            raise ValueError(f"未知时间源：{source}")
        if source == "file" and not fps:
            raise ValueError("source='file' 必须给出 fps")

        self.source = source
        self.nominal_fps = fps

        self._ts_unit_s = ts_unit_s
        self._t0_perf: Optional[float] = None
        self._t0_device: Optional[int] = None
        self._last_device_ts: Optional[int] = None
        self._last_frame_id: Optional[int] = None
        self._last_t: float = -1.0

        self._device_deltas: Deque[int] = deque(maxlen=200)
        self.stats = ClockStats()

    # ------------------------------------------------------------ 内部

    def _resolve_unit(self) -> float:
        """从相邻帧的时间戳差值反推单位。

        不查手册也能定单位：若实测 200 fps（帧间隔 5 ms），而相邻两帧的
        时间戳原始差值是 5,000,000，那么单位就是纳秒。
        在候选单位里取最接近的一个，误差过大则退回默认值。
        """
        if self._ts_unit_s is not None:
            return self._ts_unit_s
        if not self._device_deltas or not self.nominal_fps:
            return _DEFAULT_TS_UNIT_S

        median_delta = statistics.median(self._device_deltas)
        if median_delta <= 0:
            return _DEFAULT_TS_UNIT_S

        seconds_per_tick = (1.0 / self.nominal_fps) / median_delta
        best = min(_TS_UNIT_CANDIDATES, key=lambda u: abs(u - seconds_per_tick))
        # 与候选单位差得太远，说明推论不可靠，别硬套
        if abs(best - seconds_per_tick) / best > 0.5:
            return _DEFAULT_TS_UNIT_S

        self._ts_unit_s = best
        self.stats.ts_unit_s = best
        return best

    def _record_device_delta(self, device_ts: int) -> None:
        if self._last_device_ts is not None:
            d = device_ts - self._last_device_ts
            if d > 0:
                self._device_deltas.append(d)
        self._last_device_ts = device_ts

    # ------------------------------------------------------------ 对外

    def tick(self, frame_id: Optional[int] = None,
             device_ts: Optional[int] = None) -> float:
        """推进一帧，返回该帧的时间（秒）。单调不减；丢帧不会让时间停住。"""
        self.stats.n_frames += 1

        # ---- 丢帧统计：FrameID 是唯一硬证据 ----
        if frame_id is not None:
            if self._last_frame_id is not None:
                gap = frame_id - self._last_frame_id - 1
                if gap > 0:
                    self.stats.frame_id_gaps += 1
                    self.stats.missing_frames += gap
            self._last_frame_id = frame_id

        # ---- 按时源取时间 ----
        if self.source == "device" and device_ts is not None:
            self._record_device_delta(device_ts)      # 先记差值，再定单位
            if self._t0_device is None:
                self._t0_device = device_ts
                if self.stats.ts_unit_s is None:
                    self.stats.ts_unit_s = self._ts_unit_s or _DEFAULT_TS_UNIT_S
            t = (device_ts - self._t0_device) * self._resolve_unit()

        elif self.source == "file":
            t = (self.stats.n_frames - 1) / float(self.nominal_fps)

        else:
            # host 源；device 源但该帧没带时间戳时也退到这里
            if self._t0_perf is None:
                self._t0_perf = time.perf_counter()
            t = time.perf_counter() - self._t0_perf

        # ---- 单调性保护：宁可可重复，也绝不倒退 ----
        if t < self._last_t:
            self.stats.non_monotonic += 1
            t = self._last_t
        self._last_t = t
        return t

    # ------------------------------------------------------------ 便捷

    @property
    def elapsed(self) -> float:
        """自起点以来的时长（秒）。"""
        return max(self._last_t, 0.0)

    def report(self) -> str:
        unit = f"，单位自检为 {self._ts_unit_s:.0e} s" if self._ts_unit_s else ""
        return f"[FrameClock/{self.source}{unit}] {self.stats.summary()}"


# ================================================================
# 自测：不依赖相机，直接 python -m camera.frame_clock 就能跑
# ================================================================

def _selftest() -> None:
    print("=== 场景 1：host 时间源，中途人为丢掉 30 帧 ===")
    clock = FrameClock(source="host")
    fid = 0
    last_t = 0.0
    for i in range(60):
        last_t = clock.tick(frame_id=fid)
        fid += 1
        if i == 20:
            fid += 30                     # 模拟丢帧
        time.sleep(0.001)
    print(clock.report())
    print(f"末帧时间 {last_t:.4f} s")
    print("期望：时间轴连续（不因丢帧停住），丢 30 帧被记下\n")

    print("=== 场景 2：device 时间源，纳秒单位，200 fps ===")
    clock = FrameClock(source="device", fps=200.0)
    ts = 1_000_000_000
    step = int(1e9 / 200.0)               # 5 ms = 5,000,000 ns
    last_t = 0.0
    for i in range(100):
        last_t = clock.tick(frame_id=i, device_ts=ts)
        ts += step
    print(clock.report())
    print(f"末帧时间 {last_t:.4f} s（期望 ≈ 0.4950 s）")
    print("期望：单位自检为 1e-09 s\n")

    print("=== 场景 3：file 时间源（v1 素材回归用，30 fps）===")
    clock = FrameClock(source="file", fps=30.0)
    for i in range(31):
        last_t = clock.tick(frame_id=i)
    print(f"第 31 帧 t = {last_t:.4f} s（期望 1.0000 s）\n")

    print("=== 场景 4：device 源但时间戳突然回退 ===")
    clock = FrameClock(source="device", fps=200.0)
    for i, ts in enumerate([1000, 1005, 1003, 1010]):
        last_t = clock.tick(frame_id=i, device_ts=ts * 1_000_000)
    print(f"末帧时间 {last_t:.6f} s，回退次数 {clock.stats.non_monotonic}")
    print("期望：回退 1 次，时间不倒退")


if __name__ == "__main__":
    _selftest()