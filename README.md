# Course_space_robot

科研创新训练课「空间捕获机器人的设计」—— **视觉算法组 · 第二学期**

## 一句话目标

把上学期"手机拍 + 离线算"的视觉测速系统，升级成"**工业相机 + 固定机位 + 分级光照 + 实时曲线**"的地面二维测量平台，验证两项指标：

- **指标 1**：强光（L2）下稳态速度相对误差 **≤ 20%**
- **指标 2**：检测失败率 **≤ 15%**（L0–L2 判定；L3/L4 作为已知工作边界）

## 当前状态（2026-10-23）

| 项 | 状态 |
|---|---|
| 相机 | 海康 MV-CU013-A0UC + MVL-HF0828M-6MPE；MVS SDK 已打通，硬件时间戳 10 ns、FrameID 可读 |
| 机位 | 镜头到桌面 120 cm；车顶跟踪面 **WD 117.4 cm**；**px/cm 14.37**；测量区 **78 × 60 cm** |
| 光照 | 2 × 100 W 工作灯（无调光）；实测 **100 Hz 纹波** → **曝光锁 10 ms**（2~5 ms 全部频闪） |
| 检测 | MOG2 + 阴影抑制；15 s 录像车完整可见 **100% 检出**，轮廓中位 5.5 万 px² |
| 初步测速 | 29.5 cm/s（标称 31 cm/s，尚未做透视标定 H） |
| 待做 | 透视标定 H + 尺度验证、`main_v2.py`、L0–L4 分级实验、两项指标测量 |

## 目录

```
Course_space_robot/
├── CV/             第一学期成果（冻结保留，回归测试的对照物）
├── camera/         相机接入：FrameClock / MVS+Mock 后端 / 命令行工具
├── calibration/    标定：标定板体检（check_board.py）
├── lighting/       光照：频闪测试（flicker_test.py）
├── config.py       全局参数（几何、曝光、算法阈值）——物理结论的唯一来源
├── data/           数据归档（v1_baseline 两段视频；其余待采集）
├── docs/           全部文档，入口见 docs/README.md
├── tools/          一次性脚本（仓库迁移、汇报示意图、15 s 录制）
└── out/            运行产物（已 gitignore）
```

## 快速命令

```powershell
cd "C:\Users\binghuo\Desktop\科创课\Course_space_robot"

python config.py                                         # 参数自检
python -m camera.camera_capture list                     # 相机枚举
python -m camera.camera_capture --exposure 10000 snap out/frame.png
python -m calibration.check_board -e 10000               # 标定板体检（px/cm、WD、倾角）
python -m lighting.flicker_test -e 10000 -n 100          # 频闪测试
```

录小车视频：双击 `tools/record_15s.bat`（两盏灯、10 ms、15 s）。

## 文档

**入口：[docs/README.md](docs/README.md)**。最该先看的两份：

- [docs/光照系统实测与工作点.md](docs/光照系统实测与工作点.md) —— 实测数据与工作点
- [docs/第二学期总纲.md](docs/第二学期总纲.md) —— 一页看懂本学期
