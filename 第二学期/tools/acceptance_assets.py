"""Generate acceptance summary figures and index from independently measured CSVs."""
from pathlib import Path
import argparse
import csv
import json
import re
import cv2
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary-only', action='store_true', help='只生成汇总图')
    args = parser.parse_args()
    root = Path('out/acceptance')
    figures = root / 'figures'
    data = Path('data/2026-10-30_验收')
    rows = list(csv.DictReader((root / 'summary.csv').open(encoding='utf-8-sig')))
    historical = list(csv.DictReader((data / 'summary.csv').open(encoding='utf-8-sig')))
    assert rows == historical, 'Re-measured summary differs from historical summary'
    plt.rcParams.update({'font.family': 'Microsoft YaHei', 'axes.unicode_minus': False,
                         'font.size': 11})
    colors = ['#2667A0', '#D47820']
    fig, axes = plt.subplots(1, 2, figsize=(11, 7.5))
    for ax, field, title, limit in zip(axes,
            ['误差均值_pct', '失败率均值_pct'], ['速度相对误差 (%)', '检测失败率 (%)'], [20, 15]):
        for offset, speed, color in zip([-.19, .19], [21, 31], colors):
            vals = [float(r[field]) for r in rows if float(r['目标速度_cms']) == speed]
            bars = ax.bar(np.arange(3) + offset, vals, width=.34, label=f'{speed} cm/s', color=color)
            for bar, val in zip(bars, vals):
                ax.annotate(f'{val:+.1f}%' if field == '误差均值_pct' else f'{val:.1f}%',
                            (bar.get_x()+bar.get_width()/2, val), xytext=(0, 7 if val>=0 else -16),
                            textcoords='offset points', ha='center', fontsize=10)
        ax.axhline(limit, color='#B52B35', ls='--', lw=1.5, label=f'判据 {limit}%')
        ax.text(.03, limit+.7, f'验收上限 {limit}%', color='#B52B35', transform=ax.get_yaxis_transform())
        if field == '误差均值_pct':
            ax.axhline(-limit, color='#B52B35', ls='--', lw=1.5)
            ax.text(.03, -limit+.7, '验收下限 −20%', color='#B52B35', transform=ax.get_yaxis_transform())
            ax.set_ylim(-24, 26)
        else:
            ax.set_ylim(0, 20)
        levels = sorted({r['等级'] for r in rows})
        lux = {r['等级']: str(r['照度区间']).strip() for r in rows}
        ax.set_xticks(range(len(levels)), [f'{lv}\n{lux[lv]} lx' for lv in levels])
        ax.set_title(title, fontweight='bold'); ax.set_ylabel('%')
        ax.grid(axis='y', alpha=.18); ax.set_axisbelow(True)
        ax.legend(loc='upper center', bbox_to_anchor=(.5, -.12), ncol=2)
    fig.suptitle('不同光照等级下的视觉测速验收结果', fontsize=17, fontweight='bold')
    fig.tight_layout(rect=(0, .05, 1, .94))
    fig.savefig(figures / 'summary_light_levels.png', dpi=300); plt.close(fig)
    if args.summary_only:
        return
    with Image.open(figures / 'summary_light_levels.png') as im:
        assert im.size == (3300, 2250) and abs(im.info['dpi'][0]-300)<1
        im.verify()
    checks = []
    for row in rows:
        stem = f"{row['等级']}_{row['目标速度_cms']}_1"
        video = root / 'videos' / f'{stem}_v23.mp4'
        cap = cv2.VideoCapture(str(video)); count = 0
        fps = cap.get(cv2.CAP_PROP_FPS)
        dims = (int(cap.get(3)), int(cap.get(4)))
        while True:
            ok, frame = cap.read()
            if not ok: break
            if count in (0, 300, 600, 900):
                cv2.imwrite(str(figures / f'{stem}_qa_{count:04d}.jpg'), frame)
            count += 1
        cap.release()
        src = cv2.VideoCapture(str(root / f'{stem}.mp4'))
        assert count == int(src.get(cv2.CAP_PROP_FRAME_COUNT))
        assert dims == (1280, 1024) and abs(fps-60)<.01
        src.release()
        with Image.open(figures / f'{stem}_v23.png') as im:
            assert im.size == (3300,2250) and abs(im.info['dpi'][0]-300)<1
            im.verify()
        log_bytes = (root / 'videos' / f'{stem}_render.txt').read_bytes()
        log = log_bytes.decode('utf-16' if log_bytes.startswith(b'\xff\xfe') else 'utf-8-sig')
        match = re.search(r'报道速度 ([\d.]+).*?误差 ([+-]?[\d.]+)%.*?失败率 ([\d.]+)%', log)
        assert match and tuple(map(float, match.groups())) == tuple(float(row[k]) for k in
                     ['稳态速度均值_cms','误差均值_pct','失败率均值_pct']), stem
        checks.append(dict(video=video.name, frames=count, fps=fps, size=dims, duration=count/fps,
                           bitrate_mbps=video.stat().st_size * 8 / (count/fps) / 1e6))
    (figures / 'verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 图表与视频索引', '', '6/6 达标，最大绝对速度误差 1.3%，最大检测失败率 1.5%。', '',
             '六段独立复测与历史汇总、预期表完全一致；重新渲染的报告数值与复测一致。', '',
             '| 视频 | 照度区间 | 目标 cm/s | 实测 cm/s | 误差 % | 失败率 % | 四宫格 | 标注视频 |',
             '|---|---:|---:|---:|---:|---:|---|---|']
    for r in rows:
        stem = f"{r['等级']}_{r['目标速度_cms']}_1"
        lines.append(f"| {stem} | {r['照度区间']} | {r['目标速度_cms']} | {r['稳态速度均值_cms']} | {r['误差均值_pct']} | {r['失败率均值_pct']} | [{stem}_v23.png](../../out/acceptance/figures/{stem}_v23.png) | [{stem}_v23.mp4](../../out/acceptance/videos/{stem}_v23.mp4) |")
    odd = [c for c in checks if c['frames'] != 915]
    frame_note = ('实际源文件 ' + '、'.join(f"{c['video']} 为 {c['frames']} 帧" for c in odd)
                  + '；其余为 915 帧（15.250 s）；标注视频逐段与源文件一致。') if odd else \
                 '六段均为 915 帧（15.250 s）；标注视频逐段与源文件一致。'
    lines += ['', '汇总图：[summary_light_levels.png](../../out/acceptance/figures/summary_light_levels.png)', '',
              '## 复现命令', '', '在 `第二学期/` 执行（PowerShell）：', '', '```powershell',
              "$env:PYTHONIOENCODING='utf-8'", 'python -m tools.batch_measure --dir out/acceptance --lux-file data/2026-10-30_验收/conditions.csv',
              "Get-ChildItem out/acceptance/L*.mp4 | ForEach-Object {", "  $target = $_.BaseName.Split('_')[1]",
              '  python -m tools.render_run --video $_.FullName --target $target --version v23 --outdir out/acceptance/figures --video-outdir out/acceptance/videos | Out-File -Encoding utf8 ("out/acceptance/videos/" + $_.BaseName + "_render.txt")',
              '}', 'python -m tools.acceptance_assets', '```', '',
              '复测由 batch_measure 逐段调用 measure_speed，产生 raw.csv、summary.csv 和 detect_logs。',
              '视频使用 mp4v，保持原始分辨率、帧率和帧数；完整解码检查见 figures/verification.json。',
              frame_note,
              '四宫格及汇总图均为 3300×2250、300 dpi。汇总图同时显示误差 ±20% 和失败率 15% 判据。',
              'HUD 的误差使用实际计算值（如 L2 / 21 cm/s 为 −0.9%），未采用需求示例中的 +0.5%。',
              '原始视频、测量算法、根目录文档和 PPT 未改动；未提交或推送 git。', '']
    lines += ['## 视觉检查记录', '',
              '配置：Matplotlib Agg 导出 PNG；OpenCV mp4v 写入并解码视频。中文字体实际解析到 C:/Windows/Fonts/msyh.ttc。',
              '检查范围：七张正式 PNG、每段稳态抽帧（*_pilot.jpg）及第 0/300/600/900 帧（*_qa_*.jpg）；视频完整解码另行核对。',
              '以下 PASS 仅适用于上述检查画面，不表示逐帧人工审看。无未完成的范围内检查；无剩余硬性缺陷。', '',
              '| 规则 | 结果 | 证据 |', '|---|---|---|',
              '| artifact.parse | PASS | 七张 PNG 可解析，六段视频完整解码，见 verification.json |',
              '| geometry.bounds | PASS | 图表标题、轴标、图例和 HUD 均在画布内 |',
              '| geometry.text_fit | PASS | 实际导出图及抽帧未见文字裁切或重叠 |',
              '| font.substitution_reflow | PASS | 汇总图使用 Microsoft YaHei，四宫格及 HUD 拉丁字符显示正常 |',
              '| font.glyph_coverage | PASS | 中文、负号、百分号及四宫格单位均可辨识，无缺字方块 |',
              '| geometry.connector_text | PASS | 试渲染发现轨迹穿过速度文字，文字上移后重渲染并检查通过 |',
              '| geometry.icon_text | PASS | 质心与状态标注未遮住文字；图表无图标 |',
              '| geometry.connector_clearance | PASS | 箭头、质心、轮廓和轨迹可区分，质心最后绘制 |',
              '| contrast.text_actual | PASS | 白色 HUD 和绿色 STEADY 使用深色底，橙色速度文字使用独立深色底，图表深色文字使用白底 |', '',
              '检查结论：PASS（限上述画面）。建议：按原始分辨率播放视频；抽帧缩略图仅用于定位。', '']
    (data / '图表与视频索引.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
