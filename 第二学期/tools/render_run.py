#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按指定算法版本渲染一段录像：标注视频（含速度矢量与误差 HUD）+ 四宫格学术报表

    cd 第二学期
    python -m tools.render_run --video out/truss_21_15s.mp4 --target 21 --version v23

版本：
    v21  无亮度门限（V2.1）
    v22  固定亮度门限 100（V2.2）
    v23  自适应亮度门限 + Alpha-Beta + 稳态窗（V2.3）

视频 HUD：
    第 1 行：版本 | 目标速度 | 实测速度 | 相对误差
    第 2 行：时间 | 当前速度 | 轮廓面积 | TRACK/LOST
    第 3 行：STEADY（处于稳态窗内时绿色高亮）
    速度矢量：从质心出发，长度 = 0.30 s 的位移，方向 = αβ 速度方向

两遍处理：第一遍检测并记录轨迹，算好 αβ 速度；第二遍重绘叠加。
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


def world_to_px(H, wx, wy, plane_scale):
    """真实世界坐标 → 像素（H 对应标定面，需先除掉平面修正系数）。"""
    p = cv2.perspectiveTransform(
        np.array([[[wx / plane_scale, wy / plane_scale]]], np.float64), H)[0, 0]
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


def detect(gray, mog, version, k, area_min):
    fg = mog.apply(gray)
    hard = gate(fg, gray, version)
    hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, k)
    hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, k)
    cs, _ = cv2.findContours(hard, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None, 0.0
    c = max(cs, key=cv2.contourArea)
    area = float(cv2.contourArea(c))
    if area < area_min:
        return None, area
    M = cv2.moments(c)
    if M["m00"] <= 0:
        return None, area
    return (c, M["m10"] / M["m00"], M["m01"] / M["m00"]), area


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="渲染录像：标注视频（速度矢量+误差）+ 四宫格报表")
    ap.add_argument("--video", required=True)
    ap.add_argument("--target", type=float, required=True)
    ap.add_argument("--version", choices=["v21", "v22", "v23"], required=True)
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    ap.add_argument("--area-min", type=float, default=config.CONTOUR_AREA_MIN)
    ap.add_argument("--outdir", default="out/render")
    ap.add_argument("--arrow-s", type=float, default=0.30, help="速度矢量代表的时长（s）")
    ap.add_argument("--plane-scale", type=float, default=None,
                    help="覆盖等效平面修正；给 1.0 可看未修正效果")
    args = ap.parse_args(argv)

    ks = config.PLANE_SCALE if args.plane_scale is None else args.plane_scale
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

    # ---------------- 第一遍：检测 + 记录 ----------------
    mog = cv2.createBackgroundSubtractorMOG2(
        history=config.MOG2_HISTORY, varThreshold=config.MOG2_VAR_THRESHOLD,
        detectShadows=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (config.MORPH_KERNEL_SIZE, config.MORPH_KERNEL_SIZE))

    rec = []          # (t, ok, area, u, v, wx, wy, bx, by, bw, bh)
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        res, area = detect(gray, mog, args.version, k, args.area_min)
        t = i / fps
        if res is None:
            rec.append((t, False, area, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0))
        else:
            c, u, v = res
            bx, by, bw, bh = cv2.boundingRect(c)
            wx, wy = to_world(H_inv, u, v)
            wx *= ks
            wy *= ks
            rec.append((t, True, area, u, v, wx, wy, bx, by, bw, bh))
        i += 1
    cap.release()
    arr = np.array([(r[0], float(r[1]), r[2], r[3], r[4], r[5], r[6],
                     r[7], r[8], r[9], r[10]) for r in rec])
    det = arr[arr[:, 1] > 0]
    if len(det) < 10:
        print("✗ 检出帧太少，无法出报表")
        return 1

    t = det[:, 0]; area = det[:, 2]; wx = det[:, 5]; wy = det[:, 6]
    bx = det[:, 7]; by = det[:, 8]; bw = det[:, 9]; bh = det[:, 10]
    dt = 1.0 / fps
    X, Y, VX, VY = ab_filter(wx, wy, dt)
    V = np.hypot(VX, VY)

    # ---- 稳态窗：位置中段 + 速度 ±tol + 帧间隔连续 + 时长 ≥ min ----
    m_px = int(round(config.ROI_MARGIN_CM * config.PX_PER_CM))
    roi_l, roi_t, roi_r, roi_b = m_px, m_px, w - m_px, h - m_px
    in_mid = (bx >= roi_l) & (bx + bw <= roi_r) & (by >= roi_t) & (by + bh <= roi_b)
    in_tol = np.abs(V - args.target) / args.target <= config.STEADY_TOL
    ok_mask = in_tol & in_mid
    fi = np.array([int(round(tt * fps)) for tt in t], int)
    runs = []
    s0 = None
    for j in range(len(ok_mask)):
        if s0 is None:
            if ok_mask[j]:
                s0 = j
            continue
        if (not ok_mask[j]) or (fi[j] - fi[j - 1] > config.MAX_GAP_FRAMES):
            runs.append((s0, j - 1))
            s0 = j if ok_mask[j] else None
    if s0 is not None:
        runs.append((s0, len(ok_mask) - 1))
    valid = [(a, b) for a, b in runs if t[b] - t[a] >= config.STEADY_MIN_DURATION_S]
    has_window = bool(valid)
    if has_window:
        s, e = max(valid, key=lambda ab: t[ab[1]] - t[ab[0]])
        v_steady = float(np.mean(V[s:e + 1]))
    else:
        s, e = -1, -1
        v_steady = float("nan")

    # 版本口径：v21/v22 全局拟合，v23 稳态窗均值
    if args.version in ("v21", "v22"):
        med = float(np.median(area))
        good = (area > 0.5 * med) & (area < 2.0 * med)
        vx = np.polyfit(t[good], wx[good], 1)[0]
        vy = np.polyfit(t[good], wy[good], 1)[0]
        v_report = float(np.hypot(vx, vy))
        method = "global fit"
    elif has_window:
        v_report = v_steady
        method = "steady mean"
    else:
        v_report = float(np.mean(V))
        method = "no steady (global)"
    err_pct = (v_report - args.target) / args.target * 100.0

    t0, t1 = det[0, 0], det[-1, 0]
    win = arr[(arr[:, 0] >= t0) & (arr[:, 0] <= t1)]
    hit = int(win[:, 1].sum())
    fail = 1 - hit / len(win) if len(win) else 1.0

    # 帧号 → 检测序号映射（画矢量用）
    det_idx = {int(round(r[0] * fps)): j for j, r in enumerate(det)}

    # ---------------- 第二遍：重绘 + 写视频 ----------------
    cap = cv2.VideoCapture(args.video)
    writer = cv2.VideoWriter(str(vpath), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    mog = cv2.createBackgroundSubtractorMOG2(
        history=config.MOG2_HISTORY, varThreshold=config.MOG2_VAR_THRESHOLD,
        detectShadows=True)
    trail = []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        res, cur_area = detect(gray, mog, args.version, k, args.area_min)
        now = i / fps
        fi = i
        tracked = res is not None
        v_now = 0.0
        if tracked:
            c, u, v = res
            cv2.drawContours(img, [c], -1, (0, 255, 0), 2)
            cv2.circle(img, (int(u), int(v)), 5, (0, 0, 255), -1)
            trail.append((int(u), int(v)))
            if len(trail) > config.TRAJ_MAXLEN:
                trail.pop(0)
            j = det_idx.get(fi)
            if j is not None:
                v_now = float(V[j])
                # 速度矢量：当前世界点 → 0.30 s 后的点
                x0, y0 = world_to_px(H, wx[j], wy[j], ks)
                x1, y1 = world_to_px(H, wx[j] + VX[j] * args.arrow_s,
                                     wy[j] + VY[j] * args.arrow_s, ks)
                cv2.arrowedLine(img, (int(x0), int(y0)), (int(x1), int(y1)),
                                (0, 140, 255), 3, tipLength=0.28)
                cv2.putText(img, f"v={v_now:.1f} cm/s (ab)", (int(x1) + 6, int(y1) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 140, 255), 2, cv2.LINE_AA)
        for a, b in zip(trail[:-1], trail[1:]):
            cv2.line(img, a, b, (0, 200, 255), 2)

        # HUD
        cv2.rectangle(img, (0, 0), (w, 96), (30, 30, 30), -1)
        cv2.putText(img, f"{args.version.upper()} | target {args.target:.0f} cm/s | "
                         f"measured {v_report:.2f} cm/s ({method}) | error {err_pct:+.1f}%",
                    (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, f"t={now:5.2f}s | v={v_now:5.1f} cm/s | area={cur_area:6.0f} | "
                         f"{'TRACK' if tracked else 'LOST'}",
                    (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1, cv2.LINE_AA)
        j = det_idx.get(fi)
        in_steady = j is not None and (s <= j <= e)
        if in_steady:
            cv2.putText(img, "STEADY", (12, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 220, 0), 2, cv2.LINE_AA)
        writer.write(img)
        i += 1
    cap.release(); writer.release()

    # ---------------- 四宫格报表 ----------------
    plt.rcParams.update({"figure.dpi": 120, "font.size": 9})
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    fig.suptitle(f"{args.version.upper()}  |  target {args.target:.0f} cm/s  |  "
                 f"measured {v_report:.2f} cm/s  |  error {err_pct:+.1f}%  |  "
                 f"failure {fail*100:.1f}%",
                 fontsize=12, fontweight="bold")

    ax[0, 0].plot(wx, wy, "-", lw=1.2, color="#1f77b4")
    if has_window:
        ax[0, 0].plot(wx[s:e + 1], wy[s:e + 1], "-", lw=3, color="#2ca02c", alpha=0.7,
                      label="steady window")
    ax[0, 0].set_xlabel("X (cm)"); ax[0, 0].set_ylabel("Y (cm)")
    ax[0, 0].set_title(f"Trajectory ({'plane-corrected' if ks != 1.0 else 'raw geometry'})")
    ax[0, 0].legend(loc="best"); ax[0, 0].grid(alpha=0.3)

    ax[0, 1].plot(t, wx, lw=1.2, color="#1f77b4", label="X")
    ax[0, 1].plot(t, wy, lw=1.0, color="#ff7f0e", label="Y")
    if has_window:
        ax[0, 1].axvspan(t[s], t[e], color="#2ca02c", alpha=0.15)
    ax[0, 1].set_xlabel("t (s)"); ax[0, 1].set_ylabel("position (cm)")
    ax[0, 1].set_title("X / Y vs time"); ax[0, 1].legend(loc="best"); ax[0, 1].grid(alpha=0.3)

    ax[1, 0].plot(t, V, lw=1.2, color="#1f77b4", label="speed")
    ax[1, 0].axhline(args.target, color="#2ca02c", ls="--", lw=1, label="target")
    ax[1, 0].axhspan(args.target * 0.85, args.target * 1.15, color="#2ca02c", alpha=0.12,
                     label="±15%")
    if has_window:
        ax[1, 0].axhline(v_steady, color="#d62728", ls=":", lw=1,
                         label=f"steady mean {v_steady:.2f}")
        ax[1, 0].axvspan(t[s], t[e], color="#2ca02c", alpha=0.12)
    else:
        ax[1, 0].text(0.5, 0.92, "no valid steady window (≥1.0 s)", ha="center",
                      va="top", transform=ax[1, 0].transAxes, color="#d62728", fontsize=9)
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
    win_txt = (f"{t[s]:.2f}~{t[e]:.2f}s（{t[e] - t[s]:.2f} s）" if has_window
               else f"无有效段（判据 ≥{config.STEADY_MIN_DURATION_S:.1f} s）")
    print(f"  版本 {args.version} | 目标 {args.target:.0f} | 报道速度 {v_report:.2f} cm/s | "
          f"误差 {err_pct:+.1f}% | 稳态窗 {win_txt} | 失败率 {fail*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
