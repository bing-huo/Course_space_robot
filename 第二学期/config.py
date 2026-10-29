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
#
# 仓库按学期分目录：本文件在 第二学期/ 下，是第二学期的运行根目录
# （`python -m camera...` 要在本目录执行）。跨学期的资源用 PROJECT_ROOT 指过去。

REPO_ROOT = Path(__file__).resolve().parent            # 第二学期/
PROJECT_ROOT = REPO_ROOT.parent                        # 仓库根

DATA_DIR = REPO_ROOT / "data"
DETECT_LOG_DIR = DATA_DIR / "detect_log"        # 逐帧检测日志
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
RESULTS_DIR = DATA_DIR / "results"

# 第一学期遗留（第一学期/CV 冻结保留，回归测试要用）
V1_BASELINE_DIR = PROJECT_ROOT / "第一学期" / "data" / "v1_baseline"
V1_DIR = PROJECT_ROOT / "第一学期" / "CV"
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
# 二、实验区域与几何（理论推导 + 2026-10-23 现场实测覆盖）
# ================================================================
#
# ★ 2026-10-23 晚 定稿（以此为准；下面的"理论推导"只作存档）：
#   桁架：底部离桌面 12 cm、高 14 cm → **顶面 26 cm**；跟踪点取白色桁架轮廓质心（≈顶面）
#   镜头到桌面 143 cm → 实测 WD = 113.5 cm（板在桁架顶面）
#   用 Q12-200-15 棋盘反算：px/cm = 14.67（X）/ 14.70（Y）
#   视野 87.2 × 69.7 cm，测量区 77 × 60 cm，31 cm/s 稳态窗 1.33 s
#
# ---- 理论推导（2026-09-18 / 09-20，已被上面的实测覆盖）----
#   完全在画面内的行程 = 视野长 − 车长，这段要装下：
#       滤波器收敛 ≈ 21 cm（v1 实测）+ 稳态窗（31 cm/s × 1.0~2.0 s）
#   车长 < 25 cm → 2.0 s 方案需要视野 ≥ 108 cm → 区域 100 cm
#   px/cm 按【整个视野】算：1280 ÷ 110 = 11.64

# ---- 以下为 2026-10-23 晚 实测值（覆盖理论推导）----
REGION_W_CM = 77.0          # 测量区（沿运动方向）：视野 87.2 两端各留约 5 cm
REGION_H_CM = 60.0          # 测量区短边：视野 69.7 上下各留约 4.8 cm
WORKING_DISTANCE_M = 1.135  # 镜头 → 标定板平面（桁架顶面）实测
PX_PER_CM = 14.67           # 实测（Q12-200-15 反算；Y 向 14.70）

# ---- 跟踪面修正（2026-10-24 由实测速度反推）----
#
# 标定板放在桁架【顶面】，但俯视时穿过桁架镂空看到的白色结构以底部为主，
# 轮廓的等效平面在顶面下方约一个桁架高度。
# 实测：21 cm/s 跑出 18.95、30 cm/s 跑出 26.67，比值 0.886~0.889
#   → 等效平面比标定面低约 113.5 × (1/0.886 − 1) ≈ 14.6 cm ≈ 桁架高度 14 cm
# 修正：把世界距离乘 k = (WD + 14) / WD = 1.123
#   → 21 → 21.3（+1.4%）、30 → 29.96（−0.1%），两段同时对上
# 若以后把标定板直接垫到"等效平面"（或换更扁的目标），这个修正要重定。
TRACK_PLANE_DH_CM = 14.0
PLANE_SCALE = (WORKING_DISTANCE_M * 100.0 + TRACK_PLANE_DH_CM) / (WORKING_DISTANCE_M * 100.0)

# 传感器 / 镜头（标称，未变）
SENSOR_W_MM = 6.144         # 1280 × 4.8 μm
SENSOR_H_MM = 4.9152        # 1024 × 4.8 μm
LENS_FOCAL_MM = 8.0

# 由实测 px/cm 反推的视野（自检用，应 ≈ 87.2 × 69.7 cm）
FOV_W_CM = 1280.0 / PX_PER_CM                       # 87.2
FOV_H_CM = 1024.0 / (PX_PER_CM * 14.70 / 14.67)     # 69.7
FOV_MARGIN_CM = (FOV_W_CM - REGION_W_CM) / 2        # 5.1

# 轮廓面积下限（px²），P2.2 按实测 px/cm 反算。
#
# ⚠️ 方向：px/cm 变高 → 同一个目标占的像素**更多** → 阈值要**调高**。
# 第一学期阈值 800 px²。**2026-09-20 更正**：由 v1 标定四角反算，
#   区域横跨 ≈ 1082 px / 180 cm → 约 **6.0 px/cm**（不是早前估的 10.7）；
#   800 px² 折算物理面积约 22 cm²。
# 在 11.64 px/cm 下同样大小的目标约占 22 × 11.64² ≈ 3000 px²。
# **2026-10-23 更新**：实测 px/cm = 14.37（面积因子 1.52），且曝光锁 10 ms
#   → 31 cm/s 下拖影约 4.5 px，轮廓面积还会再缩一点。
#   起步值取 3000 × (14.37/11.64)² ≈ 4570，这里取整 4600。
# **2026-10-23 晚 实测定值（目标已换成白桁架）**：
#   静止白桁架轮廓 bbox 250×256 px、面积 **36,000 px²**（当时 px/cm 15.93）；
#   换到当前 px/cm 14.67 后约 **30,500 px²**。
#   阈值取 0.45× ≈ **14000 px²**（静止噪声实测为 0）。
#   ⚠️ 这是"静止+板拿走"前的数，推车测试后必须按运动中的实际面积复核。
CONTOUR_AREA_MIN = 14000.0

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

# ---- 相机工作点（2026-10-23 现场实测）----
#
# 曝光：1~5 ms 全部频闪（工作灯驱动 100 Hz 纹波），10 ms 起干净
#   → **10 ms 是唯一可用的短曝光**，L0~L4 全程固定，改曝光 = 已跑数据作废。
#   代价：31 cm/s 下拖影约 4.5 px（质心基本不受影响，contourArea 要重标）。
#
# 光圈/增益：F2.8 + 6 dB 下白桁架 P95 = 177（目标 150~200），噪声 std 3.5，
#   对比度（桁架/桌面）≈ 2.15，无过曝。F2.8 是光圈全开，再暗只能加增益/曝光。
EXPOSURE_US = 10000.0
GAIN_DB = 6.0
APERTURE_F = 2.8

# 曝光定标判据（P1.4）：目标表面最亮区灰度落在 150~200，暗部不低于 30。
# 2026-10-23 定：把 200~240 留给 L2 的代理量定义，避免两条判据撞车。
EXPOSURE_CALIB_BRIGHT_MIN = 150
EXPOSURE_CALIB_BRIGHT_MAX = 200
EXPOSURE_CALIB_DARK_MIN = 30

# ================================================================
# 四、算法参数（沿用第一学期，按新 px/cm 调整）
# ================================================================

# 2026-10-23 实测（out/car_2lights_15s.mp4，两盏灯、10 ms）：
#   开阴影检测时，小车轮廓中位 5.2 万 px²、阴影另占 2.2 万 px²（约 30%）。
#   关掉阴影检测（v1 的 False）会把车和影子连成一片 → 面积虚高、质心被影子拉偏，
#   所以这里改成 True，并在后续处理里只保留 255 的前景、丢掉 127 的阴影。
MOG2_HISTORY = 500
MOG2_VAR_THRESHOLD = 50
MOG2_DETECT_SHADOWS = True

MORPH_KERNEL_SIZE = 5                # 椭圆核
TRAJ_MAXLEN = 45                     # 轨迹拖尾长度

TARGET_SPEEDS_CMS = (21.0, 31.0)     # 两个考核速度

# ================================================================
# 五、测量协议（v2 §5）
# ================================================================

# 指标 1 · 稳态区间判据（V2.3 起，四条同时满足）
#   ① 位置：目标外接框完全落在 ROI 内（ROI = 画面四周内缩 ROI_MARGIN_CM）
#   ② 速度：|v - v_target| / v_target ≤ STEADY_TOL（αβ 平滑后的速度）
#   ③ 连续：相邻检出帧的帧号间隔 ≤ MAX_GAP_FRAMES（连续漏检超过它即断开）
#   ④ 长度：最长连续段时长 ≥ STEADY_MIN_DURATION_S
#   不满足 ④ → 判“无有效稳态段”，该次按失败处理
STEADY_TOL = 0.15                    # |v - v_target| / v_target ≤ 15%
STEADY_MIN_DURATION_S = 1.0          # 最长连续区间长度 ≥ 1.0 s
ROI_MARGIN_CM = 5.0                  # ROI 相对画面四周内缩；按 PX_PER_CM 折算成像素
MAX_GAP_FRAMES = 3                   # 检出帧号间隔 > 3 帧（≈50 ms）即断段

# 指标 2 · 检测失败率
WARMUP_EXCLUDE_S = 1.0               # 排除开头 1.0 s 背景建模期
FAILURE_RATE_LIMIT = 0.15            # ≤ 15%
#
# ★ 录制协议：车入镜前 ≥ 1.5 s 就开始录。
#   这样被排除的开头 1 s 正好全是空场景，MOG2 拿它建背景，一点不浪费；
#   目标从出现的第一帧起就是匀速的，稳态区间也更好选。

# 光照等级（L0–L4）—— 用相机自测的代理量定义，不用 lux（v2 §5.3）
LIGHT_LEVELS = ("L0", "L1", "L2", "L3", "L4")

# 灯位初值（2026-10-23）：两盏 100 W 工作灯，**无调光**，只能靠距离/角度分级。
# A = 基础灯（固定），B = 强光灯（只动它）。单位 m，灯心到测量区中心。
# 装完必须用相机代理量实测回填，并把实测距离/角度写进 data/conditions.csv。
LIGHT_DISTANCE_M = {
    "L0": None,     # A、B 全关，仅室内光
    "L1": 2.0,      # A 开，B 关
    "L2": 2.0,      # A + B 对称
    "L3": 1.2,      # B 斜射
    "L4": 0.8,      # B 最近，局部过曝
}

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
    print(f"区域      {REGION_W_CM:.0f} × {REGION_H_CM:.0f} cm（2026-10-23 实测）")
    print(f"视野      {FOV_W_CM:.1f} × {FOV_H_CM:.1f} cm（每边留 {FOV_MARGIN_CM:.1f} cm）")
    print(f"工作距离  {WORKING_DISTANCE_M:.3f} m（镜头→车顶跟踪面）")
    print(f"px/cm     {PX_PER_CM:.2f}（实测）")
    print(f"曝光/增益 {EXPOSURE_US/1000:.1f} ms / {GAIN_DB:.0f} dB，光圈 F{APERTURE_F}")
    print(f"轮廓阈值  {CONTOUR_AREA_MIN:.0f} px²（待 P2.2 按实测反算）")
    print(f"质心偏移  {'未标定（P1.8）' if CY_OFFSET_K is None else CY_OFFSET_K}")