# -*- coding: utf-8 -*-
"""
全局参数（对应 P0.3.f「参数外置」）

第一学期这些魔数散落在 main.py 的主流程里：history / varThreshold /
contourArea 下限 / 形态学核尺寸 / 标定区域尺寸 / 质心偏移系数……
改一个要翻代码，而且改错了没人知道。

从第二学期起，**所有会影响物理结论的数字只能出现在本文件里**。
主流程代码只读不写。

────────────────────────────────────────────────────────────────
★ 换了支架、换了镜头、换了区域尺寸之后，下列参数必须重新标定：
    WORKING_DISTANCE_M   （几何，改了就得重算 PX_PER_CM）
    PX_PER_CM            （P1.9 实测）
    CONTOUR_AREA_MIN     （由 PX_PER_CM 反算）
    CY_OFFSET_K          （P1.8 重标）
    REGION_W_CM / REGION_H_CM（改了区域＝改机位＝以上全部作废）
────────────────────────────────────────────────────────────────
"""

from pathlib import Path

# ================================================================
# 一、路径
# ================================================================

REPO_ROOT = Path(__file__).resolve().parent

DATA_DIR = REPO_ROOT / "data"
V1_BASELINE_DIR = DATA_DIR / "v1_baseline"      # P0.3.g 归档
DETECT_LOG_DIR = DATA_DIR / "detect_log"        # 逐帧检测日志
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
RESULTS_DIR = DATA_DIR / "results"

# 第一学期遗留（CV/ 冻结保留，回归测试要用）
V1_DIR = REPO_ROOT / "CV"
V1_CALIBRATION_CONFIG = V1_DIR / "calibration_config.json"

# 第二学期标定产物
CALIBRATION_DIR = REPO_ROOT / "calibration"
CALIBRATION_CONFIG = CALIBRATION_DIR / "calibration_config.json"
CAMERA_PARAMS_NPZ = CALIBRATION_DIR / "camera_params.npz"


def ensure_dirs() -> None:
    """建好所有输出目录；程序启动时调一次。"""
    for d in (DATA_DIR, DETECT_LOG_DIR, GROUND_TRUTH_DIR, RESULTS_DIR,
              CALIBRATION_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ================================================================
# 二、实验区域与几何（2026-09-18 定，详见 docs/相机与镜头参数汇总.md §4）
# ================================================================
#
# 前提：机器人在画面外加速到目标速度后入镜（助跑段只需留空间，不需设计）。
# 所以区域长边不必装下加速段，只需装住一个 ≥ 2 s 的稳态测量窗口。
#
#   REGION_W_CM = 90          测量段长度
#   REGION_H_CM = 70          横向（短边不要超过长边的 0.8 倍，传感器是 5:4）
#   FOV = 区域 + 每边 5 cm 留边 → 100 cm × 80 cm
#   WD  = FOV_w ÷ 0.768（f = 8 mm 时的比例）→ 1.30 m
#   px/cm = 1280 ÷ FOV_w = 12.8
#
# ★ px/cm 是按**整个视野**算的，不是按区域宽度算的：
#   1280 个像素铺满 100 cm，所以 12.8 px/cm。
#   换算成区域内的像素数：1 cm ⇔ 12.8 px（与位置无关）。

REGION_W_CM = 90.0          # 区域长边（沿运动方向）
REGION_H_CM = 70.0          # 区域短边

FOV_MARGIN_CM = 5.0         # 视野四周各留的边
FOV_W_CM = REGION_W_CM + 2 * FOV_MARGIN_CM      # 100.0
FOV_H_CM = REGION_H_CM + 2 * FOV_MARGIN_CM      # 80.0

SENSOR_W_MM = 6.144         # 1280 × 4.8 μm
SENSOR_H_MM = 4.9152        # 1024 × 4.8 μm
LENS_FOCAL_MM = 8.0

WORKING_DISTANCE_M = (FOV_W_CM * 10.0) * LENS_FOCAL_MM / SENSOR_W_MM / 1000.0   # ≈ 1.302 m

# ---- 以下三项必须现场实测后覆盖（P1.9 / P1.8）----

# px/cm，P1.9 实测。理论值见上：1280 ÷ FOV_W_CM = 12.8
PX_PER_CM = 1280.0 / FOV_W_CM                  # 12.8，待实测覆盖

# 轮廓面积下限（px²），P2.2 按实测 px/cm 反算。
#
# ⚠️ 方向：px/cm 变高 → 同一个目标占的像素**更多** → 阈值要**调高**。
# 第一学期阈值 800 px²（手机拍摄，约 10.7 px/cm）折算成物理面积约 7 cm²；
# 在 12.8 px/cm 下同样大小的目标约占 7 × 12.8² ≈ 1150 px²。
# **这只是"等效换算"的起点，不是最终值** —— 最终必须按目标实测尺寸
# 乘 px/cm² 重算（P1.9 → P2.2）。
CONTOUR_AREA_MIN = 1150.0

# 质心纵向偏移系数。第一学期是 cy + h_box * 0.3，那个 0.3 是透视补偿的
# 经验常数，换机位后失效，必须重标（P1.8）。未标定时置 None，程序应告警。
CY_OFFSET_K = None          # ← P1.8 填

# ================================================================
# 三、相机与镜头（详细参数见 docs/相机与镜头参数汇总.md）
# ================================================================

CAMERA_MODEL = "MV-CU013-A0UC"       # 彩色
LENS_MODEL = "MVL-HF0828M-6MPE"      # 8 mm FA

# 实验全程必须锁死的设置（改一项＝已跑数据作废）
CAMERA_LOCKED = {
    "ExposureAuto": "Off",
    "GainAuto": "Off",
    "BalanceWhiteAuto": "Off",       # 彩色款！AWB 会让平均灰度随光照自漂
    "GammaSelector": "User",         # Gamma 固定或关闭
    "BinningHorizontal": 1,
    "BinningVertical": 1,
}

# 曝光定标的判据（P1.4）：目标表面最亮区灰度落在 200~240，暗部不低于 30
EXPOSURE_CALIB_BRIGHT_MIN = 200
EXPOSURE_CALIB_BRIGHT_MAX = 240
EXPOSURE_CALIB_DARK_MIN = 30

# ================================================================
# 四、算法参数（沿用第一学期，按新 px/cm 调整）
# ================================================================

MOG2_HISTORY = 500
MOG2_VAR_THRESHOLD = 50
MOG2_DETECT_SHADOWS = False

MORPH_KERNEL_SIZE = 5                # 椭圆核
TRAJ_MAXLEN = 45                     # 轨迹拖尾长度

TARGET_SPEEDS_CMS = (21.0, 31.0)     # 两个考核速度

# ================================================================
# 五、测量协议（v2 §5）
# ================================================================

# 指标 1 · 稳态区间判据
STEADY_TOL = 0.15                    # |v - v_target| / v_target ≤ 15%
STEADY_MIN_DURATION_S = 1.0          # 最长连续区间长度 ≥ 1.0 s

# 指标 2 · 检测失败率
WARMUP_EXCLUDE_S = 1.0               # 排除开头 1.0 s 背景建模期
FAILURE_RATE_LIMIT = 0.15            # ≤ 15%
#
# ★ 录制协议：车入镜前 ≥ 1.5 s 就开始录。
#   这样被排除的开头 1 s 正好全是空场景，MOG2 拿它建背景，一点不浪费；
#   目标从出现的第一帧起就是匀速的，稳态区间也更好选。

# 光照等级（L0–L4）—— 用相机自测的代理量定义，不用 lux（v2 §5.3）
LIGHT_LEVELS = ("L0", "L1", "L2", "L3", "L4")

# ================================================================
# 六、相机采集
# ================================================================

CAPTURE_TIMEOUT_MS = 1000            # 取帧超时
CAPTURE_FPS_TARGET = None            # None = 用相机最大帧率；跨设备对比时设 30
CAMERA_BACKEND = "auto"              # auto | mvs | mock

# MVS SDK 安装路径候选（按顺序探测；也可用环境变量 MVS_PATH 覆盖）
MVS_PATH_CANDIDATES = [
    r"C:\Program Files (x86)\MVS",
    r"C:\Program Files\MVS",
    r"D:\MVS",
]


if __name__ == "__main__":
    # 直接运行本文件可以看当前几何推导是否自洽
    print(f"区域      {REGION_W_CM:.0f} × {REGION_H_CM:.0f} cm")
    print(f"视野      {FOV_W_CM:.1f} × {FOV_H_CM:.1f} cm（每边留 {FOV_MARGIN_CM:.0f} cm）")
    print(f"工作距离  {WORKING_DISTANCE_M:.3f} m")
    print(f"px/cm     {PX_PER_CM:.2f}（待 P1.9 实测覆盖）")
    print(f"轮廓阈值  {CONTOUR_AREA_MIN:.0f} px²（待 P2.2 按实测反算）")
    print(f"质心偏移  {'未标定（P1.8）' if CY_OFFSET_K is None else CY_OFFSET_K}")