#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机命令行工具

    python -m camera.camera_capture list                    # 列出设备
    python -m camera.camera_capture info                    # 读能力参数
    python -m camera.camera_capture snap out/first.png      # 抓一帧
    python -m camera.camera_capture record out/v.mp4 -s 10  # 录一段
    python -m camera.camera_capture bench -s 60             # 体检（三项待确认）

无相机时可加 --mock 或 --mock-video <文件> 走假相机，把流程先跑通。
打通步骤与排错见 docs/相机打通步骤.md。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import config
from camera.backend import CameraError, Frame, MockBackend, MvsBackend, open_camera


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


# ---------------------------------------------------------------- 子命令


def cmd_list(args) -> int:
    if args.mock_video or args.backend == "mock":
        print("mock 模式没有真实设备可列。")
        return 0
    try:
        devices = MvsBackend.list_devices()
    except CameraError as exc:
        print(f"✗ {exc}")
        return 1
    if not devices:
        print("没有枚举到设备。检查：USB3.0 是否接主板原生口、MVS 客户端能否看见相机。")
        return 1
    print(f"找到 {len(devices)} 个设备：")
    for d in devices:
        print(f"  [{d['index']}] {d['型号']}  序列号 {d['序列号']}  "
              f"{d['接口']}  固件 {d['版本']}")
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
        if args.exposure:
            cam.set_exposure_us(args.exposure)
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

        cv2.imwrite(str(out), frame.image)
        h, w = frame.image.shape[:2]
        print(f"✓ 已保存 {out}（{w} × {h}）")
        print(f"  {_saturation_report(frame.image)}")
        print(f"  FrameID {frame.frame_id}｜硬件时间戳 {frame.device_ts}")
        if frame.device_ts is None and cam.name == "mvs":
            print("  ⚠ 这一帧没带硬件时间戳，P0.3.a 的时间基准需要退回 host 源")
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
        writer.write(frame)
        while time.perf_counter() - t0 < args.seconds:
            frame = cam.read()
            if frame is None:
                continue
            writer.write(frame)
            n += 1
        writer.release()
        dur = time.perf_counter() - t0
        print(f"✓ 已录制 {out}")
        print(f"  {n} 帧 / {dur:.2f} s → 实测 {n / dur:.2f} fps（写入标称 {args.fps} fps）")
    finally:
        cam.close()
    return 0


def cmd_bench(args) -> int:
    """体检：把三项待确认一次做实。"""
    cam = _open(args)
    try:
        if args.exposure:
            cam.set_exposure_us(args.exposure)
        if args.gain is not None:
            cam.set_gain_db(args.gain)

        n = 0
        t_first = t_last = None
        last_fid = None
        gaps = 0
        missing = 0
        host_deltas, dev_deltas = [], []
        prev_host = prev_dev = None

        t_start = time.perf_counter()
        print(f"开始体检，时长 {args.seconds} s（Ctrl-C 可提前结束）…")
        while time.perf_counter() - t_start < args.seconds:
            frame = cam.read()
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
    finally:
        cam.close()

    wall = (t_last - t_first) if (t_first and t_last) else 0.0
    if n < 2 or wall <= 0:
        print("✗ 样本不足，体检失败")
        return 1

    fps = (n - 1) / wall
    print("\n" + "=" * 62)
    print("相机体检报告（可直接回填 docs/相机与镜头参数汇总.md §6）")
    print("=" * 62)
    print(f"后端            {cam.name}")
    print(f"采样帧数        {n}")
    print(f"采样时长        {wall:.2f} s")

    # ---- ① 实测帧率 ----
    print(f"\n① 实测帧率      {fps:.2f} fps")
    print(f"   （规格书 201.4 fps 是极限值；实测值才是能写进报告的）")

    # ---- ② 硬件时间戳单位自证 ----
    print("\n② 硬件时间戳")
    if dev_deltas:
        unit = statistics.median(host_deltas) / statistics.median(dev_deltas)
        cand = min((1e-9, 1e-6, 1e-3), key=lambda u: abs(u - unit))
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
    sub.add_parser("info", help="读能力参数").set_defaults(func=cmd_info)

    sp = sub.add_parser("snap", help="抓一帧存图")
    sp.add_argument("output", help="输出图片路径")
    sp.add_argument("--warmup", type=int, default=8, help="先丢几帧让曝光稳定")
    sp.set_defaults(func=cmd_snap)

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