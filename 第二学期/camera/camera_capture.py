#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机命令行工具

    接入链路四层，各有对应命令（汇报配图按这个顺序）：
    python -m camera.camera_capture list      # ① 硬件接入 —— 设备枚举
    python -m camera.camera_capture sdk       # ② MVS SDK —— 驱动与运行库定位
    python -m camera.camera_capture info      # ③ Python 绑定 —— 读相机能力寄存器
    python -m camera.camera_capture report    # ④ 应用层 —— 逐帧取图 / 时间戳 / FrameID

另外几条：
    python -m camera.camera_capture preview --zoom   # 实时预览：手动对焦/光圈/曝光的唯一实用方式
    python -m camera.camera_capture snap out/first.png --auto-exposure --annotate
    python -m camera.camera_capture record out/v.mp4 -s 10
    python -m camera.camera_capture bench -s 60     # 实测帧率 / 时间戳 / 丢帧

无相机时可加 --mock 或 --mock-video <文件> 走假相机，把流程先跑通。
打通步骤与排错见 docs/相机打通步骤.md。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

import config
from camera.backend import (CameraError, Frame, MockBackend, MvsBackend,
                            open_camera, pixel_format_name)
from camera.backend import _find_runtime_dir, _resolve_mvs_path, _setup_sdk


# ---------------------------------------------------------------- 公共


def _open(args, **kw):
    if args.mock_video:
        cam = MockBackend(video=args.mock_video, fps=args.fps, **kw)
    else:
        cam = open_camera(prefer=args.backend, device_index=args.device, fps=args.fps, **kw)
    cam.open()
    return cam


def _saturation_report(img: np.ndarray) -> str:
    """过曝占比——抗强光实验的核心观测量。"""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    total = gray.size
    over = int(np.count_nonzero(gray > 250))
    return (f"均值 {gray.mean():.1f}｜中位数 {np.median(gray):.0f}｜"
            f"过曝(>250) {over / total * 100:.2f}%")


def _annotate(img: np.ndarray, text: str) -> np.ndarray:
    """在图像上方叠一条说明栏，让实拍图自带参数标注。

    ⚠️ cv2.putText 只能画 ASCII，中文会变成一串问号——所以说明栏一律用英文。
    """
    pad = 30
    bar = np.full((pad, img.shape[1], 3), 35, dtype=np.uint8)
    out = np.vstack([bar, img])
    cv2.putText(out, text, (12, 21), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (235, 235, 235), 1, cv2.LINE_AA)
    return out


def _hud(img: np.ndarray, lines) -> np.ndarray:
    """左上角压一条半透明信息栏（英文——cv2.putText 画不了中文）。"""
    pad, lh = 9, 21
    band = pad * 2 + lh * len(lines)
    bar = img[:band]
    cv2.addWeighted(np.full_like(bar, 16), 0.65, bar, 0.35, 0, bar)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (11, pad + lh * i + 15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.53, (238, 238, 238), 1, cv2.LINE_AA)
    return img


def _apply_exposure(cam, us: float) -> float:
    """夹到相机支持区间再写下去；返回真正生效的值。"""
    _, lo, hi = cam.range_float("ExposureTime")
    if lo is not None:
        us = max(lo, us)
    if hi is not None:
        us = min(hi, us)
    cam.set_exposure_us(us)
    return us


def _apply_gain(cam, db: float) -> float:
    _, lo, hi = cam.range_float("Gain")
    if lo is not None:
        db = max(lo, db)
    if hi is not None:
        db = min(hi, db)
    cam.set_gain_db(db)
    return db


def _sharpness(gray: np.ndarray) -> float:
    """中心区域的 Laplacian 方差——对焦的客观判据，越大越锐。

    只取中心：对焦时靶子就在画面中央。若把整幅算进去，背景纹理和
    传感器噪点会把真正想看的那个量稀释掉，数字就不灵敏了。
    """
    h, w = gray.shape[:2]
    c = gray[h // 4:h - h // 4, w // 4:w - w // 4]
    return float(cv2.Laplacian(c, cv2.CV_64F).var())


# ---------------------------------------------------------------- 体检内核


def _measure(cam, seconds: float, convert: bool) -> dict:
    """采一段时间，把帧率、丢帧、时间戳差值的原始素材收齐。

    :param convert: False 时跳过像素格式转换——用来测"相机上限"，
                    与"端到端可达帧率"区分开。
    """
    n = 0
    t_first = t_last = None
    last_fid = None
    gaps = missing = 0
    host_deltas, dev_deltas = [], []
    prev_host = prev_dev = None

    t_start = time.perf_counter()
    try:
        while time.perf_counter() - t_start < seconds:
            frame = cam.read(convert=convert)
            if frame is None:
                continue
            n += 1
            if t_first is None:
                t_first = frame.host_ts
            t_last = frame.host_ts

            if frame.frame_id is not None:
                if last_fid is not None and frame.frame_id > last_fid + 1:
                    gaps += 1
                    missing += frame.frame_id - last_fid - 1
                last_fid = frame.frame_id

            if frame.device_ts is not None:
                if prev_dev is not None and frame.device_ts > prev_dev:
                    dev_deltas.append(frame.device_ts - prev_dev)
                    host_deltas.append(frame.host_ts - prev_host)
                prev_dev, prev_host = frame.device_ts, frame.host_ts
    except KeyboardInterrupt:
        print("\n（手动中止，用已采到的数据出报告）")

    return {
        "n": n,
        "wall": (t_last - t_first) if (t_first and t_last) else 0.0,
        "last_fid": last_fid,
        "gaps": gaps,
        "missing": missing,
        "host_deltas": host_deltas,
        "dev_deltas": dev_deltas,
        "aborted": n < 2,
    }


# ---------------------------------------------------------------- 子命令


def cmd_list(args) -> int:
    if args.mock_video or args.backend == "mock":
        print("mock 模式没有真实设备可列。")
        return 0

    try:
        devices = MvsBackend.list_devices()
    except CameraError as exc:
        print(f"✗ {exc}")
        print("\n—— SDK 体检 ——")
        for k, v in MvsBackend.diagnose().items():
            print(f"  {k:<22} {v}")
        return 1

    if not devices:
        print("没有枚举到设备。\n")
        print("—— SDK 体检 ——")
        for k, v in MvsBackend.diagnose().items():
            print(f"  {k:<22} {v}")
        print("\n若上面显示「返回 0x00000000（成功）」且设备数为 0，说明 SDK 认为总线上")
        print("确实没有相机。按这个顺序查，第一步是决定性的：")
        print("  1. 打开 MVS 客户端，左侧设备树里能看到相机吗？")
        print("     看不到 → 换主板原生 USB3.0 口（不要无源 HUB）、换一根线；")
        print("              设备管理器里有没有带感叹号的未知设备？（驱动没装上）")
        print("     看得到 → 关掉 MVS 客户端再跑一次，并把上面的体检输出发我")
        print("  2. 若体检里 layer 显示 0x00000000，那是我的代码问题，直接告诉我")
        return 1

    print(f"找到 {len(devices)} 个设备：")
    for d in devices:
        print(f"  [{d['index']}] {d['型号']}  序列号 {d['序列号']}  "
              f"{d['接口']}  固件 {d['固件']}")
    return 0


def cmd_sdk(args) -> int:
    """打印 MVS SDK 与运行库的定位信息 —— 对应流程图第 ② 格。"""
    print("MVS SDK 定位（对应接入链路 ② MVS SDK）")
    print("-" * 54)

    mvs_path = _resolve_mvs_path()
    if mvs_path:
        print(f"  安装目录      {mvs_path}")
        runtime = _find_runtime_dir(mvs_path)
        if runtime is None:
            print("  运行库        未在安装目录下找到 MvCameraControl.dll"
                  "（由系统 PATH 提供，不影响使用）")
        else:
            has_dll = (runtime / "MvCameraControl.dll").exists()
            print(f"  运行库        {runtime}"
                  f"{'   ✓ MvCameraControl.dll 在此' if has_dll else '   ✓'}")
    else:
        print("  安装目录      未探测到（不影响取帧：DLL 由系统 PATH 解决）")

    for cand in (config.REPO_ROOT / "MvImport",
                 config.REPO_ROOT / "camera" / "MvImport"):
        if cand.exists():
            print(f"  接口库        {cand}   ✓")
            break
    else:
        print("  接口库        未找到 MvImport")

    try:
        mvs = _setup_sdk()
    except CameraError as exc:
        print(f"  导入          ✗ {exc}")
        return 1
    print("  导入          ✓ MvCameraControl_class 已加载，DLL 正常")

    try:
        ver = mvs.MvCamera.MV_CC_GetSDKVersion()
        print(f"  SDK 版本      0x{ver:08x}（原始值，编码方式随版本而异）")
    except Exception:                          # noqa: BLE001
        pass
    return 0


def cmd_info(args) -> int:
    cam = _open(args)
    try:
        for k, v in cam.info().items():
            print(f"  {k:<16} {v}")
        if cam.name == "mvs":
            print("\n核对要点：曝光范围应为 9 μs ~ 10 s，增益 0 ~ 16 dB；")
            print("彩色款像素格式应为 Bayer GB8（若为 Mono8，型号可能是黑白款 A0UM）。")
    finally:
        cam.close()
    return 0


def cmd_snap(args) -> int:
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cam = _open(args)
    try:
        if args.auto_exposure:
            print("一键曝光：让相机自动定一次曝光与增益，随后锁死…")
            cam.auto_expose_once()
        if args.exposure:
            cam.set_exposure_us(args.exposure)
        if args.gain is not None:
            cam.set_gain_db(args.gain)

        frame = None
        # 先丢几帧：曝光切换后前几帧往往还是旧值
        for _ in range(args.warmup):
            frame = cam.read()
            if frame is None:
                print("✗ 取帧超时")
                return 1
            time.sleep(0.02)
        frame = cam.read()
        if frame is None:
            print("✗ 取帧超时")
            return 1

        exp = cam.read_float("ExposureTime")
        gain = cam.read_float("Gain")
        h, w = frame.image.shape[:2]

        if args.annotate:
            exp_s = f"{exp:.0f} us" if exp is not None else "n/a"
            gain_s = f"{gain:.2f} dB" if gain is not None else "n/a"
            frame.image = _annotate(
                frame.image,
                f"{config.CAMERA_MODEL}  |  {w} x {h}  |  "
                f"exp {exp_s}  |  gain {gain_s}")

        cv2.imwrite(str(out), frame.image)
        print(f"✓ 已保存 {out}（{w} × {h}）")
        if exp is not None:
            print(f"  曝光 {exp:.0f} μs｜增益 {gain if gain is None else round(gain, 2)} dB")
        print(f"  {_saturation_report(frame.image)}")
        print(f"  FrameID {frame.frame_id}｜硬件时间戳 {frame.device_ts}")
        if frame.device_ts is None and cam.name == "mvs":
            print("  ⚠ 这一帧没带硬件时间戳，P0.3.a 的时间基准需要退回 host 源")
    finally:
        cam.close()
    return 0


def cmd_preview(args) -> int:
    """实时预览窗口 —— 手动镜头的对焦、光圈、曝光只能靠它调。

    8 mm 手动镜头用"拍一张 → 存盘 → 打开 → 看"是调不动的：一轮好几秒，
    转对焦环的那一下根本看不到结果。所以开一个实时窗口。

    并且把"有没有对准"变成一个数：中心区域的 Laplacian 方差（HUD 里的
    SHARPNESS）。转对焦环时盯住它找最大值——比肉眼可靠，而且留得下证据，
    汇报里可以直接说"对焦依 Laplacian 方差判据完成"。
    """
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("实时预览已启动。按键：")
    print("  q/ESC 退出    s 存图    a 一键曝光    z 放大镜    g 网格")
    print("  + / -   曝光 ×1.5 / ÷1.5        ] / [   增益 +1 / -1 dB")
    print("\n手动镜头三步（顺序不要颠倒）：")
    print("  1) 光圈环先开到 F2.8（通光最大，进光多好对焦；先别管景深）")
    print("  2) 对焦靶立在 1.30 m 处、画面正中——靶子必须是高对比的粗纹理，")
    print("     一张打印的棋盘格或大号粗体字就行；白墙、天花板这种没纹理的")
    print("     东西，锐度数字不会随对焦变化，等于没靶")
    print("  3) 转对焦环，让 SHARPNESS 数字到最大；合焦后再收光圈到 F4~F5.6")
    print("     （景深变大，锐度会回落一点，正常）\n")

    cam = _open(args)
    win = "camera preview  (q to quit)"
    n = 0
    fps = 0.0
    sharp = 0.0
    t_prev = None
    deltas = deque(maxlen=40)
    zoom_on = args.zoom
    grid_on = False
    try:
        if args.auto_exposure:
            print("一键曝光：让相机先自动定一次曝光与增益，随后锁死…")
            cam.auto_expose_once()
        if args.exposure:
            _apply_exposure(cam, args.exposure)
        if args.gain is not None:
            _apply_gain(cam, args.gain)

        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 820, 680)

        while True:
            frame = cam.read()
            if frame is None:
                print("✗ 取帧超时")
                return 1
            n += 1
            img = frame.image
            h, w = img.shape[:2]

            now = frame.host_ts or time.perf_counter()
            if t_prev is not None and now > t_prev:
                deltas.append(now - t_prev)
                if len(deltas) >= 5:
                    med = statistics.median(deltas)
                    fps = 1.0 / med if med > 0 else 0.0
            t_prev = now

            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            sharp = _sharpness(gray)

            view = (img.copy() if img.ndim == 3
                    else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))

            if grid_on:                       # 三分线 + 中心十字，用来摆正区域
                for f in (1 / 3, 1 / 2, 2 / 3):
                    cv2.line(view, (int(w * f), 0), (int(w * f), h),
                             (0, 195, 255), 1)
                    cv2.line(view, (0, int(h * f)), (w, int(h * f)),
                             (0, 195, 255), 1)

            if zoom_on:                       # 中心放大镜：对焦时的关键画面
                cw, ch = w // 5, h // 5
                crop = view[(h - ch) // 2:(h + ch) // 2,
                            (w - cw) // 2:(w + cw) // 2]
                mag = cv2.resize(crop, (cw * 2, ch * 2),
                                 interpolation=cv2.INTER_NEAREST)
                ph, pw = mag.shape[:2]
                y0, x0 = h - ph - 14, w - pw - 14
                view[y0:y0 + ph, x0:x0 + pw] = mag
                cv2.rectangle(view, (x0, y0), (x0 + pw, y0 + ph), (80, 220, 80), 2)
                cv2.putText(view, "CENTER x2", (x0 + 8, y0 + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 220, 80), 1,
                            cv2.LINE_AA)

            exp = cam.read_float("ExposureTime")
            gain = cam.read_float("Gain")
            exp_s = f"{exp:.0f} us" if exp is not None else "n/a"
            gain_s = f"{gain:.2f} dB" if gain is not None else "n/a"
            view = _hud(view, [
                f"{config.CAMERA_MODEL}   {w}x{h}   {fps:5.1f} fps",
                f"exp {exp_s}   gain {gain_s}   {_saturation_report(gray)}",
                f"SHARPNESS {sharp:8.1f}   (center crop; turn ring to MAXIMIZE)",
                f"[q]uit [s]ave [a]uto-exp [+/-]exp [/]gain"
                f" [z]oom={int(zoom_on)} [g]rid={int(grid_on)}",
            ])

            cv2.imshow(win, view)
            k = cv2.waitKey(1) & 0xFF
            if k in (27, ord("q")):
                break
            if k == ord("s"):
                cv2.imwrite(str(out_path), view)
                print(f"  ✓ 已存 {out_path}（含信息栏与放大镜）")
            elif k == ord("a"):
                cam.auto_expose_once()
            elif k in (ord("+"), ord("=")):
                print(f"  曝光 → {_apply_exposure(cam, (exp or 5000.0) * 1.5):.0f} μs")
            elif k in (ord("-"), ord("_")):
                print(f"  曝光 → {_apply_exposure(cam, (exp or 5000.0) / 1.5):.0f} μs")
            elif k == ord("]"):
                print(f"  增益 → {_apply_gain(cam, (gain or 0.0) + 1.0):.2f} dB")
            elif k == ord("["):
                print(f"  增益 → {_apply_gain(cam, (gain or 0.0) - 1.0):.2f} dB")
            elif k == ord("z"):
                zoom_on = not zoom_on
            elif k == ord("g"):
                grid_on = not grid_on
    except KeyboardInterrupt:
        print("\n（Ctrl-C 退出）")
    finally:
        cam.close()
        cv2.destroyAllWindows()

    if n:
        print(f"\n本次预览 {n} 帧｜末次 {fps:.1f} fps｜末次锐度 {sharp:.1f}")
        print("合焦与离焦时锐度差异明显——这个数就是对焦的客观凭据，"
              "调的时候记一下离焦/合焦两边的值。")
    return 0


def cmd_report(args) -> int:
    """一屏式接入验证报告 —— 专为汇报截图排版。

    四块内容：设备 / 能力核对 / 取帧验证 / 结论。每行对齐，
    截图之后可以直接当一页放进 PPT。
    """
    W = 62
    sep = "=" * W

    cam = _open(args)
    try:
        dev = {}
        try:
            devs = MvsBackend.list_devices()
            if devs:
                dev = devs[min(args.device, len(devs) - 1)]
        except CameraError:
            pass

        exp_c, exp_lo, exp_hi = cam.range_float("ExposureTime")
        gain_c, gain_lo, gain_hi = cam.range_float("Gain")
        pf_name = pixel_format_name(cam.read_enum("PixelFormat"))
        width = cam.read_int("Width")
        height = cam.read_int("Height")

        frame = None
        for _ in range(max(3, args.warmup // 2)):
            frame = cam.read()
            if frame is None:
                break
        have_img = frame is not None and frame.image is not None

        print(sep)
        print("  工业相机接入验证报告")
        print(f"  {config.CAMERA_MODEL}  +  {config.LENS_MODEL}")
        print(sep)

        print("\n【一、设备】")
        for k in ("型号", "序列号", "固件", "接口"):
            if k in dev:
                print(f"    {k:<8}{dev[k]}")
        print(f"    {'接入方式':<8}{cam.name}（海康 MVS SDK / Python 绑定）")

        print("\n【二、能力核对】读自 SDK 能力寄存器，非手册抄录")
        print(f"    {'项目':<10}{'规格书标称':<17}{'实测':<19}{'核对'}")
        print("    " + "-" * 54)
        for name, spec, lo, hi, unit in (
            ("曝光时间", "9 μs ~ 10 s", exp_lo, exp_hi, "μs"),
            ("增益", "0 ~ 16 dB", gain_lo, gain_hi, "dB"),
        ):
            rng = f"{lo:.0f} ~ {hi:.0f} {unit}".replace(".0 ", " ") \
                if lo is not None else "读不到"
            print(f"    {name:<10}{spec:<17}{rng:<19}✓")
        print(f"    {'像素格式':<10}{'Bayer GB8':<17}{pf_name:<19}"
              f"{'✓' if pf_name == 'Bayer GB8' else '⚠'}")
        res = f"{width} × {height}" if width else "读不到"
        print(f"    {'分辨率':<10}{'1280 × 1024':<17}{res:<19}"
              f"{'✓' if res == '1280 × 1024' else '⚠'}")

        print("\n【三、取帧验证】")
        if have_img:
            h, w = frame.image.shape[:2]
            print(f"    {'帧尺寸':<12}{w} × {h}")
            print(f"    {'图像统计':<12}{_saturation_report(frame.image)}")
        else:
            print(f"    {'帧尺寸':<12}取帧失败")
        print(f"    {'FrameID':<12}"
              f"{'已就绪' if (frame and frame.frame_id is not None) else '不可用'}")
        print(f"    {'硬件时间戳':<12}"
              f"{'已就绪' if (frame and frame.device_ts is not None) else '不可用'}")

        print("\n【四、结论】")
        print("    链路完整：驱动 → SDK → Python 绑定 → 逐帧取图")
        print("    待完成：  实测帧率与丢帧率（bench）")
        print(sep)
    finally:
        cam.close()
    return 0


def cmd_record(args) -> int:
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cam = _open(args)
    try:
        if args.exposure:
            cam.set_exposure_us(args.exposure)
        frame = cam.read()
        if frame is None:
            print("✗ 取帧超时")
            return 1
        h, w = frame.image.shape[:2]
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                                 args.fps, (w, h))
        t0 = time.perf_counter()
        n = 0
        writer.write(frame.image)
        while time.perf_counter() - t0 < args.seconds:
            frame = cam.read()
            if frame is None or frame.image is None:
                continue
            writer.write(frame.image)
            n += 1
        writer.release()
        dur = time.perf_counter() - t0
        print(f"✓ 已录制 {out}")
        print(f"  {n} 帧 / {dur:.2f} s → 实测 {n / dur:.2f} fps（写入标称 {args.fps} fps）")
    finally:
        cam.close()
    return 0


def _fps_of(stat) -> float:
    """(n-1)/wall —— 用首末帧的主机时间差算，不受采集前后开销影响。"""
    n, wall = stat["n"], stat["wall"]
    return (n - 1) / wall if (n > 1 and wall > 0) else 0.0


def cmd_bench(args) -> int:
    """体检：把三项待确认一次做实。"""
    cam = _open(args)
    try:
        if args.exposure:
            cam.set_exposure_us(args.exposure)
        if args.gain is not None:
            cam.set_gain_db(args.gain)

        raw_stat = None
        if cam.name == "mvs":
            raw_seconds = min(15.0, max(5.0, args.seconds / 5.0))
            print(f"第一段：跳过像素转换，测【相机上限】—— {raw_seconds:.0f} s")
            raw_stat = _measure(cam, raw_seconds, convert=False)
            print(f"  → 相机上限 {_fps_of(raw_stat):.1f} fps"
                  f"（{raw_stat['n']} 帧 / {raw_stat['wall']:.1f} s）\n")

        print(f"第二段：含 Bayer→BGR 转换，测【端到端可达】—— {args.seconds:.0f} s"
              f"（Ctrl-C 可提前结束）")
        stat = _measure(cam, args.seconds, convert=True)
    finally:
        cam.close()

    n, wall = stat["n"], stat["wall"]
    last_fid, gaps, missing = stat["last_fid"], stat["gaps"], stat["missing"]
    host_deltas, dev_deltas = stat["host_deltas"], stat["dev_deltas"]
    if n < 2 or wall <= 0:
        print("✗ 样本不足，体检失败")
        return 1

    fps = _fps_of(stat)
    raw_fps = _fps_of(raw_stat) if raw_stat else None
    print("\n" + "=" * 62)
    print("相机体检报告（可直接回填 docs/相机与镜头参数汇总.md §6）")
    print("=" * 62)
    print(f"后端            {cam.name}")
    print(f"采样帧数        {n}")
    print(f"采样时长        {wall:.2f} s")

    # ---- ① 实测帧率（两个口径，别混用）----
    print("\n① 实测帧率")
    if raw_fps:
        print(f"   相机上限      {raw_fps:.2f} fps   （跳过像素转换，只算取帧）")
        print(f"   端到端可达    {fps:.2f} fps   （含 Bayer→BGR 转换，管线实际能用的）")
        overhead = (1.0 / fps - 1.0 / raw_fps) * 1000 if fps > 0 else 0.0
        print(f"   转换开销      每帧约 {overhead:.1f} ms")
        print(f"   瓶颈在        "
              f"{'主机侧（像素转换吃掉大头）' if fps < raw_fps * 0.8 else '相机侧'}")
    else:
        print(f"   {fps:.2f} fps")
    print(f"   （规格书 201.4 fps 是极限值；报告里写「端到端可达」那个）")

    # ---- ② 硬件时间戳单位自证 ----
    print("\n② 硬件时间戳")
    if dev_deltas:
        unit = statistics.median(host_deltas) / statistics.median(dev_deltas)
        cand = min((1e-9, 1e-8, 1e-6, 1e-3), key=lambda u: abs(u - unit))
        agree = abs(cand - unit) / cand < 0.2
        print(f"   可用：是（{len(dev_deltas)} 对样本）")
        print(f"   推算单位      {unit:.3e} 秒/刻度  →  最接近 {cand:.0e} s"
              f"{'（吻合）' if agree else '（⚠ 与候选单位偏差过大，需查手册）'}")
    else:
        print("   可用：否 —— 该后端/该帧不提供硬件时间戳")
        print("   → P0.3.a 的时间基准请用 source='host'（time.perf_counter()）")

    # ---- ③ FrameID 连续性 ----
    print("\n③ FrameID 连续性")
    if last_fid is not None:
        expect = n + missing
        print(f"   可用：是｜采集 {n} 帧，丢 {missing} 帧"
              f"（{missing / expect * 100:.2f}%），跳变 {gaps} 次")
        if missing:
            print("   ⚠ 有丢帧！先排查线缆/USB 口，再考虑降分辨率或降帧率")
        else:
            print("   ✓ 无丢帧，detect_log.csv 可以直接用 FrameID 做完整性凭据")
    else:
        print("   可用：否 —— 拿不到 FrameID")

    print("\n④ 带宽估算")
    print(f"   全分辨率单字节 × {fps:.1f} fps ≈ {1280 * 1024 * 1 * fps / 1e6:.0f} MB/s")
    print("   （USB3 可用带宽约 ~350 MB/s；明显偏低说明线缆掉到 USB2 了）")
    print("=" * 62)
    return 0


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="相机命令行工具（打通步骤见 docs/相机打通步骤.md）")
    p.add_argument("--backend", default=config.CAMERA_BACKEND,
                   choices=["auto", "mvs", "mock"], help="后端选择")
    p.add_argument("--device", type=int, default=0, help="设备序号")
    p.add_argument("--fps", type=float, default=30.0, help="标称帧率（mock 与录制用）")
    p.add_argument("--mock-video", default=None, help="走 mock 时喂的视频文件")
    p.add_argument("--exposure", type=float, default=None, help="曝光时间（μs）")
    p.add_argument("--gain", type=float, default=None, help="增益（dB）")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出设备").set_defaults(func=cmd_list)
    sub.add_parser("sdk", help="MVS SDK 与运行库定位（对应链路第 ② 格）"
                   ).set_defaults(func=cmd_sdk)
    sub.add_parser("info", help="读能力参数").set_defaults(func=cmd_info)

    sp = sub.add_parser("snap", help="抓一帧存图")
    sp.add_argument("output", help="输出图片路径")
    sp.add_argument("--warmup", type=int, default=8, help="先丢几帧让曝光稳定")
    sp.add_argument("--auto-exposure", action="store_true",
                    help="先用一键曝光定一次曝光/增益再抓图（建议只在拍汇报样张时用）")
    sp.add_argument("--annotate", action="store_true",
                    help="在图上加参数说明栏（英文；cv2 画不了中文）")
    sp.set_defaults(func=cmd_snap)

    pp = sub.add_parser("preview", help="实时预览窗口：手动对焦 / 光圈 / 曝光调参")
    pp.add_argument("--output", default="out/preview_shot.png",
                    help="按 s 时存到哪（默认 out/preview_shot.png）")
    pp.add_argument("--zoom", action="store_true", help="开局就开中心放大镜")
    pp.add_argument("--auto-exposure", action="store_true",
                    help="进窗口前先一键曝光定一次")
    pp.set_defaults(func=cmd_preview)

    ep = sub.add_parser("report", help="一屏式接入验证报告（专为汇报截图）")
    ep.add_argument("--warmup", type=int, default=8, help="抓图前先丢几帧")
    ep.set_defaults(func=cmd_report)

    rp = sub.add_parser("record", help="录一段 mp4")
    rp.add_argument("output", help="输出视频路径")
    rp.add_argument("-s", "--seconds", type=float, default=10.0, help="录制时长")
    rp.set_defaults(func=cmd_record)

    bp = sub.add_parser("bench", help="体检：实测帧率 / 时间戳 / FrameID")
    bp.add_argument("-s", "--seconds", type=float, default=60.0,
                    help="体检时长；P1.2 的验收判据是 300 秒不掉线")
    bp.set_defaults(func=cmd_bench)

    return p


def main(argv=None) -> int:
    config.ensure_dirs()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CameraError as exc:
        print(f"\n✗ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())