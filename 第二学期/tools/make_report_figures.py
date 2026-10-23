#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
汇报示意图生成（第二学期）

    python tools/make_report_figures.py              # 全部生成到 out/figures/
    python tools/make_report_figures.py pipeline     # 只生成接入链路图
    python tools/make_report_figures.py --outdir docs/figures

生成的图：
    fig_camera_pipeline.png    相机接入链路（从驱动到应用，四格流程）
    fig_spec_vs_measured.png   相机能力核对：规格书 vs 实测

★ 字体：中文标注依赖系统里的中文字体，脚本会自动挑一个可用的
  （Windows 上通常是 Microsoft YaHei 或 SimHei）。挑不到会明确报错退出，
  不会静默画出一堆方块。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # 必须在 pyplot 之前，无窗口环境也能跑
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# ---------------------------------------------------------------- 配色

BLUE_EDGE = "#2E75B6"
BLUE_FILL = "#EAF3FC"
BLUE_TEXT = "#1F3864"
BLUE_SUB = "#2F5496"
GREEN_EDGE = "#4CAF50"
GREEN_FILL = "#EAF7EC"
GREEN_TEXT = "#2E7D32"
CHECK = "#2E9E4F"
ARROW = "#2E75B6"
GRID = "#F5F8FC"

CJK_CANDIDATES = (
    "Microsoft YaHei", "微软雅黑", "SimHei", "黑体",
    "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
    "WenQuanYi Zen Hei",
)


def setup_font() -> str:
    """挑一个能显示中文的字体，挑不到就报错退出。"""
    for name in CJK_CANDIDATES:
        try:
            fm.findfont(name, fallback_to_default=False)
        except Exception:                  # noqa: BLE001
            continue
        plt.rcParams["font.sans-serif"] = [name]
        plt.rcParams["axes.unicode_minus"] = False
        return name
    print("✗ 找不到可用的中文字体。装一个，或把字体名加进 CJK_CANDIDATES"
          "（Windows 自带 'Microsoft YaHei'）。")
    sys.exit(1)


def _canvas(**kw):
    """铺一张满幅画布：坐标直接用 0~1，标题和内容都在同一套坐标里，
    这样靠 bbox_inches='tight' 裁出来不会有夹心空白。"""
    fig = plt.figure(**kw)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


# ---------------------------------------------------------------- 元件


def _box(ax, x, y, w, h, title, subtitle, *, badge="", accent=BLUE_EDGE,
         fill=BLUE_FILL, title_color=BLUE_TEXT, sub_color=BLUE_SUB, done=True):
    """一个圆角框：编号 + 标题 + 副标题 + 右上角对勾。"""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.006,rounding_size=0.03",
        linewidth=1.8, edgecolor=accent, facecolor=fill, zorder=1))

    if badge:
        ax.text(x + 0.016, y + h - 0.03, badge, ha="left", va="top",
                fontsize=11.5, fontweight="bold", color=accent, zorder=3)

    ax.text(x + w / 2, y + h * 0.60, title, ha="center", va="center",
            fontsize=13.5, fontweight="bold", color=title_color, zorder=2)
    ax.text(x + w / 2, y + h * 0.27, subtitle, ha="center", va="center",
            fontsize=9, color=sub_color, zorder=2, linespacing=1.8)

    if done:
        ax.text(x + w - 0.016, y + h - 0.03, "✓", ha="right", va="top",
                fontsize=13, fontweight="bold", color=CHECK, zorder=3)


def _arrow(ax, x0, x1, y, color=ARROW):
    ax.annotate("", xy=(x1, y), xytext=(x0, y),
                arrowprops=dict(arrowstyle="-|>", color=color,
                                linewidth=1.9, mutation_scale=16),
                zorder=1)


# ---------------------------------------------------------------- 图一


def fig_pipeline(outdir: Path, dpi: int) -> Path:
    """相机接入链路：从驱动到应用，四格流程。"""
    steps = [
        dict(badge="①", title="硬件接入",
             subtitle="USB 3.0 直连主机\n设备正常枚举"),
        dict(badge="②", title="MVS 客户端",
             subtitle="海康官方驱动与运行库\n连续出图（保底验证）"),
        dict(badge="③", title="Python 绑定",
             subtitle="MvImport 接入项目\n可枚举设备并读参数"),
        dict(badge="④", title="应用层封装",
             subtitle="逐帧取图 ✓   硬件时间戳 ✓\nFrameID ✓",
             accent=GREEN_EDGE, fill=GREEN_FILL,
             title_color=GREEN_TEXT, sub_color=GREEN_TEXT),
    ]

    fig, ax = _canvas(figsize=(13.5, 2.5))
    ax.text(0.5, 0.93, "从驱动到应用：相机接入链路", ha="center", va="center",
            fontsize=15, fontweight="bold", color=BLUE_TEXT)

    n = len(steps)
    w, gap = 0.18, 0.0933
    x0 = (1.0 - (n * w + (n - 1) * gap)) / 2
    y, h = 0.07, 0.72

    for i, s in enumerate(steps):
        _box(ax, x0 + i * (w + gap), y, w, h, **s)

    for i in range(n - 1):
        _arrow(ax, x0 + i * (w + gap) + w + 0.008,
               x0 + (i + 1) * (w + gap) - 0.008, y + h / 2)

    out = outdir / "fig_camera_pipeline.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight", pad_inches=0.06,
                facecolor="white")
    plt.close(fig)
    return out


# ---------------------------------------------------------------- 图二


def fig_spec_vs_measured(outdir: Path, dpi: int) -> Path:
    """相机能力核对：规格书 vs 实测。"""
    rows = [
        ("曝光时间", "9 μs ~ 10 s", "9 μs ~ 10.0 s"),
        ("增益", "0 ~ 16 dB", "0 ~ 16.37 dB"),
        ("像素格式", "Bayer GB8", "Bayer GB8"),
        ("分辨率", "1280 × 1024", "1280 × 1024"),
    ]
    headers = ("参数", "规格书标称", "实测值", "核对")
    cols = (0.03, 0.30, 0.60, 0.88)

    fig, ax = _canvas(figsize=(9.6, 3.2))
    ax.text(0.5, 0.945, "相机能力核对：规格书 vs 实测", ha="center", va="center",
            fontsize=15, fontweight="bold", color=BLUE_TEXT)

    n = len(rows)
    top, rh = 0.86, 0.15
    y_head = top

    for cx, head in zip(cols, headers):
        ax.text(cx, y_head, head, ha="left", va="center",
                fontsize=11.5, fontweight="bold", color=BLUE_TEXT)
    ax.plot([0.02, 0.98], [y_head - rh * 0.55] * 2, color=BLUE_EDGE, linewidth=1.4)

    for i, (name, spec, meas) in enumerate(rows):
        cy = y_head - rh * (i + 1) - rh * 0.1
        if i % 2 == 1:                                   # 斑马纹
            ax.add_patch(FancyBboxPatch(
                (0.015, cy - rh * 0.42), 0.97, rh * 0.84,
                boxstyle="square,pad=0", linewidth=0, facecolor=GRID, zorder=0))
        ax.text(cols[0], cy, name, ha="left", va="center",
                fontsize=11, color="#333333", zorder=2)
        ax.text(cols[1], cy, spec, ha="left", va="center",
                fontsize=11, color="#666666", zorder=2)
        ax.text(cols[2], cy, meas, ha="left", va="center",
                fontsize=11, fontweight="bold", color=BLUE_TEXT, zorder=2)
        ax.text(cols[3], cy, "✓", ha="left", va="center",
                fontsize=13, fontweight="bold", color=CHECK, zorder=2)

    ax.text(0.03, 0.055,
            "读自 MVS SDK 能力寄存器，非手册抄录；各项逐条吻合",
            ha="left", va="center", fontsize=9.5, color="#888888")

    out = outdir / "fig_spec_vs_measured.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight", pad_inches=0.08,
                facecolor="white")
    plt.close(fig)
    return out


# ---------------------------------------------------------------- 入口

FIGURES = {
    "pipeline": ("相机接入链路", fig_pipeline),
    "spec": ("相机能力核对", fig_spec_vs_measured),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="生成汇报示意图",
        epilog="可选名字：" + "、".join(f"{k}（{v[0]}）" for k, v in FIGURES.items()))
    ap.add_argument("which", nargs="*", default=[],
                    help="要生成哪几张；不给就全部生成")
    ap.add_argument("--outdir", default="out/figures", help="输出目录")
    ap.add_argument("--dpi", type=int, default=300, help="分辨率，默认 300")
    args = ap.parse_args(argv)

    unknown = [k for k in args.which if k not in FIGURES]
    if unknown:
        ap.error(f"不认识的名字：{'、'.join(unknown)}；可选：{'、'.join(FIGURES)}")

    font = setup_font()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    which = args.which or list(FIGURES)
    print(f"中文字体：{font}")
    print(f"输出目录：{outdir.resolve()}\n")

    for key in which:
        print(f"  ✓ {FIGURES[key][1](outdir, args.dpi)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())