#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""光源频闪测试（P3.2）

    python -m lighting.flicker_test                 # 3 ms × 100 帧
    python -m lighting.flicker_test -e 2000 -n 100  # 指定曝光
    python -m lighting.flicker_test --watch         # 连续报数，边调灯边看

判据（docs/光照系统要求与选型.md §2.1）：锁死曝光，空场景连拍 100 帧，
**帧间平均灰度极差 < 2 个灰度级**为通过；出现周期性波动即 PWM 频闪。

为什么必须测：LED 调光多是 PWM（几百 Hz ~ 几 kHz），快门不同步时帧间亮度剧烈
跳变，MOG2 会把整幅画面判成前景，检测失败率瞬间冲到接近 100%——现场看起来
像"算法彻底崩了"，根因却在灯上。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from camera.backend import open_camera

PASS_RANGE = 2.0          # 帧间极差判据（灰度级）


def grab_means(cam, n: int) -> tuple[np.ndarray, np.ndarray]:
    """连拍 n 帧，返回 (逐帧平均灰度, 逐帧过曝占比)。"""
    means, sats = [], []
    got = 0
    while got < n:
        f = cam.read()
        if f is None:
            continue
        g = f.image if f.image.ndim == 2 else cv2.cvtColor(f.image, cv2.COLOR_BGR2GRAY)
        means.append(float(g.mean()))
        sats.append(float((g > 250).mean() * 100))
        got += 1
    return np.array(means), np.array(sats)


def one_round(exposure_us: float, n: int, save: bool = True) -> int:
    cam = open_camera()
    cam.open()
    try:
        cam.set_exposure_us(exposure_us)
        for _ in range(15):                 # 丢掉曝光切换后的过渡帧
            cam.read()
        t0 = time.perf_counter()
        means, sats = grab_means(cam, n)
        dt = time.perf_counter() - t0

        frame = cam.read()                  # 存一张用于肉眼核对
        img = None if frame is None else frame.image
    finally:
        cam.close()

    rng = float(means.max() - means.min())
    passed = rng < PASS_RANGE
    print(f"曝光 {exposure_us:>6.0f} μs | {n} 帧 | 耗时 {dt:.2f} s "
          f"({n/dt:.0f} fps)")
    print(f"  平均灰度  {means.mean():6.1f}   P5 {np.percentile(means,5):5.1f} "
          f"P95 {np.percentile(means,95):5.1f}")
    print(f"  帧间极差  {rng:6.2f}（判据 < {PASS_RANGE:.0f}）  std {means.std():.3f}")
    print(f"  过曝占比  均值 {sats.mean():.2f}%   最大 {sats.max():.2f}%")
    print(f"  判定      {'✓ 通过（无可见频闪）' if passed else '⚠ 未通过（疑似 PWM/纹波频闪）'}")
    if means.mean() < 45:
        print("  ⚠ 画面偏暗（均值 < 45）：曝光太短或灯不够亮，检测会不稳")

    if save:
        out = Path("out")
        out.mkdir(exist_ok=True)
        tag = f"{exposure_us:.0f}us"
        if img is not None:
            path = out / f"flicker_{tag}.png"
            cv2.imwrite(str(path), img)
            print(f"  快照      {path}")
        csv_path = out / f"flicker_{tag}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frame", "mean_gray", "overexposed_pct"])
            for i, (m, s) in enumerate(zip(means, sats)):
                w.writerow([i, f"{m:.4f}", f"{s:.4f}"])
        print(f"  逐帧数据  {csv_path}")
    return 0 if passed else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="光源频闪测试")
    ap.add_argument("-e", "--exposure", type=float, default=3000.0,
                    help="曝光时间（μs），默认 3000（实验工作点）")
    ap.add_argument("-n", "--frames", type=int, default=100, help="帧数，判据用 100")
    ap.add_argument("--watch", action="store_true", help="每轮约 2 s 连续报数")
    ap.add_argument("--no-save", action="store_true", help="不存快照与 CSV")
    args = ap.parse_args(argv)

    if not args.watch:
        return one_round(args.exposure, args.frames, not args.no_save)

    print("watch 模式：Ctrl-C 退出（每轮之间等 1 s）\n")
    try:
        while True:
            one_round(args.exposure, args.frames, not args.no_save)
            print()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
