#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收批量测量：把一个目录下的视频全部跑一遍，输出逐段与汇总两份 CSV

用法：
    cd 第二学期
    python -m tools.batch_measure --dir out/acceptance --lux-file data/2026-10-30_验收/conditions.csv

文件名约定（必须有等级、速度、次数三段数字）：
    L1_21_1.mp4   L1_21_2.mp4   L1_21_3.mp4
    L1_30_1.mp4   ...
    等级可写 L1/L2/L3（也接受任意字母+数字，如 A1）

输出：
    <dir>/summary.csv   每个（等级, 速度）一行：速度均值、误差均值、失败率均值、判定
    <dir>/raw.csv       每个视频一行
    <dir>/detect_logs/  逐帧检测日志（可选，--logdir 指定，默认自动放这里）
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

PAT = re.compile(r"(?P<level>[A-Za-z]+\d+)_(?P<speed>\d+(?:\.\d+)?)_(?P<rep>\d+)")
V_LIMIT = 0.20      # 指标 1：速度相对误差 ≤20%
F_LIMIT = 0.15      # 指标 2：检测失败率 ≤15%


def parse_out(text: str) -> dict:
    d = {}
    m = re.search(r"失败率\s+([\d.]+)%", text)
    d["fail_pct"] = float(m.group(1)) if m else None
    m = re.search(
        r"稳态窗\s+([\d.]+)~([\d.]+)s（([\d.]+) s，(\d+) 帧）→ ([\d.]+) cm/s", text)
    if m:
        d.update(win_start=float(m.group(1)), win_end=float(m.group(2)),
                 win_dur=float(m.group(3)), win_frames=int(m.group(4)),
                 v_steady=float(m.group(5)))
    else:
        d.update(win_start=None, win_end=None, win_dur=None, win_frames=None,
                 v_steady=None)
        d["no_window"] = "无有效段" in text
    m = re.search(r"相对误差\s+([+-]?[\d.]+)%", text)
    d["err_pct"] = float(m.group(1)) if m else None
    m = re.search(r"轮廓面积\s+中位 ([\d.]+) px²", text)
    d["area_med"] = float(m.group(1)) if m else None
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="验收批量测量")
    ap.add_argument("--dir", required=True, help="视频目录，如 out/acceptance")
    ap.add_argument("--calib", default="calibration/calibration_config.json")
    ap.add_argument("--lux-file", default="",
                    help="光照条件表（两列：等级,照度_lx），用于汇总里带上照度")
    ap.add_argument("--logdir", default="", help="逐帧日志目录（默认 <dir>/detect_logs）")
    args = ap.parse_args(argv)

    d = Path(args.dir)
    if not d.is_dir():
        print(f"✗ 目录不存在：{d}")
        return 1
    vids = sorted(p for p in d.glob("*.mp4") if PAT.search(p.stem))
    if not vids:
        print("✗ 没找到符合 <等级>_<速度>_<次数>.mp4 的文件")
        return 1

    logdir = Path(args.logdir) if args.logdir else d / "detect_logs"
    logdir.mkdir(parents=True, exist_ok=True)

    lux = {}
    if args.lux_file:
        lp = Path(args.lux_file)
        if lp.is_file():
            with lp.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        lux[row["等级"].strip()] = float(str(row["照度_lx"]).strip())
                    except (KeyError, ValueError):
                        pass
            print(f"光照条件：{ ', '.join(f'{k}={v:.0f}lx' for k, v in lux.items()) }")

    raw = []
    for p in vids:
        m = PAT.search(p.stem)
        level, speed, rep = m.group("level"), float(m.group("speed")), int(m.group("rep"))
        log = logdir / f"{p.stem}_detect_log.csv"
        cmd = [sys.executable, "-m", "tools.measure_speed",
               "--video", str(p), "--target", str(speed), "--calib", args.calib,
               "--log", str(log)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore")
        text = (r.stdout or "") + (r.stderr or "")
        rec = dict(level=level, target=speed, rep=rep, video=p.name, **parse_out(text))
        rec["rc"] = r.returncode
        raw.append(rec)
        ws = (f"{rec['v_steady']:.2f} cm/s" if rec["v_steady"] is not None
              else "无有效段")
        print(f"{p.name:14s} 稳态 {ws:>12s}  误差 {rec['err_pct']:>6}%  "
              f"失败率 {rec['fail_pct']:>5}%")

    # 逐段
    raw_path = d / "raw.csv"
    with raw_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["等级", "目标速度_cms", "次数", "视频", "稳态速度_cms",
                    "相对误差_pct", "失败率_pct", "稳态窗_s", "轮廓面积中位_px2", "备注"])
        for r in raw:
            note = "无有效稳态段" if r.get("no_window") else ""
            w.writerow([r["level"], r["target"], r["rep"], r["video"],
                        f"{r['v_steady']:.2f}" if r["v_steady"] is not None else "",
                        f"{r['err_pct']:+.1f}" if r["err_pct"] is not None else "",
                        f"{r['fail_pct']:.1f}" if r["fail_pct"] is not None else "",
                        f"{r['win_dur']:.2f}" if r["win_dur"] is not None else "",
                        f"{r['area_med']:.0f}" if r["area_med"] is not None else "",
                        note])

    # 汇总
    groups = {}
    for r in raw:
        groups.setdefault((r["level"], r["target"]), []).append(r)
    summ_path = d / "summary.csv"
    with summ_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["等级", "照度_lx", "目标速度_cms", "次数",
                    "稳态速度均值_cms", "误差均值_pct", "失败率均值_pct",
                    "指标1_速度≤20%", "指标2_失败率≤15%", "总体判定", "备注"])
        for (level, target), rs in sorted(groups.items()):
            ok = [r for r in rs if r["v_steady"] is not None and r["fail_pct"] is not None]
            n = len(rs)
            if ok:
                v_mean = sum(r["v_steady"] for r in ok) / len(ok)
                e_mean = sum(r["err_pct"] for r in ok) / len(ok)
                f_mean = sum(r["fail_pct"] for r in ok) / len(ok)
                m1 = abs(e_mean) / 100.0 <= V_LIMIT
                m2 = f_mean / 100.0 <= F_LIMIT
                note = "" if len(ok) == n else f"{n - len(ok)} 段无有效稳态"
                w.writerow([level, f"{lux.get(level, ''):.0f}" if level in lux else "",
                            f"{target:.0f}", n, f"{v_mean:.2f}", f"{e_mean:+.1f}",
                            f"{f_mean:.1f}", "是" if m1 else "否",
                            "是" if m2 else "否", "达标" if (m1 and m2) else "未达标", note])
            else:
                w.writerow([level, "", f"{target:.0f}", n, "", "", "", "否", "否",
                            "未达标", "全部无有效稳态段"])
    print(f"\n✓ 逐段 {raw_path}")
    print(f"✓ 汇总 {summ_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
