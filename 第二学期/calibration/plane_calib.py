#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""平面标定：用标定板求"区域厘米坐标 ↔ 像素"的单应 H

    cd 第二学期
    python -m calibration.plane_calib --image out/calib_center.png --dx 3.0 --dy 5.0

参数：
    --image   标定板照片（板要垫到"跟踪面"高度，平放、摆正）
    --dx/--dy 板第 0 个内角点在【区域坐标系】里的位置（cm，卷尺量，±2 mm）
    --region  区域尺寸，默认 78×60
    --out     H 的保存路径，默认 calibration/calibration_config.json

输出：
    · H（区域 cm → 像素）与重投影 RMS
    · 把 5 cm 网格投到图上（out/calib_overlay.png），肉眼核对是否与地面胶带对齐
    · 板四角的世界坐标（应与卷尺量到的板位置一致）

注意：
    · 板必须和跟踪点同一高度 —— 差 1 cm 约 0.85% 尺度误差，直接进速度
    · 角点顺序随板在画面里的转向而变；本脚本会自动检查镜像并提示
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import config

SQ_CM = 1.5            # 单格 15 mm
COLS, ROWS = 11, 8     # 内角点


def find_corners(gray: np.ndarray):
    for pattern in ((COLS, ROWS), (ROWS, COLS)):
        ok, pts = cv2.findChessboardCornersSB(
            gray, pattern,
            flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
        if ok:
            return pts.reshape(-1, 2).astype(np.float64), pattern, "SB"
    for pattern in ((COLS, ROWS), (ROWS, COLS)):
        ok, pts = cv2.findChessboardCorners(
            gray, pattern,
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ok:
            cv2.cornerSubPix(
                gray, pts, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))
            return pts.reshape(-1, 2).astype(np.float64), pattern, "classic"
    return None, None, None


def world_to_px(H: np.ndarray, pts_cm: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts_cm, np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="标定板求平面单应 H")
    ap.add_argument("--image", required=True)
    ap.add_argument("--dx", type=float, required=True, help="板第 0 内角点的区域 x（cm）")
    ap.add_argument("--dy", type=float, required=True, help="板第 0 内角点的区域 y（cm）")
    ap.add_argument("--region", default="78x60", help="区域尺寸 cm，如 78x60")
    ap.add_argument("--out", default="calibration/calibration_config.json")
    ap.add_argument("--overlay", default="out/calib_overlay.png")
    args = ap.parse_args(argv)

    gray = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        print(f"✗ 读不到 {args.image}")
        return 1

    pts, pattern, how = find_corners(gray)
    if pts is None:
        print("✗ 没检出完整棋盘：板不在画面 / 缺角 / 曝光不足")
        return 1
    cols, rows = pattern
    obj = np.array([[c * SQ_CM, r * SQ_CM]
                    for r in range(rows) for c in range(cols)], np.float64)

    H_board, mask = cv2.findHomography(obj, pts, cv2.RANSAC, 2.0)
    if H_board is None:
        print("✗ 单应求解失败")
        return 1
    proj = world_to_px(H_board, obj)
    rms = float(np.sqrt(np.mean(np.sum((proj - pts) ** 2, axis=1))))

    # 区域坐标 = 板坐标 + (dx, dy)
    T = np.array([[1, 0, args.dx], [0, 1, args.dy], [0, 0, 1]], np.float64)
    H = H_board @ np.linalg.inv(T)

    # 镜像检查
    det = np.linalg.det(H[:2, :2])
    print(f"✓ 检出 {len(pts)} 角点（{how}，pattern={pattern}），重投影 RMS {rms:.3f} px")
    print(f"  板原点在区域坐标 ({args.dx:.2f}, {args.dy:.2f}) cm")
    print(f"  H 保存到 {args.out}")
    if det <= 0:
        print("  ⚠ H 的 2×2 行列式为负：角点顺序可能是镜像，请把板转 180° 重拍或检查 dx/dy")

    # 板四角世界坐标（用于和卷尺比对）
    w, h = (cols - 1) * SQ_CM, (rows - 1) * SQ_CM
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]])
    print("  板内角点四角在区域坐标系下的位置（应与你量的板位置一致）：")
    for name, p in zip(("左上", "右上", "右下", "左下"), corners):
        print(f"    {name}: ({p[0] + args.dx:.1f}, {p[1] + args.dy:.1f}) cm")

    # 保存
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "H": H.tolist(),
        "H_board": H_board.tolist(),
        "dx": args.dx, "dy": args.dy,
        "region": args.region,
        "rms_px": rms,
        "image": str(args.image),
        "note": "H 把区域厘米坐标映射到像素；像素→厘米用 np.linalg.inv(H)",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5 cm 网格叠加
    rw, rh = (float(v) for v in args.region.lower().split("x"))
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for x in np.arange(0, rw + 1e-6, 5.0):
        p0 = world_to_px(H, [[x, 0]])[0]
        p1 = world_to_px(H, [[x, rh]])[0]
        cv2.line(vis, tuple(np.int32(p0)), tuple(np.int32(p1)), (0, 220, 0), 1)
    for y in np.arange(0, rh + 1e-6, 5.0):
        p0 = world_to_px(H, [[0, y]])[0]
        p1 = world_to_px(H, [[rw, y]])[0]
        cv2.line(vis, tuple(np.int32(p0)), tuple(np.int32(p1)), (0, 220, 0), 1)
    cv2.putText(vis, f"grid 5cm | RMS {rms:.2f}px | dx={args.dx} dy={args.dy}",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    overlay = Path(args.overlay)
    overlay.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(overlay), vis)
    print(f"  网格叠加图 → {overlay}（把 5 cm 网格与地面胶带/卷尺比对）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
