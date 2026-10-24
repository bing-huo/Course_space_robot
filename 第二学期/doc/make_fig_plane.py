import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch, Polygon
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=220)
ax.set_xlim(0, 10); ax.set_ylim(0, 7); ax.axis("off")

# 地面
ax.add_patch(Rectangle((0.4, 0.6), 9.2, 0.18, color="#D9D9D9", ec="#8C8C8C"))
ax.text(9.7, 0.55, "桌面", ha="right", va="top", fontsize=10, color="#555")

# 小车 + 桁架（简化为两条竖线 + 底部横梁）
ax.add_patch(Rectangle((3.6, 0.78), 2.6, 0.55, color="#404040"))      # 车体（黑）
ax.text(4.9, 0.95, "小车", ha="center", va="center", fontsize=9, color="white")
for x in (4.0, 5.8):
    ax.add_patch(Rectangle((x, 1.33), 0.14, 2.2, color="#F2F2F2", ec="#9A9A9A"))
ax.add_patch(Rectangle((3.95, 3.45), 2.1, 0.12, color="#F2F2F2", ec="#9A9A9A"))
ax.text(6.15, 2.4, "桁架\n(镂空)", ha="left", va="center", fontsize=10, color="#555")

# 标定板（顶面）
ax.add_patch(Rectangle((4.05, 3.57), 1.9, 0.12, color="#2F5597"))
ax.text(4.95, 3.9, "标定板（桁架顶面）", ha="center", va="bottom", fontsize=10, color="#2F5597")

# 相机
ax.add_patch(Rectangle((4.55, 5.9), 0.9, 0.55, color="#1F3864"))
ax.add_patch(Polygon([[4.72, 5.9], [5.28, 5.9], [5.15, 5.72], [4.85, 5.72]], color="#1F3864"))
ax.text(5.6, 6.15, "工业相机（143 cm）", ha="left", va="center", fontsize=10, color="#1F3864")

# 视线
for x in (4.1, 4.95, 5.9):
    ax.plot([5.0, x], [5.72, 3.6], color="#7F7F7F", lw=0.8, ls=(0, (3, 2)))

# 两个平面
ax.plot([2.2, 7.6], [3.63, 3.63], color="#2F5597", lw=1.4, ls="--")
ax.text(7.7, 3.63, "标定面", ha="left", va="center", fontsize=10, color="#2F5597")
ax.plot([2.2, 7.6], [1.40, 1.40], color="#C00000", lw=1.4, ls="--")
ax.text(7.7, 1.40, "等效跟踪面", ha="left", va="center", fontsize=10, color="#C00000")

# Δh 标注
ax.add_patch(FancyArrowPatch((2.6, 1.40), (2.6, 3.63), arrowstyle="<->", color="#C00000", lw=1.4))
ax.text(2.45, 2.5, "Δh ≈ 14 cm", ha="right", va="center", fontsize=10, color="#C00000")

# 说明
ax.text(0.4, 6.6, "标定板在桁架顶面，俯视穿过镂空看到的白色结构以底部为主", fontsize=10, color="#333")
ax.text(0.4, 0.15, "等效平面比标定面低约 14 cm（= 桁架高度）→ 速度按 WD_c/WD_t 偏小", fontsize=10, color="#333")

fig.tight_layout()
fig.savefig("fig_plane_error.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("saved fig_plane_error.png")
