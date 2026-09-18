#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓库结构迁移（第二学期）—— 默认 dry-run，不碰任何文件。

用法：
    python tools/migrate_repo.py            # 只打印将要做的事
    python tools/migrate_repo.py --apply    # 真正执行

设计原则见 docs/仓库结构_v2.md：
  · 只移动 v2 §9.2 / P0.3.g 明确要求归档的素材，其余一律新建、不动
  · CV/ 目录冻结保留，本脚本不会碰它除两段基线视频以外的任何文件
  · 用 git mv 保留历史（没有 .git 时退化为普通移动）
  · 不删除任何文件；出问题用 git reset --hard HEAD 整体回滚
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 配置

# 要移动的文件：(源, 目标)，相对于仓库根
MOVES = [
    ("CV/test_video_21.mp4", "data/v1_baseline/test_video_21.mp4"),
    ("CV/test_video_31.mp4", "data/v1_baseline/test_video_31.mp4"),
]

# 要确保存在的目录（放 .gitkeep 占位，让空目录也能进版本库）
DIRS = [
    "camera",
    "calibration",
    "lighting",
    "realtime",
    "analysis",
    "tools",
    "data/v1_baseline",
    "data/detect_log",
    "data/ground_truth",
    "data/results",
]

# ---------------------------------------------------------------- 工具


def repo_root() -> Path:
    """从本脚本位置推仓库根：tools/migrate_repo.py -> 上一级。"""
    return Path(__file__).resolve().parent.parent


def has_git(root: Path) -> bool:
    return (root / ".git").exists()


def do_move(root: Path, src_rel: str, dst_rel: str, apply: bool) -> str:
    src, dst = root / src_rel, root / dst_rel

    if not src.exists():
        if dst.exists():
            return f"  跳过（已迁移）：{src_rel}"
        return f"  ⚠ 跳过（源文件不存在）：{src_rel}"

    if dst.exists():
        return f"  ⚠ 跳过（目标已存在，不覆盖）：{dst_rel}"

    if has_git(root):
        cmd = ["git", "mv", src_rel, dst_rel]
    else:
        cmd = None

    if not apply:
        shown = " ".join(cmd) if cmd else f"move {src_rel} -> {dst_rel}"
        return f"  [dry-run] {shown}"

    dst.parent.mkdir(parents=True, exist_ok=True)
    if cmd:
        try:
            subprocess.run(cmd, cwd=root, check=True)
            return f"  ✓ 已移动（git mv，保留历史）：{src_rel} -> {dst_rel}"
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            # 文件未被 git 跟踪、或机器上没装 git —— 退回普通移动，不让脚本崩掉
            print(f"  ⚠ git mv 不可用（{type(exc).__name__}），改用普通移动")
    shutil.move(str(src), str(dst))
    return f"  ✓ 已移动：{src_rel} -> {dst_rel}"


def ensure_dirs(root: Path, apply: bool) -> list:
    lines = []
    for d in DIRS:
        path = root / d
        keep = path / ".gitkeep"
        if path.exists() and keep.exists():
            lines.append(f"  已存在：{d}/")
            continue
        if path.exists() and any(path.iterdir()):
            # 目录虽然没占位文件但已经有内容（比如 camera/ 里已有代码），跳过
            lines.append(f"  已存在且非空，跳过：{d}/")
            continue
        if not apply:
            lines.append(f"  [dry-run] mkdir -p {d}/")
            continue
        path.mkdir(parents=True, exist_ok=True)
        keep.touch()
        lines.append(f"  ✓ 已创建：{d}/")
    return lines


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="仓库结构迁移（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正执行；不加则只打印")
    args = ap.parse_args()

    root = repo_root()
    print(f"仓库根：{root}")
    print(f"模式：{'执行' if args.apply else 'dry-run（不会改动任何文件）'}")
    print(f"git 仓库：{'是' if has_git(root) else '否（将退化为普通移动）'}\n")

    print("一、创建目录")
    for line in ensure_dirs(root, args.apply):
        print(line)

    print("\n二、迁移素材（依据 P0.3.g / v2 §9.2）")
    for src, dst in MOVES:
        print(do_move(root, src, dst, args.apply))

    print("\n三、未处理（本脚本有意不动）")
    for line in [
        "  CV/ 除上述两段视频外的全部文件 —— 冻结保留，见 docs/仓库结构_v2.md 原则 1",
        "  CV/calibration_config.json —— 断开与 step1_calibrate.py 的路径依赖，得不偿失",
        "  docs/ 下的规格书 PDF —— 文件名含日期批次，是溯源凭据",
        "  .obsidian/ —— 仓库同时是 Obsidian 库，保留",
    ]:
        print(line)

    if not args.apply:
        print("\n以上均为预演。确认无误后执行：python tools/migrate_repo.py --apply")
        print("若要回滚：git reset --hard HEAD")
    else:
        print("\n完成。建议接着跑一遍 git status 确认改动符合预期。")

    return 0


if __name__ == "__main__":
    sys.exit(main())