# -*- coding: utf-8 -*-
"""第二学期相机接入模块。

    from camera import FrameClock        # 统一时间基准（P0.3.a），不依赖 OpenCV
    from camera.backend import open_camera

命令行工具见 docs/相机打通步骤.md：

    python -m camera.camera_capture list|info|snap|record|bench
"""

__all__ = [
    "FrameClock", "ClockStats",
    "Frame", "CameraError", "MockBackend", "MvsBackend", "open_camera",
]

# 惰性导入（PEP 562）。
#
# 不在包初始化时 eager import，有两个好处：
#   1) `python -m camera.frame_clock` 不会再报
#      "found in sys.modules after import of package 'camera'" 的 RuntimeWarning
#      ——因为模块在被 runpy 执行之前不会先被这个 __init__ 导进来；
#   2) cv2 没装好时，光是 `import camera` 也能成功，FrameClock 仍然可用
#      （它的自测不需要 OpenCV）。

_LAZY = {
    "FrameClock": "camera.frame_clock",
    "ClockStats": "camera.frame_clock",
    "Frame": "camera.backend",
    "CameraError": "camera.backend",
    "MockBackend": "camera.backend",
    "MvsBackend": "camera.backend",
    "open_camera": "camera.backend",
}


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module 'camera' has no attribute {name!r}")
    from importlib import import_module
    return getattr(import_module(module_name), name)


def __dir__():
    return sorted(__all__)