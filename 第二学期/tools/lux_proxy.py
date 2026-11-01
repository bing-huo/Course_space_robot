"""用相机画面估计相对光强与时间稳定性（无需再实验）

同一固定表面、同一曝光/增益下，灰度 ∝ 照度（线性传感器）。
本工具对每段视频计算：
  - 全帧中位灰度（对运动目标鲁棒）
  - 参考面（右上角固定亮面）中位灰度：用于看档内时间波动
输出 out/acceptance/lux_proxy.csv 并打印表格。
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

PATCH = (60, 200, 950, 1200)  # y0, y1, x0, x1：右上角固定亮面


def analyze(video: Path, step: int = 6):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"打不开 {video}")
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    full, patch = [], []
    for i in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, img = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        y0, y1, x0, x1 = PATCH
        full.append(float(np.median(g)))
        patch.append(float(np.median(g[y0:y1, x0:x1])))
    cap.release()
    full, patch = np.array(full), np.array(patch)
    return dict(frames=n,
                full_mean=full.mean(), full_std=full.std(),
                patch_mean=patch.mean(), patch_std=patch.std(),
                patch_min=patch.min(), patch_max=patch.max(),
                jitter=float(np.mean(np.abs(np.diff(patch)))) if len(patch) > 1 else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="out/acceptance")
    ap.add_argument("--out", default="out/acceptance/lux_proxy.csv")
    ap.add_argument("--step", type=int, default=6, help="每隔几帧采样一次")
    args = ap.parse_args()
    rows = []
    for p in sorted(Path(args.dir).glob("L*_*.mp4")):
        r = analyze(p, args.step)
        rows.append(dict(视频=p.stem, 帧数=r["frames"],
                         全帧中位=f"{r['full_mean']:.1f}", 全帧波动_pct=f"{100*r['full_std']/r['full_mean']:.1f}",
                         参考面中位=f"{r['patch_mean']:.1f}", 参考面波动_pct=f"{100*r['patch_std']/r['patch_mean']:.1f}",
                         参考面范围=f"{r['patch_min']:.0f}~{r['patch_max']:.0f}",
                         帧间抖动=f"{r['jitter']:.2f}"))
        print(f"{p.stem:10s} 全帧 {r['full_mean']:6.1f}（±{100*r['full_std']/r['full_mean']:.1f}%）"
              f"  参考面 {r['patch_mean']:6.1f}（±{100*r['patch_std']/r['patch_mean']:.1f}%）"
              f"  范围 {r['patch_min']:.0f}~{r['patch_max']:.0f}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"\n✓ {out}")


if __name__ == "__main__":
    main()
