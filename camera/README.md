# camera/ —— 相机接入

第二学期新增。**打通步骤、排错、判据全部在 [`docs/相机打通步骤.md`](../docs/相机打通步骤.md)**，先看那份。

## 文件

| 文件 | 作用 | 依赖 |
|---|---|---|
| `frame_clock.py` | **FrameClock** 统一时间基准（P0.3.a）。三种时间源：`device`（相机硬件时间戳）/ `host`（perf_counter）/ `file`（v1 回归）。保证单调不减，丢帧不会让时间停住 | 纯标准库，不依赖 OpenCV |
| `backend.py` | 相机后端抽象。`MvsBackend` 走海康 MVS SDK；`MockBackend` 喂视频或生成合成移动目标——**没有相机也能开发算法** | opencv, numpy |
| `camera_capture.py` | 命令行工具：`list` / `info` / `snap` / `record` / `bench` | 上面两个 |

## 快速自检

> ⚠️ **所有命令都在仓库根目录下执行**（代码用 `import config` 读全局参数，从别处运行会 `ModuleNotFoundError`）：
>
> ```powershell
> cd "C:\Users\binghuo\Desktop\科创课\Course_space_robot"
> ```

```bash
# 不接相机也能跑（FrameClock 自带四个场景的自测）
python -m camera.frame_clock

# 假相机跑通全流程
python -m camera.camera_capture --backend mock snap out/mock_frame.png
python -m camera.camera_capture --backend mock --mock-video data/v1_baseline/test_video_21.mp4 info

# 真机
python -m camera.camera_capture list
python -m camera.camera_capture info
python -m camera.camera_capture bench -s 300      # P1.2 判据：5 分钟不掉线
```

## 为什么要这么设计

**时间基准单独成模块**，是因为第一学期的 `curr_t = len(h_t) / real_fps` 在丢帧时
会静默出错，而速度正是本学期的考核指标。三种来源统一到一个类里，将来换相机、
换驱动都不用动上层代码。

**后端抽象**，是因为 MVS 的 Python 绑定在不同 SDK 版本之间类名和字段名会变，
而且不少机器上装不上。所有版本差异都关在 `backend.py` 里；
MVS 挂掉时 `open_camera()` 会自动退回 Mock 并打印原因，进度不会停。

**bench 子命令一次回答三个问题**（`docs/相机与镜头参数汇总.md` §6 的待确认项）：
实测帧率是多少、硬件时间戳能不能用且单位是什么、FrameID 连不连续（丢没丢帧）。

## 已定的参数

`config.py` 里的几何参数（区域 90 × 70 cm、视野 100 × 80 cm、
工作距离 ≈ 1.30 m、px/cm ≈ 12.8）都是**理论值**，其中 `PX_PER_CM`、
`CONTOUR_AREA_MIN`、`CY_OFFSET_K` 三项必须现场实测后覆盖（P1.9 / P2.2 / P1.8）。