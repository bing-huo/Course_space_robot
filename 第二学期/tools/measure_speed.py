#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测速 v2：自适应亮度门限 + Alpha-Beta 平滑 + 稳态窗自动选取

    cd 第二学期
    python -m tools.measure_speed --video out/truss_20_15s.mp4 --target 21

相对 v1（tools/analyze_run.py）的改进：
    1. 亮度门限**自适应**：thr = 中位灰度 + 0.5×(P95 − 中位)，换光照等级不用改常数
    2. 速度用 **Alpha-Beta 滤波**输出，而不是逐帧差分
    3. **稳态窗自动选取**：|v − v_target|/v_target ≤ 15% 且连续 ≥ 1.0 s
    4. 输出逐帧检测日志（失败率的数据来源）

注意：本脚本只做"测量"，不做标定。世界坐标由 calibration_config.json 的 H 给出。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

import config


def load_H(path: str):
    H = np.array(json.loads(Path(path).read_text(encoding="utf-8"))["H"], np.float64)
    return H, np.linalg.inv(H)


def to_world(H_inv, u, v):
    p = cv2.perspectiveTransform(np.array([[[u, v]]], np.float64), H_inv)[0, 0]
    return float(p[0]), float(p[1])


def ab_filter(xs, ys, dt, alpha=0.15, beta=0.005):
    """Alpha-Beta：返回平滑后的 (x, y, vx, vy) 序列。"""
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="测速 v2")
    ap.add_argument("--video", required=True)
    ap.add_argument("--target", type=float, required=True, help="目标速度 cm/s")
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    ap.add_argument("--area-min", type=float, default=config.CONTOUR_AREA_MIN)
    ap.add_argument("--steady-tol", type=float, default=config.STEADY_TOL)
    ap.add_argument("--steady-min-s", type=float, default=config.STEADY_MIN_DURATION_S)
    ap.add_argument("--alpha", type=float, default=0.15)
    ap.add_argument("--beta", type=float, default=0.005)
    ap.add_argument("--plane-scale", type=float, default=None,
                    help="覆盖等效平面修正；给 1.0 可看未修正的原始速度")
    ap.add_argument("--log", default="", help="逐帧日志输出 csv（可选）")
    args = ap.parse_args(argv)

    H, H_inv = load_H(args.calib)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"✗ 打不开 {args.video}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    w_img = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_img = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    mog = cv2.createBackgroundSubtractorMOG2(
        history=config.MOG2_HISTORY, varThreshold=config.MOG2_VAR_THRESHOLD,
        detectShadows=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (config.MORPH_KERNEL_SIZE, config.MORPH_KERNEL_SIZE))

    frames = []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        med, p95 = float(np.median(gray)), float(np.percentile(gray, 95))
        thr = med + 0.5 * (p95 - med)                      # 自适应门限
        fg = mog.apply(gray)
        hard = np.where((fg == 255) & (gray >= thr), 255, 0).astype(np.uint8)
        hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, k)
        hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, k)
        cs, _ = cv2.findContours(hard, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rec = {"i": i, "t": i / fps, "ok": False, "u": 0.0, "v": 0.0,
               "area": 0.0, "thr": thr,
               "bx": 0, "by": 0, "bw": 0, "bh": 0}
        if cs:
            c = max(cs, key=cv2.contourArea)
            a = float(cv2.contourArea(c))
            M = cv2.moments(c)
            if a >= args.area_min and M["m00"] > 0:
                bx, by, bw, bh = cv2.boundingRect(c)
                rec.update(ok=True, area=a,
                           u=M["m10"] / M["m00"], v=M["m01"] / M["m00"],
                           bx=bx, by=by, bw=bw, bh=bh)
        frames.append(rec)
        i += 1
    cap.release()

    det = [r for r in frames if r["ok"]]
    if len(det) < 10:
        print("✗ 检出帧太少")
        return 1

    ks = config.PLANE_SCALE if args.plane_scale is None else args.plane_scale
    wx = np.array([to_world(H_inv, r["u"], r["v"])[0] for r in det]) * ks
    wy = np.array([to_world(H_inv, r["u"], r["v"])[1] for r in det]) * ks
    t = np.array([r["t"] for r in det])
    dt = 1.0 / fps
    X, Y, VX, VY = ab_filter(wx, wy, dt, args.alpha, args.beta)
    V = np.hypot(VX, VY)

    # ---- 稳态窗：位置中段 + 速度 ±tol + 帧间隔连续 + 时长 ≥ min ----
    m_px = int(round(config.ROI_MARGIN_CM * config.PX_PER_CM))
    roi_l, roi_t, roi_r, roi_b = m_px, m_px, w_img - m_px, h_img - m_px

    in_mid = np.array([
        (r["bx"] >= roi_l and r["bx"] + r["bw"] <= roi_r and
         r["by"] >= roi_t and r["by"] + r["bh"] <= roi_b) for r in det])
    in_tol = np.abs(V - args.target) / args.target <= args.steady_tol
    ok_mask = in_tol & in_mid
    fi = np.array([r["i"] for r in det], int)

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

    valid = [(a, b) for a, b in runs if t[b] - t[a] >= args.steady_min_s]
    has_window = bool(valid)
    if has_window:
        s, e = max(valid, key=lambda ab: t[ab[1]] - t[ab[0]])
    elif runs:
        s, e = max(runs, key=lambda ab: t[ab[1]] - t[ab[0]])
    else:
        s, e = 0, -1
    dur = t[e] - t[s] if e > s else 0.0
    v_steady = float(np.mean(V[s:e + 1])) if has_window else float("nan")
    v_global = float(np.mean(V))

    # 失败率：目标在画面内的帧（首次检出 → 末次检出）
    t0, t1 = det[0]["t"], det[-1]["t"]
    win = [r for r in frames if t0 <= r["t"] <= t1]
    hit = sum(1 for r in win if r["ok"])
    fail = 1 - hit / len(win) if win else 1.0

    print(f"视频      {args.video}")
    print(f"帧率      {fps:.1f} fps，总帧 {len(frames)}")
    print(f"检出      统计窗 {t0:.2f}~{t1:.2f}s（{len(win)} 帧）→ 失败率 {fail*100:.1f}%")
    print(f"轮廓面积  中位 {np.median([r['area'] for r in det]):.0f} px²")
    print(f"速度      全程均 {v_global:.2f} cm/s")
    longest = max((t[b] - t[a] for a, b in runs), default=0.0)
    print(f"候选帧    位置 {int(in_mid.sum())}/{len(det)}｜速度 {int(in_tol.sum())}/{len(det)}"
          f"｜连续段 {len(runs)} 个，最长 {longest:.2f} s")
    if has_window:
        print(f"稳态窗    {t[s]:.2f}~{t[e]:.2f}s（{dur:.2f} s，{e - s + 1} 帧）→ "
              f"{v_steady:.2f} cm/s")
        print(f"相对误差  {(v_steady - args.target) / args.target * 100:+.1f}%"
              f"（目标 {args.target:.1f} cm/s）")
    else:
        print(f"稳态窗    无有效段（最长连续段仅 {longest:.2f} s，判据 ≥"
              f"{args.steady_min_s:.1f} s）→ 该次按失败处理")
    print(f"判据      位置 ROI 内缩 {config.ROI_MARGIN_CM:.0f} cm｜速度 ±"
          f"{args.steady_tol * 100:.0f}%｜帧号间隔 ≤{config.MAX_GAP_FRAMES}｜"
          f"时长 ≥{args.steady_min_s:.1f} s")

    if args.log:
        p = Path(args.log)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frame", "t", "ok", "area", "u", "v", "thr"])
            for r in frames:
                w.writerow([r["i"], f"{r['t']:.4f}", int(r["ok"]),
                            f"{r['area']:.1f}", f"{r['u']:.1f}", f"{r['v']:.1f}",
                            f"{r['thr']:.1f}"])
        print(f"逐帧日志  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
