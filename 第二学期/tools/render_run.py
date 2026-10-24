#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按指定算法版本渲染一段录像：标注视频 + 四宫格学术报表

    cd 第二学期
    python -m tools.render_run --video out/truss_21_15s.mp4 --target 21 --version v23

版本：
    v21  无亮度门限（V2.1）
    v22  固定亮度门限 100（V2.2）
    v23  自适应亮度门限 + Alpha-Beta + 稳态窗（V2.3）

输出：
    out/render/<视频名>_<版本>.mp4        标注视频（轮廓/质心/轨迹/HUD）
    out/render/<视频名>_<版本>.png        四宫格报表（300 dpi）

说明：世界坐标统一乘 config.PLANE_SCALE（等效平面修正），三个版本同一几何。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config


def load_H(path: str):
    H = np.array(json.loads(Path(path).read_text(encoding="utf-8"))["H"], np.float64)
    return H, np.linalg.inv(H)


def to_world(H_inv, u, v):
    p = cv2.perspectiveTransform(np.array([[[u, v]]], np.float64), H_inv)[0, 0]
    return float(p[0]), float(p[1])


def ab_filter(xs, ys, dt, alpha=0.15, beta=0.005):
    n = len(xs)
    X = np.zeros(n); Y = np.zeros(n); VX = np.zeros(n); VY = np.zeros(n)
    X[0], Y[0] = xs[0], ys[0]
    if n > 1:
        VX[0] = (xs[1] - xs[0]) / dt
        VY[0] = (ys[1] - ys[0]) / dt
    for i in range(1, n):
        Xp = X[i-1] + VX[i-1] * dt
        Yp = Y[i-1] + VY[i-1] * dt
        rx, ry = xs[i] - Xp, ys[i] - Yp
        X[i] = Xp + alpha * rx
        Y[i] = Yp + alpha * ry
        VX[i] = VX[i-1] + (beta / dt) * rx
        VY[i] = VY[i-1] + (beta / dt) * ry
    return X, Y, VX, VY


def gate(fg, gray, version):
    if version == "v21":
        return (fg == 255).astype(np.uint8) * 255
    if version == "v22":
        return np.where((fg == 255) & (gray >= 100), 255, 0).astype(np.uint8)
    med = float(np.median(gray)); p95 = float(np.percentile(gray, 95))
    thr = med + 0.5 * (p95 - med)
    return np.where((fg == 255) & (gray >= thr), 255, 0).astype(np.uint8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="渲染录像：标注视频 + 四宫格报表")
    ap.add_argument("--video", required=True)
    ap.add_argument("--target", type=float, required=True)
    ap.add_argument("--version", choices=["v21", "v22", "v23"], required=True)
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    ap.add_argument("--area-min", type=float, default=config.CONTOUR_AREA_MIN)
    ap.add_argument("--outdir", default="out/render")
    args = ap.parse_args(argv)

    H, H_inv = load_H(args.calib)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"✗ 打不开 {args.video}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.video).stem
    vpath = outdir / f"{stem}_{args.version}.mp4"
    writer = cv2.VideoWriter(str(vpath), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    mog = cv2.createBackgroundSubtractorMOG2(
        history=config.MOG2_HISTORY, varThreshold=config.MOG2_VAR_THRESHOLD,
        detectShadows=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (config.MORPH_KERNEL_SIZE, config.MORPH_KERNEL_SIZE))

    rec = []          # (t, ok, area, u, v, wx, wy)
    trail = []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        fg = mog.apply(gray)
        hard = gate(fg, gray, args.version)
        hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, k)
        hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, k)
        cs, _ = cv2.findContours(hard, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        t = i / fps
        okd = False
        area = 0.0
        u = v = 0.0
        if cs:
            c = max(cs, key=cv2.contourArea)
            area = float(cv2.contourArea(c))
            M = cv2.moments(c)
            if area >= args.area_min and M["m00"] > 0:
                okd = True
                u, v = M["m10"] / M["m00"], M["m01"] / M["m00"]
                cv2.drawContours(img, [c], -1, (0, 255, 0), 2)
                cv2.circle(img, (int(u), int(v)), 5, (0, 0, 255), -1)
                trail.append((int(u), int(v)))
                if len(trail) > config.TRAJ_MAXLEN:
                    trail.pop(0)
        for a, b in zip(trail[:-1], trail[1:]):
            cv2.line(img, a, b, (0, 200, 255), 2)
        wx = wy = 0.0
        if okd:
            wx, wy = to_world(H_inv, u, v)
            wx *= config.PLANE_SCALE
            wy *= config.PLANE_SCALE
        rec.append((t, okd, area, u, v, wx, wy))
        hud = f"{args.version} | t={t:5.2f}s | area={area:6.0f} | {'TRACK' if okd else 'LOST'}"
        cv2.putText(img, hud, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 255, 255), 2, cv2.LINE_AA)
        writer.write(img)
        i += 1
    cap.release(); writer.release()

    arr = np.array([(r[0], float(r[1]), r[2], r[3], r[4], r[5], r[6]) for r in rec])
    det = arr[arr[:, 1] > 0]
    if len(det) < 10:
        print("✗ 检出帧太少，无法出报表")
        return 1
    t = det[:, 0]; wx = det[:, 5]; wy = det[:, 6]; area = det[:, 2]
    dt = 1.0 / fps
    X, Y, VX, VY = ab_filter(wx, wy, dt)
    V = np.hypot(VX, VY)

    # 稳态窗（15% / 1.0 s）
    in_tol = np.abs(V - args.target) / args.target <= config.STEADY_TOL
    best = (0, 0); s = None
    for j, flag in enumerate(in_tol):
        if flag and s is None:
            s = j
        if (not flag or j == len(in_tol) - 1) and s is not None:
            e = j if (flag and j == len(in_tol) - 1) else j - 1
            if (t[e] - t[s]) > (t[best[1]] - t[best[0]] if best[1] else -1):
                best = (s, e)
            s = None
    s, e = best
    if e <= s:
        s, e = 0, len(t) - 1
    v_steady = float(np.mean(V[s:e+1]))

    # 各版本的口径：v21/v22 用全局拟合；v23 用稳态窗均值
    if args.version in ("v21", "v22"):
        med = float(np.median(area))
        good = (area > 0.5 * med) & (area < 2.0 * med)
        vx = np.polyfit(t[good], wx[good], 1)[0]
        vy = np.polyfit(t[good], wy[good], 1)[0]
        v_report = float(np.hypot(vx, vy))
    else:
        v_report = v_steady

    t0, t1 = det[0, 0], det[-1, 0]
    win = arr[(arr[:, 0] >= t0) & (arr[:, 0] <= t1)]
    hit = int(win[:, 1].sum())
    fail = 1 - hit / len(win) if len(win) else 1.0

    # ---------- 四宫格报表 ----------
    plt.rcParams.update({"figure.dpi": 120, "font.size": 9})
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    fig.suptitle(f"{args.version.upper()}  |  target {args.target:.0f} cm/s  |  "
                 f"measured {v_report:.2f} cm/s  |  failure {fail*100:.1f}%",
                 fontsize=12, fontweight="bold")

    ax[0, 0].plot(wx, wy, "-", lw=1.2, color="#1f77b4")
    ax[0, 0].plot(wx[s:e+1], wy[s:e+1], "-", lw=3, color="#2ca02c", alpha=0.7,
                  label="steady window")
    ax[0, 0].set_xlabel("X (cm)"); ax[0, 0].set_ylabel("Y (cm)")
    ax[0, 0].set_title("Trajectory (plane-corrected)")
    ax[0, 0].legend(loc="best"); ax[0, 0].grid(alpha=0.3)

    ax[0, 1].plot(t, wx, lw=1.2, color="#1f77b4"); ax[0, 1].plot(t, wy, lw=1.0, color="#ff7f0e")
    ax[0, 1].axvspan(t[s], t[e], color="#2ca02c", alpha=0.15)
    ax[0, 1].set_xlabel("t (s)"); ax[0, 1].set_ylabel("position (cm)")
    ax[0, 1].set_title("X / Y vs time"); ax[0, 1].grid(alpha=0.3)

    ax[1, 0].plot(t, V, lw=1.2, color="#1f77b4", label="speed")
    ax[1, 0].axhline(args.target, color="#2ca02c", ls="--", lw=1, label="target")
    ax[1, 0].axhspan(args.target * 0.85, args.target * 1.15, color="#2ca02c", alpha=0.12,
                     label="±15%")
    ax[1, 0].axhline(v_steady, color="#d62728", ls=":", lw=1, label=f"steady mean {v_steady:.2f}")
    ax[1, 0].axvspan(t[s], t[e], color="#2ca02c", alpha=0.12)
    ax[1, 0].set_xlabel("t (s)"); ax[1, 0].set_ylabel("speed (cm/s)")
    ax[1, 0].set_title("Speed (Alpha-Beta)"); ax[1, 0].legend(loc="best", fontsize=8)
    ax[1, 0].grid(alpha=0.3)

    ax[1, 1].plot(t, area, lw=1.0, color="#9467bd")
    ax[1, 1].axhline(args.area_min, color="#d62728", ls="--", lw=1, label="area threshold")
    ax[1, 1].set_xlabel("t (s)"); ax[1, 1].set_ylabel("contour area (px²)")
    ax[1, 1].set_title(f"Contour area  |  detection {hit}/{len(win)}")
    ax[1, 1].legend(loc="best", fontsize=8); ax[1, 1].grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fpath = outdir / f"{stem}_{args.version}.png"
    fig.savefig(fpath, dpi=300)
    plt.close(fig)

    print(f"✓ 视频 {vpath}")
    print(f"✓ 报表 {fpath}")
    print(f"  版本 {args.version} | 目标 {args.target:.0f} | 报道速度 {v_report:.2f} cm/s | "
          f"稳态窗 {t[s]:.2f}~{t[e]:.2f}s | 失败率 {fail*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
