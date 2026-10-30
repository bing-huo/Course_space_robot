#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收实验会话：按「一个光强 → 两个速度 → 换光强」的顺序录制，最后自动批量测量

用法（在 第二学期/ 下运行）：
    python -m tools.acceptance_session                 # 默认 L1 L2 L3，21/31 cm/s，每个组合 1 次
    python -m tools.acceptance_session --levels L1 L2 L3 --speeds 21 31 --reps 1
    python -m tools.acceptance_session --dry-run       # 只打印流程，不录、不调用相机

流程：
    对每个光照等级：
        1. 提示把灯调到该档，输入照度计读数（lx），自动写进 conditions.csv；
        2. 21 cm/s 录 1 段（5 秒倒计时 + 15 秒录制）；
        3. 31 cm/s 录 1 段；
    全部录完，问是否跑 tools.batch_measure 出 summary.csv。

文件名：out/acceptance/<等级>_<速度>_<次数>.mp4，例如 L1_21_1.mp4。
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

COND_FIELDS = ["等级", "照度_lx", "灯A距离_m", "灯B距离_m", "备注"]


def update_lux(path: Path, level: str, lux: float) -> None:
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    found = False
    for r in rows:
        if r.get("等级", "").strip() == level:
            r["照度_lx"] = f"{lux:g}"
            found = True
    if not found:
        rows.append({"等级": level, "照度_lx": f"{lux:g}",
                     "灯A距离_m": "", "灯B距离_m": "", "备注": ""})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COND_FIELDS)
        w.writeheader()
        w.writerows(rows)


def ask(prompt: str, dry: bool, default: str = "") -> str:
    if dry:
        print(f"{prompt} [dry-run 默认: {default!r}]")
        return default
    try:
        return input(prompt)
    except EOFError:
        return default


def countdown(seconds: int = 5) -> None:
    for i in range(seconds, 0, -1):
        print(f"  {i}...", end="", flush=True)
        time.sleep(1)
    print("  GO")


def record(video: Path, exposure: float, gain: float, dry: bool) -> float | None:
    cmd = [sys.executable, "-m", "camera.camera_capture",
           "--fps", "60", "--exposure", f"{exposure:g}", "--gain", f"{gain:g}",
           "record", str(video), "-s", "15"]
    if dry:
        print("    " + " ".join(cmd))
        return None
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    out = (r.stdout or "").strip().splitlines()
    fps = None
    for line in out[-4:]:
        print("    " + line.strip())
        if "实测" in line and "fps" in line:
            try:
                fps = float(line.split("实测")[1].split("fps")[0].split("（")[0].strip())
            except (IndexError, ValueError):
                pass
    if r.returncode != 0:
        print(f"    ⚠ 录制返回码 {r.returncode}")
    return fps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="验收实验会话（光强→速度→次数）")
    ap.add_argument("--levels", nargs="+", default=["L1", "L2", "L3"])
    ap.add_argument("--speeds", nargs="+", type=float, default=[21.0, 31.0])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--outdir", default="out/acceptance")
    ap.add_argument("--conditions", default="data/2026-10-30_验收/conditions.csv")
    ap.add_argument("--exposure", type=float, default=10000.0)
    ap.add_argument("--gain", type=float, default=6.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    cond = Path(args.conditions)
    if not args.dry_run:
        outdir.mkdir(parents=True, exist_ok=True)
    print("=" * 64)
    print(f"  验收录制：等级 {args.levels}｜速度 {args.speeds}｜每个组合 {args.reps} 次")
    print(f"  输出 {outdir}｜条件表 {cond}")
    print("=" * 64)

    for level in args.levels:
        print(f"\n########## {level} ##########")
        lux_txt = ask(f"把灯调到 {level} 档；照度计读数（lx，回车跳过）：", args.dry_run, "")
        lux_txt = lux_txt.strip()
        if lux_txt:
            try:
                lux = float(lux_txt)
                if args.dry_run:
                    print(f"  [dry-run] 会写入 {level} = {lux:g} lx")
                else:
                    update_lux(cond, level, lux)
                    print(f"  ✓ {level} = {lux:g} lx 已写入 {cond.name}")
            except ValueError:
                print("  ⚠ 不是数字，跳过记录（可事后手填 conditions.csv）")

        for speed in args.speeds:
            print(f"\n--- {level} · {speed:g} cm/s ---")
            for rep in range(1, args.reps + 1):
                video = outdir / f"{level}_{speed:g}_{rep}.mp4"
                if video.exists() and not args.dry_run:
                    keep = ask(f"  {video.name} 已存在，回车覆盖（输入 s 跳过）：", False, "")
                    if keep.strip().lower() == "s":
                        print("  跳过")
                        continue
                print(f"  [{level} {speed:g} cm/s 第 {rep}/{args.reps} 次] 把小车放回起点")
                if not args.dry_run:
                    input("  按回车开始 5 秒倒计时…")
                countdown(5)
                fps = record(video, args.exposure, args.gain, args.dry_run)
                if fps:
                    print(f"    → 实测 {fps:.1f} fps｜{video}")
                if not args.dry_run and not (rep == args.reps and speed == args.speeds[-1]
                                             and level == args.levels[-1]):
                    input("  按回车继续（可先摆好下一趟）…")

    print("\n" + "=" * 64)
    print("  录制结束。逐段结果可直接跑批量测量：")
    print(f"    python -m tools.batch_measure --dir {outdir} --lux-file \"{cond}\"")
    print("=" * 64)
    if not args.dry_run:
        ans = ask("现在就跑批量测量？(Y/n)：", False, "y").strip().lower()
        if ans in ("", "y", "yes"):
            r = subprocess.run([sys.executable, "-m", "tools.batch_measure",
                                "--dir", str(outdir), "--lux-file", str(cond)])
            return r.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
