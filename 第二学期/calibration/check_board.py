#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定板体检（P1.5/P1.6 前置）

    python -m calibration.check_board                 # 抓一帧，默认曝光 20 ms
    python -m calibration.check_board -e 15000        # 指定曝光（μs）
    python -m calibration.check_board --image out/a.png
    python -m calibration.check_board --watch         # 每 2 s 一帧，边调机位边看

回答四个问题：
    1) 板有没有完整进画面、角点能不能稳定检出；
    2) 现在的像素尺度 px/cm 是多少（与焦距无关，最可靠）；
    3) 镜头到板面的工作距离大概多少（用单应反推，假设焦距/像元为标称值）；
    4) 光轴与板法线差多少度（吸收进单应，但能反映机位正不正）。

板规格：DFOPTIX Q12-200-15，图案 180×135 mm，单格 15 mm，12×9 格 → 内角点 11×8。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import config

# ---- Q12-200-15 ----
SQ_CM = 1.5
COLS, ROWS = 11, 8                 # 内角点数
# 相机标称参数（从 px/cm 反推 WD 时用）
F_PX = config.LENS_FOCAL_MM / 0.0048      # 8 mm / 4.8 μm ≈ 1666.7 px

CAR_LEN_CM = 25.0                  # 车在运动方向上的可见长度（保守值）
CONVERGE_CM = 21.0                 # v1 实测的滤波器收敛段
TARGET_CMS = 31.0


# ------------------------------------------------------------------ 检测

def find_corners(gray: np.ndarray):
    """返回 (corners Nx2, pattern, 方法名)；检不到返回 (None, None, None)。"""
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


def analyse(gray: np.ndarray) -> dict | None:
    pts, pattern, how = find_corners(gray)
    if pts is None:
        return None

    cols, rows = pattern
    obj = np.array([[c * SQ_CM, r * SQ_CM]
                    for r in range(rows) for c in range(cols)], np.float64)
    H, mask = cv2.findHomography(obj, pts, cv2.RANSAC, 2.0)
    if H is None:
        return None
    proj = cv2.perspectiveTransform(obj.reshape(-1, 1, 2), H).reshape(-1, 2)
    rms = float(np.sqrt(np.mean(np.sum((proj - pts) ** 2, axis=1))))

    K = np.array([[F_PX, 0, gray.shape[1] / 2],
                  [0, F_PX, gray.shape[0] / 2], [0, 0, 1.0]])
    Hn = np.linalg.inv(K) @ H
    s = 2.0 / (np.linalg.norm(Hn[:, 0]) + np.linalg.norm(Hn[:, 1]))
    r1, r2 = Hn[:, 0] * s, Hn[:, 1] * s
    r3 = np.cross(r1, r2)
    wd_cm = float(np.linalg.norm(Hn[:, 2] * s))
    tilt = float(np.degrees(np.arccos(np.clip(abs(r3[2]), -1, 1))))

    def scale(d):
        c = obj.mean(axis=0)
        p0 = cv2.perspectiveTransform(np.array([[[*c]]]), H)[0, 0]
        p1 = cv2.perspectiveTransform(np.array([[[c[0] + d[0], c[1] + d[1]]]]), H)[0, 0]
        return float(np.linalg.norm(p1 - p0))

    px_x, px_y = scale((1.0, 0.0)), scale((0.0, 1.0))
    fov_w = 1280.0 / px_x
    fov_h = 1024.0 / px_y

    h, w = gray.shape[:2]
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    margin = min(x0, y0, w - x1, h - y1)

    steady = (fov_w - CAR_LEN_CM - CONVERGE_CM) / TARGET_CMS
    return dict(n=len(pts), how=how, rms=rms, px_x=px_x, px_y=px_y,
                wd=wd_cm, tilt=tilt, fov_w=fov_w, fov_h=fov_h,
                region_w=fov_w - 10, region_h=fov_h - 10,
                steady=steady, margin=margin,
                bbox=(x0, y0, x1, y1), board_c=(pts.mean(axis=0)),
                H=H, pts=pts, pattern=pattern)


# ------------------------------------------------------------------ 输出

def report(r: dict, img: np.ndarray, out: Path | None) -> None:
    print(f"  角点        {r['n']} 个（{r['how']}，pattern={r['pattern']}）"
          f"｜重投影 RMS {r['rms']:.3f} px")
    print(f"  像素尺度    X {r['px_x']:.2f}  Y {r['px_y']:.2f} px/cm"
          f"（X/Y 比 {r['px_x'] / r['px_y']:.4f}）")
    print(f"  工作距离    ≈ {r['wd']:.1f} cm（按 f=8 mm / 4.8 μm 反推）")
    print(f"  板面倾角    {r['tilt']:.1f}°（光轴与板法线）")
    print(f"  视野        {r['fov_w']:.1f} × {r['fov_h']:.1f} cm")
    print(f"  建议测量区  {r['region_w']:.1f} × {r['region_h']:.1f} cm（留 5 cm 边）")
    print(f"  31 cm/s 稳态窗 ≈ {r['steady']:.2f} s（车长 {CAR_LEN_CM:.0f} cm、"
          f"收敛 {CONVERGE_CM:.0f} cm）")
    print(f"  板到画面边缘最小余量 {r['margin']:.0f} px"
          + ("  ⚠ 偏小，建议 ≥100 px" if r['margin'] < 100 else "  ✓"))

    if out is not None:
        vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        cv2.drawChessboardCorners(vis, r['pattern'],
                                  r['pts'].astype(np.float32).reshape(-1, 1, 2), True)
        bar = np.full((32, vis.shape[1], 3), 35, np.uint8)
        cv2.putText(bar, f"{r['px_x']:.2f} px/cm  WD~{r['wd']:.0f}cm  "
                         f"tilt {r['tilt']:.1f}deg  RMS {r['rms']:.2f}px",
                    (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (235, 235, 235), 1, cv2.LINE_AA)
        cv2.imwrite(str(out), np.vstack([bar, vis]))
        print(f"  标注图 → {out}")


# ------------------------------------------------------------------ 主流程

def grab(exposure_us: float) -> np.ndarray:
    from camera.backend import open_camera
    cam = open_camera()
    cam.open()
    try:
        cam.set_exposure_us(exposure_us)
        frame = None
        for _ in range(8):                 # 曝光切换后前几帧还是旧值
            frame = cam.read()
            if frame is None:
                raise RuntimeError("取帧超时")
            time.sleep(0.02)
        frame = cam.read()
        if frame is None:
            raise RuntimeError("取帧超时")
        img = frame.image
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img
    finally:
        cam.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="标定板体检（Q12-200-15）")
    ap.add_argument("--image", help="离线分析一张图（不给就抓帧）")
    ap.add_argument("-e", "--exposure", type=float, default=20000.0,
                    help="抓帧曝光（μs），默认 20000")
    ap.add_argument("--watch", action="store_true", help="每 2 s 抓一帧连续报数")
    ap.add_argument("--out", default="out/check_board.png", help="标注图输出路径")
    args = ap.parse_args(argv)

    if args.image:
        gray = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            print(f"✗ 读不到 {args.image}")
            return 1
        r = analyse(gray)
        if r is None:
            print("✗ 没检出完整棋盘：板不在画面 / 缺角 / 太暗")
            return 1
        report(r, gray, Path(args.out))
        np.save("calibration/homography_board.npy", r["H"])
        return 0

    if not args.watch:
        gray = grab(args.exposure)
        r = analyse(gray)
        if r is None:
            print("✗ 没检出完整棋盘：板不在画面 / 缺角 / 太暗（先看快照）")
            cv2.imwrite("out/check_board_fail.png", gray)
            print("  原始帧 → out/check_board_fail.png")
            return 1
        report(r, gray, Path(args.out))
        return 0

    print("watch 模式：每 2 s 抓一帧，Ctrl-C 退出\n")
    try:
        while True:
            try:
                gray = grab(args.exposure)
            except Exception as exc:          # noqa: BLE001
                print(f"  取帧失败：{exc!r}")
                time.sleep(2)
                continue
            r = analyse(gray)
            stamp = time.strftime("%H:%M:%S")
            if r is None:
                print(f"[{stamp}] 未检出")
            else:
                print(f"[{stamp}] {r['n']} 点  {r['px_x']:.2f} px/cm  "
                      f"WD {r['wd']:.0f} cm  tilt {r['tilt']:.1f}°  "
                      f"边距 {r['margin']:.0f} px  "
                      f"窗 {r['steady']:.1f} s")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
