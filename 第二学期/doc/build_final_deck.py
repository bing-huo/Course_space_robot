#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《第二学期结课汇报》PPT

沿用上一次周汇报的模板（院徽/院训/底栏），以结果展示为主：
    一、实验平台（4 张平台图）
    二、相机标定（标定成果图 + 关键数字）
    三、算法移植（主框架）
    四、算法改进（核心改进点 + 标注帧）
    五、实验方案（一页一个表格）
    六、七、标注视频占位（2 页）
    八、结果图表（汇总图 + 6 张四宫格，2 张/页）
    九、目标达成
    十、总结
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Cm, Pt

import build_deck as bd
from build_deck import (BLUE, DARK, GREEN, ORANGE, RED, GRAY, BODY, CARD_FILL,
                        CARD_LINE, accent_card, arrow, banner, metric_strip,
                        picture, set_font, stat_card, table, textbox, _rect)

WEEKLY = bd.BASE / "视觉算法组_周汇报_10.30.pptx"
OUT = bd.BASE / "视觉算法组_结课汇报.pptx"

ARCH = bd.ROOT / "第二学期" / "验收成果_2026-10-30"
PLAT = ARCH / "00_实验平台"
CAL = ARCH / "01_标定"
FIG = bd.ROOT / "第二学期" / "out" / "acceptance" / "figures"


class FinalDeck(bd.Builder):
    def __init__(self):
        bd.TEMPLATE = WEEKLY
        super().__init__()

    # ---------- 通用 ----------
    def build(self):
        sldIdLst = self.prs.slides._sldIdLst
        for sldId in list(sldIdLst)[:self.n_orig]:
            self.prs.part.drop_rel(sldId.rId)
            sldIdLst.remove(sldId)
        self.platform()
        self.calibration()
        self.algorithm()
        self.improve()
        self.scheme()
        self.video_one()
        self.video_two()
        self.summary_fig()
        self.grids_l1()
        self.grids_l2()
        self.grids_l3()
        self.goal()
        self.conclusion()
        self.prs.save(str(OUT))
        print(f"saved {OUT}")

    def video_placeholder(self, s, img, x, y, w, h, caption, detail):
        picture(s, img, x, y, w, h)
        cx, cy = x + w / 2, y + h / 2
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Cm(cx - 1.5), Cm(cy - 1.5),
                                  Cm(3.0), Cm(3.0))
        circ.fill.solid()
        circ.fill.fore_color.rgb = bd.RGBColor.from_string("FFFFFF")
        circ.line.color.rgb = bd.RGBColor.from_string("D6E4F0")
        circ.line.width = Pt(1.5)
        tri = s.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE,
                                 Cm(cx - 0.55), Cm(cy - 0.75), Cm(1.4), Cm(1.5))
        tri.rotation = 90
        tri.fill.solid()
        tri.fill.fore_color.rgb = bd.RGBColor.from_string(BLUE)
        tri.line.fill.background()
        textbox(s, x, y + h + 0.1, w, 0.7, caption, size=11, bold=True,
                color=DARK, align=PP_ALIGN.CENTER)
        textbox(s, x, y + h + 0.75, w, 0.6, detail, size=9.5, color=GRAY,
                align=PP_ALIGN.CENTER)

    # ---------- 一、实验平台 ----------
    def platform(self):
        s = self.new_slide("一、实验平台")
        textbox(s, 0.9, 2.0, 9.4, 2.7,
                "面向“在轨服务机器人地面试验”任务：\n"
                "俯视相机 + 双 100 W 工作灯 +\n"
                "桁架小车 + 白桌，完成平台搭建。", size=13, color=BODY)
        data = [
            ["项目", "参数"],
            ["相机", "MV-CU013-A0UC"],
            ["分辨率", "1280 × 1024"],
            ["镜头", "MVL-HF0828M-6MPE"],
            ["机位", "镜头 → 桌面 144 cm"],
            ["曝光/光圈/增益", "10 ms / F2.8 / 6 dB"],
            ["桌面", "白桌（未铺黑布）"],
        ]
        table(s, 0.9, 5.0, 9.4, 8.2, data, col_w=[3.7, 5.7], fsize=11.5,
              first_col_bold=True)
        textbox(s, 0.9, 13.6, 9.4, 1.2,
                "注：图片取自验收成果 00_实验平台，共 4 张。", size=9.5, color=GRAY)

        picture(s, PLAT / "平台全景_相机与桌面.jpg", 10.6, 2.0, 10.8, 6.6)
        textbox(s, 10.6, 8.65, 10.8, 0.6, "平台全景：相机、桌面与左灯", size=9.5,
                color=GRAY, align=PP_ALIGN.CENTER)
        picture(s, PLAT / "平台全景_灯位与桁架车.jpg", 21.8, 2.0, 10.9, 6.6)
        textbox(s, 21.8, 8.65, 10.9, 0.6, "平台全景：灯位与桁架小车", size=9.5,
                color=GRAY, align=PP_ALIGN.CENTER)
        picture(s, PLAT / "平台全景_三灯布置.jpg", 10.6, 9.8, 10.8, 6.6)
        textbox(s, 10.6, 16.45, 10.8, 0.6, "三灯布置与采集端", size=9.5,
                color=GRAY, align=PP_ALIGN.CENTER)
        picture(s, PLAT / "相机视角_俯拍.png", 21.8, 9.8, 10.9, 6.6)
        textbox(s, 21.8, 16.45, 10.9, 0.6, "相机视角：俯拍画面", size=9.5,
                color=GRAY, align=PP_ALIGN.CENTER)
        self.notes(s, "实验平台：按任务情景搭好相机、双灯、桁架小车与白桌；四张图分别展示全景、灯位、三灯布置和相机实际画面。")

    # ---------- 二、相机标定 ----------
    def calibration(self):
        s = self.new_slide("二、相机标定")
        imgs = [
            (CAL / "标定原图_Q12-200-15.png", "① 标定原图"),
            (CAL / "角点标注_88点.png", "② 88 个内角点 + 重投影网格"),
            (CAL / "5cm网格_全视野.png", "③ 全视野 5 cm 网格"),
        ]
        x = 0.9
        for path, cap in imgs:
            picture(s, path, x, 2.0, 10.4, 8.32)
            textbox(s, x, 10.4, 10.4, 0.6, cap, size=10, color=GRAY,
                    align=PP_ALIGN.CENTER)
            x += 10.8
        stat_card(s, 0.9, 11.3, 7.7, 2.6, "0.044", "px", "重投影 RMS")
        stat_card(s, 9.0, 11.3, 7.7, 2.6, "14.73", "px/cm", "像素尺度（X）")
        stat_card(s, 17.1, 11.3, 7.7, 2.6, "88/88", "", "内角点全部检出")
        stat_card(s, 25.2, 11.3, 7.7, 2.6, "114.8", "cm", "标定面 WD")
        textbox(s, 0.9, 14.3, 31.9, 1.4,
                "标定板 Q12-200-15 放在桁架顶面；视野 86.9 × 69.3 cm，测量区 76.9 × 59.3 cm；"
                "单应 H 把像素映射到厘米。", size=12, color=BODY)
        banner(s, 0.9, 15.9, 31.9, 1.7,
               "标定质量良好：88/88 个内角点全部检出，重投影 RMS 0.044 px（≈0.03 mm）",
               "E8F5E9", GREEN, GREEN, size=12.5)
        self.notes(s, "相机标定：标定原图、88 角点、5 cm 网格三张图；88/88 角点、RMS 0.044 px、14.73 px/cm；单应 H 打通像素到厘米。")

    # ---------- 三、算法移植 ----------
    def algorithm(self):
        s = self.new_slide("三、算法移植")
        steps = [
            ("相机取流", "时间戳 + FrameID"),
            ("灰度 + 背景建模", "MOG2"),
            ("形态学开 / 闭", "5×5 椭圆核"),
            ("最大轮廓", "面积 ≥ 阈值"),
            ("图像矩质心", "m10 / m00"),
            ("单应 H", "cm → px"),
            ("速度", "差分 + αβ"),
        ]
        x = 0.9
        for i, (st, sub) in enumerate(steps):
            shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(2.2),
                                     Cm(4.1), Cm(2.1))
            shp.adjustments[0] = 0.12
            shp.fill.solid()
            shp.fill.fore_color.rgb = bd.RGBColor.from_string(bd.STAT_FILL)
            shp.line.color.rgb = bd.RGBColor.from_string(CARD_LINE)
            tf = shp.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run(); r.text = st
            set_font(r, 11.5, True, DARK)
            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            r = p2.add_run(); r.text = sub
            set_font(r, 9.5, False, GRAY)
            if i < len(steps) - 1:
                arrow(s, x + 4.15, 3.0, 0.35, 0.5)
            x += 4.6
        banner(s, 0.9, 4.75, 31.9, 1.5,
               "主框架：运动前景 + 亮度门限 → 最大轮廓 → 质心 → 单应 → αβ 平滑测速",
               "EAF3FB", BLUE, DARK, size=12.5)
        picture(s, FIG / "pick_L1_21_1_440.jpg", 0.9, 6.5, 15.4, 10.0)
        textbox(s, 0.9, 16.6, 15.4, 0.7,
                "运行画面：绿色轮廓、红色质心、橙色速度矢量与 HUD",
                size=10, color=GRAY, align=PP_ALIGN.CENTER)
        accent_card(s, 16.9, 6.5, 15.9, 3.0, "① 前景提取",
                    "MOG2 背景差分得到运动像素，再用亮度门限筛出目标", bsize=11.5)
        accent_card(s, 16.9, 9.8, 15.9, 3.0, "② 目标定位",
                    "取最大轮廓，用图像矩 m10/m00 求质心（亚像素）", bsize=11.5)
        accent_card(s, 16.9, 13.1, 15.9, 3.0, "③ 速度计算",
                    "单应 H 把质心映射到厘米坐标，αβ 滤波后差分求速度", bsize=11.5)
        textbox(s, 16.9, 16.35, 15.9, 0.8,
                "移植后暴露的问题：单侧强光的长阴影被并成前景。",
                size=10.5, color=RED)
        self.notes(s, "算法移植：7 步主框架；直接搬过来后遇到强光长阴影问题，引出下一页的改进。")

    # ---------- 四、算法改进 ----------
    def improve(self):
        s = self.new_slide("四、算法改进")
        items = [
            ("① 曝光锁定", "快门定在 10 ms，正好一个 100 Hz 周期，画面不闪"),
            ("② 亮度门限", "影子比目标暗，只保留“又亮又在动”的像素"),
            ("③ 自适应阈值", "门槛跟着画面亮度走，换光照不用改参数"),
            ("④ αβ + 稳态窗", "速度平滑、自动挑出稳定段，失败率可统计"),
        ]
        y = 2.3
        for t, b in items:
            accent_card(s, 0.9, y, 13.2, 2.8, t, b, bsize=11.5)
            y += 3.15
        banner(s, 0.9, 15.2, 13.2, 2.2,
               "失败率 19.6% → 0%，速度误差 −10% → ±1.3%",
               "E8F5E9", GREEN, GREEN, size=12.5)
        picture(s, FIG / "pick_L3_31_1_440.jpg", 14.8, 2.3, 18.0, 12.6)
        textbox(s, 14.8, 15.05, 18.0, 0.7,
                "改进后的标注画面：轮廓、质心、速度矢量、HUD 与稳态标记",
                size=10, color=GRAY, align=PP_ALIGN.CENTER)
        textbox(s, 14.8, 15.75, 18.0, 1.6,
                "核心改进：曝光挡频闪 + 亮度筛影子 + 自适应阈值 + 平滑与稳态窗，\n"
                "使强光下的检出和测速稳定下来。", size=11, color=BODY)
        self.notes(s, "算法改进：四点——曝光锁定、亮度门限、自适应阈值、αβ+稳态窗；失败率从 19.6% 降到 0%。")

    # ---------- 五、实验方案（表格） ----------
    def scheme(self):
        s = self.new_slide("五、实验方案")
        data = [
            ["等级", "照度区间", "目标速度"],
            ["L1", "333–368 lx", "21 / 31 cm/s"],
            ["L2", "428–473 lx", "21 / 31 cm/s"],
            ["L3", "523–578 lx", "21 / 31 cm/s"],
        ]
        table(s, 3.9, 2.4, 26.0, 5.6, data,
              col_w=[4.6, 10.4, 11.0], fsize=14, first_col_bold=True)
        textbox(s, 0.9, 8.5, 31.9, 1.0,
                "每个等级在 21 / 31 cm/s 下各录一段 15 s、60 fps 视频；"
                "曝光 10 ms / F2.8 / 6 dB 全程固定。", size=12.5, color=BODY)
        accent_card(s, 0.9, 10.0, 10.2, 4.2, "指标 1：速度误差",
                    "稳态阶段速度相对误差 ≤ 20%\n（稳态均值 vs 目标速度）", bsize=11.5)
        accent_card(s, 11.8, 10.0, 10.2, 4.2, "指标 2：检测失败率",
                    "失败率 ≤ 15%\n（统计窗内未检出帧 ÷ 总帧数）", bsize=11.5)
        accent_card(s, 22.7, 10.0, 10.2, 4.2, "稳态阶段（四条）",
                    "ROI 内 · 速度差 ≤15%\n连续（漏检 ≤3 帧）· ≥1.0 s", bsize=11.5)
        textbox(s, 0.9, 14.8, 31.9, 1.0,
                "所有组合使用同一曝光与增益，判据由测速脚本自动判定。",
                size=10.5, color=GRAY)
        self.notes(s, "实验方案：三个光照等级，每档 21/31 cm/s 各录一段；两项指标与稳态判据。")

    # ---------- 六、七、标注视频占位 ----------
    def video_one(self):
        s = self.new_slide("六、标注视频：L1 · 21 cm/s")
        self.video_placeholder(s, FIG / "pick_L1_21_1_440.jpg", 0.9, 2.2, 17.0, 13.6,
                               "▶ 标注视频（占位）",
                               "out/acceptance/videos/L1_21_1_v23.mp4")
        textbox(s, 18.9, 2.3, 14.0, 0.9, "视频内容", size=15, bold=True, color=DARK)
        textbox(s, 18.9, 3.3, 14.0, 5.6,
                "• 绿色轮廓、红色质心、橙色速度矢量\n"
                "• 左上 HUD：目标、实测、误差、失败率\n"
                "• 底部时间轴：绿色段为稳态统计窗", size=12.5, color=BODY)
        stat_card(s, 18.9, 9.6, 6.6, 3.2, "21.02", "cm/s", "稳态速度")
        stat_card(s, 26.2, 9.6, 6.6, 3.2, "+0.1%", "", "相对误差")
        banner(s, 18.9, 13.4, 14.0, 2.2,
               "失败率 0.3%｜稳态窗 2.73 s", "E8F5E9", GREEN, GREEN, size=12.5)
        self.notes(s, "标注视频一：L1 21 cm/s。播放时展示 HUD、速度矢量、稳态时间轴；结果 21.02 cm/s、+0.1%、失败率 0.3%。")

    def video_two(self):
        s = self.new_slide("七、标注视频：L3 · 31 cm/s")
        self.video_placeholder(s, FIG / "pick_L3_31_1_440.jpg", 0.9, 2.2, 17.0, 13.6,
                               "▶ 标注视频（占位）",
                               "out/acceptance/videos/L3_31_1_v23.mp4")
        textbox(s, 18.9, 2.3, 14.0, 0.9, "视频内容", size=15, bold=True, color=DARK)
        textbox(s, 18.9, 3.3, 14.0, 5.6,
                "• 绿色轮廓、红色质心、橙色速度矢量\n"
                "• 左上 HUD：目标、实测、误差、失败率\n"
                "• 底部时间轴：绿色段为稳态统计窗", size=12.5, color=BODY)
        stat_card(s, 18.9, 9.6, 6.6, 3.2, "31.30", "cm/s", "稳态速度")
        stat_card(s, 26.2, 9.6, 6.6, 3.2, "+1.0%", "", "相对误差")
        banner(s, 18.9, 13.4, 14.0, 2.2,
               "失败率 0.5%｜稳态窗 1.78 s", "E8F5E9", GREEN, GREEN, size=12.5)
        self.notes(s, "标注视频二：L3 31 cm/s。结果 31.30 cm/s、+1.0%、失败率 0.5%。")

    # ---------- 八、结果图表 ----------
    def summary_fig(self):
        s = self.new_slide("八、结果总览")
        picture(s, FIG / "summary_light_levels.png", 0.9, 2.0, 26.4, 14.6)
        textbox(s, 0.9, 16.75, 26.4, 0.7,
                "三档光照 × 21/31 cm/s：速度相对误差与检测失败率（红线为判据）",
                size=10.5, color=GRAY, align=PP_ALIGN.CENTER)
        stat_card(s, 27.8, 2.4, 5.8, 3.2, "1.3%", "", "最大速度误差")
        stat_card(s, 27.8, 5.9, 5.8, 3.2, "1.5%", "", "最大失败率")
        stat_card(s, 27.8, 9.4, 5.8, 3.2, "6/6", "", "全部达标")
        textbox(s, 27.8, 13.0, 5.8, 3.2,
                "指标 1：≤20%\n指标 2：≤15%", size=11.5, color=GRAY)
        self.notes(s, "结果总览：汇总图 + 三个关键数字；6/6 达标，最大误差 1.3%、最大失败率 1.5%。")

    def grid_pair(self, title, left, right, notes):
        s = self.new_slide(title)
        for img, x, cap in (left, right):
            picture(s, img, x, 2.5, 15.9, 11.0)
            textbox(s, x, 13.7, 15.9, 0.7, cap, size=10.5, color=GRAY,
                    align=PP_ALIGN.CENTER)
        textbox(s, 0.9, 15.2, 31.9, 2.4,
                "左/右图：轨迹、X-Y 随时间、αβ 速度（含 ±15% 带）、轮廓面积；"
                "绿色阴影为稳态窗。", size=10.5, color=GRAY)
        self.notes(s, notes)

    def grids_l1(self):
        self.grid_pair(
            "八、结果图表：L1（333–368 lx）",
            (FIG / "L1_21_1_v23.png", 0.9, "L1 · 21 cm/s：21.02（+0.1%），失败率 0.3%"),
            (FIG / "L1_31_1_v23.png", 17.1, "L1 · 31 cm/s：31.13（+0.4%），失败率 1.5%"),
            "L1 两个速度的四宫格。")

    def grids_l2(self):
        self.grid_pair(
            "八、结果图表：L2（428–473 lx）",
            (FIG / "L2_21_1_v23.png", 0.9, "L2 · 21 cm/s：20.82（−0.9%），失败率 0.0%"),
            (FIG / "L2_31_1_v23.png", 17.1, "L2 · 31 cm/s：30.59（−1.3%），失败率 0.0%"),
            "L2 两个速度的四宫格。")

    def grids_l3(self):
        self.grid_pair(
            "八、结果图表：L3（523–578 lx）",
            (FIG / "L3_21_1_v23.png", 0.9, "L3 · 21 cm/s：20.87（−0.6%），失败率 0.0%"),
            (FIG / "L3_31_1_v23.png", 17.1, "L3 · 31 cm/s：31.30（+1.0%），失败率 0.5%"),
            "L3 两个速度的四宫格。")

    # ---------- 九、目标达成 ----------
    def goal(self):
        s = self.new_slide("九、目标达成")
        banner(s, 0.9, 2.4, 31.9, 3.4,
               "6/6 组全部达标：速度误差最大 1.3%，检测失败率最大 1.5%",
               "E8F5E9", GREEN, GREEN, size=17)
        metric_strip(s, 0.9, 6.6, 31.9, 3.2, [
            ("≤20% → 1.3%", "指标 1：速度相对误差", GREEN),
            ("≤15% → 1.5%", "指标 2：检测失败率", GREEN),
            ("6 / 6", "组合达标", BLUE),
        ])
        accent_card(s, 0.9, 10.6, 15.4, 4.0, "指标 1 达成",
                    "三档光照、两个速度，稳态速度相对误差均在 1.3% 以内，\n远低于 20% 的验收上限。", bsize=12)
        accent_card(s, 17.4, 10.6, 15.4, 4.0, "指标 2 达成",
                    "检测失败率最高 1.5%（L1·31），其余为 0–0.5%，\n远低于 15% 的验收上限。", bsize=12)
        textbox(s, 0.9, 15.4, 31.9, 2.0,
                "口径：稳态阶段速度相对误差；失败率 = 统计窗内未检出帧 ÷ 统计窗总帧数。",
                size=10.5, color=GRAY)
        self.notes(s, "目标达成：两项指标都达标，6/6 组通过，且余量很大。")

    # ---------- 十、总结 ----------
    def conclusion(self):
        s = self.new_slide("十、总结")
        cards = [
            ("平台", "相机俯拍 + 双灯 + 桁架车\n完成搭建与标定 0.044 px"),
            ("算法", "7 步框架 + 4 点改进\n失败率 19.6% → 0%"),
            ("结果", "3 档光照 × 2 个速度\n6/6 达标，误差 ≤1.3%"),
            ("交付", "成果包：平台/标定/数据\n图表/视频/文档可复现"),
        ]
        x = 0.9
        for t_, b_ in cards:
            accent_card(s, x, 2.4, 7.6, 8.0, t_, b_, bsize=10.5)
            x += 8.2
        banner(s, 0.9, 11.0, 31.9, 2.6,
               "第二学期目标全部完成，实验平台、算法与验收数据均可复现。",
               "EAF3FB", BLUE, DARK, size=14)
        textbox(s, 0.9, 14.2, 31.9, 2.2,
                "后续：更大光照范围与更快速度的验证；黑布背景与更稳光源；长时稳定性与重复性测试。",
                size=11.5, color=GRAY)
        self.notes(s, "总结：平台、算法、结果、交付四块；目标完成，给出后续方向。")


if __name__ == "__main__":
    FinalDeck().build()
