# -*- coding: utf-8 -*-
"""
相机后端抽象（MVS 真机 + Mock 假相机）

为什么要抽象：MVS 的 Python 绑定在不同 SDK 版本之间类名、结构体字段名会变，
而且不少同学的机器上装不上。把所有版本差异关在这一个文件里，上层
（camera_capture.py / 将来的 main_v2.py）只认统一的 `Frame` 接口。

    MockBackend   喂视频文件，或生成一个会动的合成目标
                  → 没有相机也能开发算法，也是 MVS 绑定失败时的保底路径

    MvsBackend    海康 MVS SDK（MvCameraControl）

统一接口：
    cam = open_camera()          # 自动挑后端
    cam.open()
    for frame in cam.frames():   # frame.image / frame.frame_id / frame.device_ts
        ...
    cam.close()
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import cv2
import numpy as np

import config

# ================================================================
# 统一帧结构
# ================================================================


@dataclass
class Frame:
    """一帧图像及其时间信息。"""
    image: np.ndarray                 # BGR（彩色）或单通道灰度
    index: int                        # 后端内部的连续计数
    frame_id: Optional[int] = None    # 相机 FrameID，可查丢帧
    device_ts: Optional[int] = None   # 相机硬件时间戳（原始值，未换算）
    host_ts: float = 0.0              # 主机读到的 perf_counter()

    @property
    def shape(self):
        return self.image.shape


class CameraError(RuntimeError):
    """相机相关的可预期错误，带上排错提示。"""


def _get(obj, *names, default=None):
    """按候选名字取属性——MVS 各版本字段名不一致，用它兜底。"""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


# ================================================================
# Mock 后端
# ================================================================


class MockBackend:
    """假相机：喂视频文件，或生成合成画面。

    合成模式会画一个沿水平方向匀速移动的方块，速度按 config 里的
    区域尺寸和 px/cm 换算——**没有场地也能先把整条流程跑通**。
    """

    name = "mock"

    def __init__(self, video: Optional[str] = None, fps: float = 30.0,
                 size=(1280, 1024), speed_cms: float = 21.0,
                 loop: bool = True) -> None:
        self.video_path = video
        self.fps = fps
        self.size = size                  # (w, h)
        self.speed_cms = speed_cms
        self.loop = loop

        self._cap: Optional[cv2.VideoCapture] = None
        self._opened = False
        self._i = 0
        self._t0 = 0.0
        self._x = 0.0

    def open(self) -> "MockBackend":
        if self.video_path:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                raise CameraError(f"打不开视频文件：{self.video_path}")
            self._cap = cap
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            if w > 0 and h > 0:
                self.size = (w, h)
            if fps and fps > 0:
                self.fps = fps
        self._t0 = time.perf_counter()
        self._opened = True
        return self

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._opened = False

    def _next_image(self) -> Optional[np.ndarray]:
        if self._cap is not None:
            ok, img = self._cap.read()
            if not ok:
                if not self.loop:
                    return None
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = self._cap.read()
                if not ok:
                    return None
            return img

        # ---- 合成模式 ----
        w, h = self.size
        img = np.full((h, w), 60, dtype=np.uint8)          # 暗背景
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        # 区域边界（config 里的 FOV），方便肉眼核对视场
        cv2.rectangle(img, (20, 20), (w - 20, h - 20), (90, 90, 90), 2)

        px_per_cm = config.PX_PER_CM
        step_cm = self.speed_cms / self.fps                # 每帧走多少厘米
        self._x += step_cm * px_per_cm
        if self._x > w - 80:
            self._x = 40.0

        cv2.rectangle(img, (int(self._x), h // 2 - 40),
                      (int(self._x) + 80, h // 2 + 40), (255, 255, 255), -1)
        return img

    def read(self) -> Optional[Frame]:
        img = self._next_image()
        if img is None:
            return None
        f = Frame(image=img, index=self._i,
                  frame_id=self._i, device_ts=None,
                  host_ts=time.perf_counter())
        self._i += 1
        return f

    def frames(self) -> Iterator[Frame]:
        while True:
            f = self.read()
            if f is None:
                return
            yield f
            # 合成模式按标称帧率节流，视频模式不节流
            if self._cap is None:
                target = self._t0 + self._i / self.fps
                dt = target - time.perf_counter()
                if dt > 0:
                    time.sleep(dt)

    def info(self) -> Dict[str, object]:
        w, h = self.size
        return {
            "后端": "mock",
            "来源": self.video_path or "合成移动目标",
            "分辨率": f"{w} × {h}",
            "标称帧率": f"{self.fps:.2f} fps",
            "像素格式": "BGR8",
            "硬件时间戳": "无（mock 不提供）",
        }

    def set_exposure_us(self, us: float) -> None:
        print(f"  [mock] 忽略设置曝光 {us} μs")

    def set_gain_db(self, db: float) -> None:
        print(f"  [mock] 忽略设置增益 {db} dB")


# ================================================================
# MVS 后端
# ================================================================

_MVS = None            # 缓存已加载的 MvCameraControl_class 模块
_MVS_IMPORT_ERROR: Optional[str] = None


def _resolve_mvs_path() -> Optional[Path]:
    """定位 MVS 安装目录。"""
    env = os.environ.get("MVS_PATH")
    if env and Path(env).exists():
        return Path(env)
    for cand in config.MVS_PATH_CANDIDATES:
        p = Path(cand)
        if p.exists():
            return p
    return None


def _setup_sdk():
    """加载 MvCameraControl_class。

    这一步是整条链路上最容易出问题的地方（DLL 找不到），
    所以把能自动做的都做了，做不了的给出可执行的提示。
    """
    global _MVS, _MVS_IMPORT_ERROR
    if _MVS is not None:
        return _MVS
    if _MVS_IMPORT_ERROR:
        raise CameraError(_MVS_IMPORT_ERROR)

    mvs_path = _resolve_mvs_path()
    if mvs_path is not None:
        os.environ.setdefault("MVCAM_SDK_PATH", str(mvs_path))
        runtime = mvs_path / "Runtime" / "Win64_x64"
        os.environ.setdefault("MVCAM_COMMON_RUNENV", str(runtime))
        # Python 3.8+ 必须显式登记 DLL 搜索目录，否则 MvCameraControl.dll 找不到
        if runtime.exists() and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(runtime))
            except OSError:
                pass

    # MvImport 目录：优先仓库根，其次 camera/ 下
    for cand in (config.REPO_ROOT / "MvImport",
                 config.REPO_ROOT / "camera" / "MvImport"):
        if cand.exists():
            sys.path.insert(0, str(cand))
            break

    try:
        import MvCameraControl_class as mvs      # type: ignore
    except Exception as exc:                     # noqa: BLE001
        _MVS_IMPORT_ERROR = (
            "无法导入 MvCameraControl_class。逐条排查：\n"
            "  1) MVS 客户端装了吗？装的是 64 位吗？（python 也要 64 位）\n"
            "  2) MvImport 文件夹在仓库根目录下吗？（从 MVS 安装目录的\n"
            "     Development\\Samples\\Python\\ 复制过来）\n"
            f"  3) MVS 装在非默认路径？设环境变量 MVS_PATH 指向它\n"
            "     （当前探测候选：" +
            "、".join(config.MVS_PATH_CANDIDATES) + "）\n"
            f"  4) 原始报错：{exc!r}\n"
            "详见 docs/相机打通步骤.md 步骤 2 与排错速查表。"
        )
        raise CameraError(_MVS_IMPORT_ERROR) from exc

    _MVS = mvs
    return mvs


class MvsBackend:
    """海康 MVS SDK 后端（USB3 Vision / GenICam）。"""

    name = "mvs"

    def __init__(self, device_index: int = 0) -> None:
        self.device_index = device_index
        self._mvs = None
        self._cam = None
        self._payload = 0
        self._conv_param = None
        self._buf: Optional[np.ndarray] = None
        self._i = 0
        self._dev_info: Dict[str, object] = {}

    # ------------------------------------------------------------ 设备枚举

    @staticmethod
    def list_devices() -> List[Dict[str, object]]:
        mvs = _setup_sdk()
        dev_list = mvs.MV_CC_DEVICE_INFO_LIST()
        layer = _get(mvs, "MV_USB_DEVICE", default=0) | _get(mvs, "MV_GIGE_DEVICE", default=0)
        ret = mvs.MvCamera.MV_CC_EnumDevices(layer, dev_list)
        if ret != 0:
            raise CameraError(f"枚举设备失败，错误码 0x{ret:08x}")

        out: List[Dict[str, object]] = []
        n = _get(dev_list, "nDeviceNum", default=0)
        for i in range(n):
            info = mvs.MV_CC_DEVICE_INFO()
            # 各版本里这块的取法略有差异，统一用 ctypes cast
            from ctypes import POINTER, cast
            info = cast(dev_list.pDeviceInfo[i], POINTER(mvs.MV_CC_DEVICE_INFO)).contents
            special = _get(info, "SpecialInfo")
            usb = _get(special, "stUsb3VInfo") if special is not None else None
            gige = _get(special, "stGigEInfo") if special is not None else None
            node = usb if usb is not None else gige

            def _chars(field_candidates, _node=node):
                arr = _get(_node, *field_candidates)
                if arr is None:
                    return ""
                try:
                    return bytes(bytearray(arr)).split(b"\x00")[0].decode(
                        "utf-8", errors="ignore")
                except Exception:                # noqa: BLE001
                    return str(arr)

            out.append({
                "index": i,
                "型号": _chars(["chModelName"]),
                "序列号": _chars(["chSerialNumber"]),
                "版本": _chars(["chDeviceVersion"]),
                "接口": "USB3" if usb is not None else "GigE",
            })
        return out

    # ------------------------------------------------------------ 生命周期

    def open(self) -> "MvsBackend":
        mvs = _setup_sdk()
        self._mvs = mvs

        dev_list = mvs.MV_CC_DEVICE_INFO_LIST()
        layer = _get(mvs, "MV_USB_DEVICE", default=0) | _get(mvs, "MV_GIGE_DEVICE", default=0)
        ret = mvs.MvCamera.MV_CC_EnumDevices(layer, dev_list)
        if ret != 0:
            raise CameraError(f"枚举设备失败，错误码 0x{ret:08x}")

        n = _get(dev_list, "nDeviceNum", default=0)
        if n == 0:
            raise CameraError(
                "没找到相机。排查：USB3.0 线是否接在主板原生口（不要用无源 HUB）、"
                "MVS 客户端是否能看见设备、相机是否被 MVS 客户端占用（先关掉客户端）。")
        if self.device_index >= n:
            raise CameraError(f"只有 {n} 个设备，取不到第 {self.device_index} 个")

        from ctypes import POINTER, cast
        info = cast(dev_list.pDeviceInfo[self.device_index],
                    POINTER(mvs.MV_CC_DEVICE_INFO)).contents

        self._cam = mvs.MvCamera()
        # 新版 SDK 需要先初始化 SDK 资源；旧版没有这个函数
        if hasattr(mvs.MvCamera, "MV_CC_Initialize"):
            try:
                mvs.MvCamera.MV_CC_Initialize()
            except Exception:                     # noqa: BLE001
                pass

        ret = self._cam.MV_CC_CreateHandle(info)
        if ret != 0:
            raise CameraError(f"CreateHandle 失败，错误码 0x{ret:08x}")

        access = _get(mvs, "MV_ACCESS_Exclusive", default=1)
        ret = self._cam.MV_CC_OpenDevice(access, 0)
        if ret != 0:
            self._cam.MV_CC_DestroyHandle()
            self._cam = None
            raise CameraError(
                f"打开设备失败，错误码 0x{ret:08x}。常见原因：相机被 MVS 客户端占用，"
                "请先关闭 MVS 客户端再试。")

        # 连续采集模式：关掉触发
        trig_off = _get(mvs, "MV_TRIGGER_MODE_OFF", default=0)
        self._cam.MV_CC_SetEnumValue("TriggerMode", trig_off)

        # 关掉所有"自动"，这是实验可复现的前提（详见 config.CAMERA_LOCKED）
        self._apply_locked_settings()

        self._payload = self._get_payload_size()
        self._cam.MV_CC_StartGrabbing()
        return self

    def _apply_locked_settings(self) -> None:
        """把自动项全部关掉。失败不致命，但会打印出来。"""
        for key, val in config.CAMERA_LOCKED.items():
            try:
                if isinstance(val, str):
                    self._cam.MV_CC_SetEnumValueByString(key, val)
                else:
                    self._cam.MV_CC_SetIntValue(key, int(val))
            except Exception as exc:              # noqa: BLE001
                print(f"  ⚠ 设置 {key}={val} 失败：{exc!r}（请手动确认）")

    def _get_payload_size(self) -> int:
        mvs = self._mvs
        if hasattr(self._cam, "MV_CC_GetIntValueEx"):
            st = _get(mvs, "MVCC_INTVALUE_EX")()
        else:
            st = _get(mvs, "MVCC_INTVALUE")()
        try:
            self._cam.MV_CC_GetIntValue("PayloadSize", st)
            return int(_get(st, "nCurValue", default=0))
        except Exception:                          # noqa: BLE001
            return 1280 * 1024 * 3

    def close(self) -> None:
        if self._cam is None:
            return
        try:
            self._cam.MV_CC_StopGrabbing()
        except Exception:                          # noqa: BLE001
            pass
        try:
            self._cam.MV_CC_CloseDevice()
        except Exception:                          # noqa: BLE001
            pass
        try:
            self._cam.MV_CC_DestroyHandle()
        except Exception:                          # noqa: BLE001
            pass
        self._cam = None

    # ------------------------------------------------------------ 取帧

    def _convert_param(self):
        """像素格式转换参数结构体；不同 SDK 版本类名不同，做一次兼容。"""
        if self._conv_param is not None:
            return self._conv_param
        mvs = self._mvs
        cls = _get(mvs, "MV_CC_PIXEL_CONVERT_PARAM_EX") or \
            _get(mvs, "MV_CC_PIXEL_CONVERT_PARAM")
        if cls is None:
            raise CameraError(
                "SDK 里找不到像素格式转换参数结构体。请在 backend.py 的 "
                "_convert_param() 里按你的 SDK 版本调整类名。")
        self._conv_param = cls()
        return self._conv_param

    def read(self) -> Optional[Frame]:
        from ctypes import byref, cast, memmove, POINTER, c_ubyte

        mvs = self._mvs
        st_out = _get(mvs, "MV_FRAME_OUT")()
        ret = self._cam.MV_CC_GetImageBuffer(st_out, config.CAPTURE_TIMEOUT_MS)
        if ret != 0:
            return None

        info = _get(st_out, "stFrameInfo")
        w = int(_get(info, "nWidth", default=0))
        h = int(_get(info, "nHeight", default=0))
        frame_len = int(_get(info, "nFrameLen", default=0))
        frame_num = _get(info, "nFrameNum")
        ts_hi = _get(info, "nDevTimeStampHigh", default=0) or 0
        ts_lo = _get(info, "nDevTimeStampLow", default=0) or 0

        try:
            src_buf = (c_ubyte * frame_len)()
            memmove(byref(src_buf), st_out.pBufAddr, frame_len)

            conv = self._convert_param()
            dst_size = w * h * 3
            dst_buf = (c_ubyte * dst_size)()
            conv.nWidth = w
            conv.nHeight = h
            conv.pSrcData = cast(src_buf, POINTER(c_ubyte))
            conv.nSrcDataLen = frame_len
            conv.enSrcPixelType = _get(info, "enPixelType")
            conv.enDstPixelType = _get(mvs, "PixelType_Gvsp_BGR8_Packed")
            conv.pDstBuffer = cast(dst_buf, POINTER(c_ubyte))
            conv.nDstBufferSize = dst_size

            ret = self._cam.MV_CC_ConvertPixelType(conv)
            if ret != 0:
                raise CameraError(
                    f"像素格式转换失败，错误码 0x{ret:08x}。"
                    "若反复失败，先在 info 里确认像素格式（彩色款应为 Bayer GB8）。")

            n_dst = int(_get(conv, "nDstLen", default=dst_size))
            img = np.frombuffer(dst_buf, dtype=np.uint8, count=n_dst)
            img = img.reshape(h, w, 3).copy()
        finally:
            try:
                self._cam.MV_CC_FreeImageBuffer(st_out)
            except Exception:                      # noqa: BLE001
                pass

        # 硬件时间戳：高 32 位 + 低 32 位拼成 64 位
        device_ts = (int(ts_hi) << 32) | int(ts_lo) if (ts_hi or ts_lo) else None

        f = Frame(image=img, index=self._i,
                  frame_id=int(frame_num) if frame_num is not None else None,
                  device_ts=device_ts, host_ts=time.perf_counter())
        self._i += 1
        return f

    def frames(self) -> Iterator[Frame]:
        while True:
            f = self.read()
            if f is None:
                time.sleep(0.001)
                continue
            yield f

    # ------------------------------------------------------------ 参数读写

    def info(self) -> Dict[str, object]:
        cam = self._cam
        mvs = self._mvs
        d: Dict[str, object] = {"后端": "mvs（MVS SDK）"}

        def _flt(node: str):
            try:
                st = _get(mvs, "MVCC_FLOATVALUE")()
                cam.MV_CC_GetFloatValue(node, st)
                return (_get(st, "fCurValue"), _get(st, "fMin"), _get(st, "fMax"))
            except Exception:                      # noqa: BLE001
                return (None, None, None)

        def _int(node: str):
            try:
                cls = _get(mvs, "MVCC_INTVALUE_EX") or _get(mvs, "MVCC_INTVALUE")
                st = cls()
                cam.MV_CC_GetIntValue(node, st)
                return _get(st, "nCurValue")
            except Exception:                      # noqa: BLE001
                return None

        def _enum(node: str):
            try:
                st = _get(mvs, "MVCC_ENUMVALUE")()
                cam.MV_CC_GetEnumValue(node, st)
                return _get(st, "nCurValue")
            except Exception:                      # noqa: BLE001
                return None

        exp_c, exp_min, exp_max = _flt("ExposureTime")
        gain_c, gain_min, gain_max = _flt("Gain")
        d.update({
            "分辨率": f"{_int('Width')} × {_int('Height')}",
            "像素格式(枚举值)": _enum("PixelFormat"),
            "曝光时间": _fmt_range(exp_c, exp_min, exp_max, "μs"),
            "增益": _fmt_range(gain_c, gain_min, gain_max, "dB"),
            "触发模式": _enum("TriggerMode"),
            "Payload": f"{self._payload} 字节",
        })
        return d

    def set_exposure_us(self, us: float) -> None:
        self._cam.MV_CC_SetFloatValue("ExposureTime", float(us))
        print(f"  [mvs] 曝光设为 {us} μs")

    def set_gain_db(self, db: float) -> None:
        self._cam.MV_CC_SetFloatValue("Gain", float(db))
        print(f"  [mvs] 增益设为 {db} dB")


def _fmt_range(cur, lo, hi, unit: str) -> str:
    if cur is None:
        return "读不到"
    if lo is None or hi is None:
        return f"{cur} {unit}"
    return f"{cur} {unit}（范围 {lo} ~ {hi} {unit}）"


# ================================================================
# 工厂
# ================================================================


def open_camera(prefer: Optional[str] = None, mock_video: Optional[str] = None,
                device_index: int = 0, fps: float = 30.0, **mock_kw):
    """按需返回一个相机后端（未 open，需自行调 .open()）。

    :param prefer: "auto"（默认，优先真机）/ "mvs" / "mock"
    :param mock_video: 走 mock 时喂的视频文件；不给就生成合成画面
    """
    prefer = prefer or config.CAMERA_BACKEND

    if prefer == "mock":
        return MockBackend(video=mock_video, fps=fps, **mock_kw)

    if prefer == "mvs":
        return MvsBackend(device_index=device_index)

    # auto：先真机，失败退回 mock 并明确告知
    try:
        return MvsBackend(device_index=device_index)
    except CameraError as exc:
        print(f"⚠ 真机后端不可用，退回 mock：\n{exc}\n")
        return MockBackend(video=mock_video, fps=fps, **mock_kw)