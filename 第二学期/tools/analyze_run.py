#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析一段推车录像：检出率、轮廓面积、速度（用已标定的 H 换算成 cm）

    cd 第二学期
    python -m tools.analyze_run --video out/truss_15s.mp4

输出：
    · 帧数 / 帧率 / 运动段
    · 检出率（面积超过 config.CONTOUR_AREA_MIN 的帧占比，统计窗口=目标在画面内的帧）
    · 轮廓面积中位数（用来复核 contourArea 阈值）
    · 速度：用 calibration_config.json 的 H 把质心换成 cm，线性拟合
    · 代表帧与掩码图 → out/run_*.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import config


def load_H(path: str):
    H = np.array(json.loads(Path(path).read_text(encoding="utf-8"))["H"], np.float64)
    return H, np.linalg.inv(H)


def to_world(px, H_inv):
    p = np.array([[px]], np.float64)
    q = cv2.perspectiveTransform(p, H_inv)[0, 0]
    return float(q[0]), float(q[1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="推车录像分析")
    ap.add_argument("--video", required=True)
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    ap.add_argument("--area-min", type=float, default=config.CONTOUR_AREA_MIN)
    ap.add_argument("--bright-min", type=float, default=100.0,
                    help="亮度门限（灰度），用来剔除深阴影；实测桁架≈177、阴影<50")
    ap.add_argument("--out", default="out/run_overlay.png")
    args = ap.parse_args(argv)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"✗ 打不开 {args.video}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    H, H_inv = load_H(args.calib)

    mog = cv2.createBackgroundSubtractorMOG2(
        history=config.MOG2_HISTORY, varThreshold=config.MOG2_VAR_THRESHOLD,
        detectShadows=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (config.MORPH_KERNEL_SIZE, config.MORPH_KERNEL_SIZE))

    rows = []          # (t, u, v, area, ok)
    best = None
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        fg = mog.apply(gray)
        # 只保留"运动 + 够亮"的像素：深阴影会被 MOG2 判成前景(255)，
        # 用亮度门限把它和白色桁架分开（实测桁架 P95≈177、阴影 <50）
        hard = np.where((fg == 255) & (gray >= args.bright_min), 255, 0).astype(np.uint8)
        hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, k)
        hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, k)
        cs, _ = cv2.findContours(hard, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cs:
            c = max(cs, key=cv2.contourArea)
            a = float(cv2.contourArea(c))
            M = cv2.moments(c)
            if M["m00"] > 0 and a >= args.area_min:
                u, v = M["m10"] / M["m00"], M["m01"] / M["m00"]
                rows.append((i / fps, u, v, a, True))
                if best is None or a > best[1]:
                    best = (img.copy(), a, hard.copy())
                i += 1
                continue
        rows.append((i / fps, 0.0, 0.0, 0.0, False))
        i += 1
    cap.release()

    r = np.array([(t, u, v, a, float(ok)) for t, u, v, a, ok in rows])
    if len(r) == 0:
        print("✗ 视频没有帧")
        return 1

    det = r[r[:, 4] > 0]
    if len(det) == 0:
        print("✗ 整段没检出目标（阈值可能太高，或画面里没有目标）")
        return 1

    t0, t1 = det[0, 0], det[-1, 0]
    win = (r[:, 0] >= t0) & (r[:, 0] <= t1)
    total = int(win.sum())
    hit = int(det.shape[0])
    fail = 1 - hit / total if total else 1.0
    areas = det[:, 3]
    med = float(np.median(areas))

    # 只用面积在 [0.5, 2]×中位 的帧做速度拟合
    good = det[(det[:, 3] > 0.5 * med) & (det[:, 3] < 2.0 * med)]
    w = np.array([to_world((u, v), H_inv) for _, u, v, _, _ in good])
    t = good[:, 0]
    vx = np.polyfit(t, w[:, 0], 1)[0]
    vy = np.polyfit(t, w[:, 1], 1)[0]
    speed = float(np.hypot(vx, vy))

    print(f"视频      {args.video}")
    print(f"帧率      {fps:.1f} fps，总帧 {len(r)}")
    print(f"运动段    {t0:.2f} ~ {t1:.2f} s（{total} 帧）")
    print(f"检出      运动段内 {hit}/{total} 帧 → 失败率 {fail*100:.1f}%")
    print(f"轮廓面积  中位 {med:.0f} px²，P25 {np.percentile(areas,25):.0f}，"
          f"P75 {np.percentile(areas,75):.0f}（阈值 {args.area_min:.0f}）")
    print(f"速度      {speed:.2f} cm/s（拟合 {len(good)} 帧；分量 vx={vx:.1f}, vy={vy:.1f}）")
    print(f"拖影      {speed/1000*config.EXPOSURE_US/1000*config.PX_PER_CM:.1f} px"
          f"（速度 {speed:.1f} cm/s × 曝光 {config.EXPOSURE_US/1000:.0f} ms）")

    if best is not None:
        cv2.imwrite(args.out, best[0])
        print(f"代表帧    {args.out}（面积 {best[1]:.0f} px²）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
