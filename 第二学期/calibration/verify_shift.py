#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""尺度校验：用"平移标定板已知距离"验证 H 的尺度（不需要画测量区）

    cd 第二学期
    python -m calibration.verify_shift --a out/calib_A.png --b out/calib_B.png --expected 30

做法：
    1. H 由 A 图求出（plane_calib 已保存到 calibration/calibration_config.json）；
    2. B 图是在 A 之后把板沿某个方向平移 expected 厘米拍的；
    3. 用同一个 H 把两张图里"同名的板内角点"换算成世界坐标，比较位移；
    4. 判据：|视觉位移 − expected| / expected ≤ 1.5%。

注意：板移动时不要转动；沿运动方向平移最好。
"""

from __future__ import annotations

import argparse
import json

import cv2
import numpy as np

SQ_CM = 1.5
COLS, ROWS = 11, 8


def find_corners(gray):
    for pattern in ((COLS, ROWS), (ROWS, COLS)):
        ok, pts = cv2.findChessboardCornersSB(
            gray, pattern,
            flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
        if ok:
            return pts.reshape(-1, 2).astype(np.float64), pattern
    for pattern in ((COLS, ROWS), (ROWS, COLS)):
        ok, pts = cv2.findChessboardCorners(
            gray, pattern,
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ok:
            cv2.cornerSubPix(gray, pts, (11, 11), (-1, -1),
                             (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))
            return pts.reshape(-1, 2).astype(np.float64), pattern
    return None, None


def to_world(H_inv, px):
    p = np.array([[[px[0], px[1]]]], np.float64)
    q = cv2.perspectiveTransform(p, H_inv)[0, 0]
    return q


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="平移标定板验证 H 的尺度")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--expected", type=float, default=30.0, help="实际平移距离（cm）")
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    args = ap.parse_args(argv)

    H = np.array(json.loads(open(args.calib, encoding="utf-8").read())["H"], np.float64)
    H_inv = np.linalg.inv(H)

    ga = cv2.imread(args.a, cv2.IMREAD_GRAYSCALE)
    gb = cv2.imread(args.b, cv2.IMREAD_GRAYSCALE)
    if ga is None or gb is None:
        missing = [p for p, g in ((args.a, ga), (args.b, gb)) if g is None]
        print("✗ 读不到图片：" + "、".join(missing))
        print("  先把两张图拍好，再跑本命令：")
        print("    python -m camera.camera_capture --exposure 10000 --gain 6 snap <路径>")
        return 1
    pa, _ = find_corners(ga)
    pb, _ = find_corners(gb)
    if pa is None or pb is None:
        print("✗ 有一张图没检出完整棋盘（板不在画面/缺角/过曝）")
        return 1

    # 用板中心（88 点的平均）算位移，抗单点噪声
    wa = to_world(H_inv, pa.mean(axis=0))
    wb = to_world(H_inv, pb.mean(axis=0))
    d = wb - wa
    dist = float(np.linalg.norm(d))
    err = abs(dist - args.expected) / args.expected

    print(f"A 板中心世界坐标: ({wa[0]:.2f}, {wa[1]:.2f}) cm")
    print(f"B 板中心世界坐标: ({wb[0]:.2f}, {wb[1]:.2f}) cm")
    print(f"视觉位移: Δx={d[0]:+.2f}  Δy={d[1]:+.2f}  |Δ|={dist:.2f} cm")
    print(f"卷尺距离: {args.expected:.2f} cm  →  相对误差 {err*100:.2f}%")
    print("判定:", "✓ 通过（≤1.5%）" if err <= 0.015 else "✗ 超限，检查标定/机位是否动过")
    return 0 if err <= 0.015 else 2


if __name__ == "__main__":
    raise SystemExit(main())
