# -*- coding: utf-8 -*-
"""第二学期相机接入模块。

    from camera import FrameClock        # 统一时间基准（P0.3.a），不依赖 OpenCV
    from camera.backend import open_camera

命令行工具见 docs/相机打通步骤.md：

    python -m camera.camera_capture list|info|snap|record|bench
"""

from camera.frame_clock import ClockStats, FrameClock

__all__ = ["FrameClock", "ClockStats"]

try:
    # 需要 OpenCV；没装好时至少 FrameClock 仍然可用（自测不需要 cv2）
    from camera.backend import CameraError, Frame, MockBackend, MvsBackend, open_camera

    __all__ += ["Frame", "CameraError", "MockBackend", "MvsBackend", "open_camera"]
except Exception as _exc:                      # noqa: BLE001
    _IMPORT_ERROR = _exc