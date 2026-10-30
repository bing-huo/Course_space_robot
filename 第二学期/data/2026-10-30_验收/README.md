# 2026-10-30 验收测量记录

## 光照等级（3 个）
| 等级 | 照度（测量区中心） | 备注 |
|---|---|---|
| L1 | **1360 lx** | 已布置，照度计实测 |
| L2 | 待测 | |
| L3 | 待测 | |

条件表：`conditions.csv`（测一档填一档）。

## 一键录制（推荐）

顺序：**一个光强 → 21 和 30 两个速度 → 换下一个光强**。

```powershell
cd "C:\Users\binghuo\Desktop\科创课\Course_space_robot\第二学期"
python -m tools.acceptance_session
```

运行后按提示操作：

1. 输入当前光强的照度（lx）→ 自动写进 `conditions.csv`；
2. 每段都有 5 秒倒计时，倒计时结束把小车推过去（15 秒录制）；
3. 一个光强的 21×3、30×3 录完，自动进入下一个光强；
4. 全部录完，问是否直接跑批量测量 → 选 Y 出 `summary.csv`。

可选参数：`--levels L1 L2 L3`、`--speeds 21 30`、`--reps 3`、`--dry-run`（只打印流程）。

## 测量流程（手动版）

1. 机位、曝光（10 ms / F2.8 / 6 dB）保持不动；
2. 每个光照等级下，小车以 21 / 30 cm/s 各跑 3 次，录 15 s；
3. 视频命名：`L1_21_1.mp4`、`L1_21_2.mp4`、`L1_30_1.mp4`……（等级_速度_次数）；
4. 放到同一目录（如 `out/acceptance/`），跑批量测量：

```powershell
python -m tools.batch_measure --dir out/acceptance --lux-file data/2026-10-30_验收/conditions.csv
```

输出：

- `summary.csv`：每个（等级, 速度）一行——稳态速度均值、误差均值、失败率均值、两项指标判定；
- `raw.csv`：每个视频一行；
- `detect_logs/`：逐帧检测日志（失败率溯源用）。

5. 录完把 `summary.csv` 和 `conditions.csv` 发我，我把结果写进验收文档。

## 判定口径
- 指标 1：稳态速度相对误差 **≤ 20%**；
- 指标 2：检测失败率 **≤ 15%**（失败率 = 统计窗内未检出帧 ÷ 统计窗总帧数）。
