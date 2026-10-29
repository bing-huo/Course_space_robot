#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《视觉算法组》周汇报 PPT（10.30）

七个部分，标题只用四字名称（一、实验平台 … 七、后续规划），无封面、无提纲。
保留模板的院徽/院训/底栏等外围装饰。

版式：
    · 卡片 = 浅底圆角 + 左侧色条 + 标题/正文，替代原来单调的统一圆角框
    · 关键数字用「大数字卡」（30pt 数字 + 单位 + 说明）
    · 每页一条「结论横幅」，把 takeaway 单独拎出来
    · 标题 28pt 粗体；卡片标题 15pt；正文 12/12.5pt；图注 10.5pt
"""

from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Cm, Pt

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent
OUT = BASE / "视觉算法组_周汇报_10.30.pptx"
TEMPLATE = BASE / "视觉算法组10.30.pptx"

BLUE = "0D63B1"
DARK = "1F3864"
RED = "C00000"
GREEN = "2E7D32"
ORANGE = "C55A11"
GRAY = "595959"
BODY = "262626"
FONT = "微软雅黑"

CARD_FILL = "F7FAFD"
CARD_LINE = "D6E4F0"
STAT_FILL = "EAF3FB"

S_TITLE = 28
S_CARD_T = 15
S_CARD_B = 12
S_BODY = 14
S_BODY2 = 12.5
S_TABLE = 12.5
S_CAP = 10.5
LS = 1.22

DECOR = {"AutoShape 2", "Connector 3", "AutoShape 66", "AutoShape 67",
         "AutoShape 69", "Picture 68"}
DECOR |= {f"AutoShape {i}" for i in range(4, 30)}
DECOR |= {f"Connector {i}" for i in range(30, 66)}


def set_font(run, size, bold=False, color="000000", italic=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)
    run.font.name = FONT
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", FONT)


def textbox(slide, x, y, w, h, lines, size=S_BODY, bold=False, color=BODY,
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=LS, wrap=True):
    tb = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = Cm(0.12)
    tf.margin_right = Cm(0.12)
    tf.margin_top = Cm(0.04)
    tf.margin_bottom = Cm(0.04)
    if isinstance(lines, str):
        lines = [lines]
    for i, item in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        if isinstance(item, str):
            segs = [(item, size, bold, color)]
        else:
            segs = [item]
        for text, sz, bd, cl in segs:
            r = p.add_run()
            r.text = text
            set_font(r, sz, bd, cl)
    return tb


def _rect(slide, x, y, w, h, fill, line=None, rounded=True, radius=0.08):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        Cm(x), Cm(y), Cm(w), Cm(h))
    if rounded:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor.from_string(fill)
    if line:
        shp.line.color.rgb = RGBColor.from_string(line)
        shp.line.width = Pt(0.75)
    else:
        shp.line.fill.background()
    return shp


def accent_card(slide, x, y, w, h, title, body, accent=BLUE,
                tsize=S_CARD_T, bsize=S_CARD_B, fill=CARD_FILL, tcolor=DARK):
    _rect(slide, x, y, w, h, fill, CARD_LINE)
    _rect(slide, x + 0.16, y + 0.32, 0.13, h - 0.64, accent, rounded=False)
    tb = slide.shapes.add_textbox(Cm(x + 0.42), Cm(y), Cm(w - 0.55), Cm(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Cm(0.1)
    tf.margin_right = Cm(0.15)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    p.space_after = Pt(2)
    r = p.add_run(); r.text = title
    set_font(r, tsize, True, tcolor)
    for line in body.split("\n"):
        p = tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = LS
        r = p.add_run(); r.text = line
        set_font(r, bsize, False, BODY)
    return tb


def stat_card(slide, x, y, w, h, value, unit, label, accent=BLUE):
    _rect(slide, x, y, w, h, STAT_FILL, CARD_LINE)
    tb = slide.shapes.add_textbox(Cm(x + 0.2), Cm(y + 0.1), Cm(w - 0.4), Cm(h - 0.2))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Cm(0.1)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = value
    set_font(r, 30, True, accent)
    if unit:
        r = p.add_run(); r.text = "  " + unit
        set_font(r, 13, True, accent)
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    p2.space_before = Pt(2)
    r = p2.add_run(); r.text = label
    set_font(r, 11, False, GRAY)
    return tb


def metric_strip(slide, x, y, w, h, items):
    """横向指标条：items = [(value, label, color), ...]，颜色区分"""
    _rect(slide, x, y, w, h, CARD_FILL, CARD_LINE)
    n = len(items)
    seg = w / n
    for i, (value, label, color) in enumerate(items):
        if i > 0:
            _rect(slide, x + seg * i, y + 0.3, 0.03, h - 0.6, CARD_LINE, rounded=False)
        tb = slide.shapes.add_textbox(Cm(x + seg * i), Cm(y), Cm(seg), Cm(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = value
        set_font(r, 20, True, color)
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r = p2.add_run(); r.text = label
        set_font(r, 11, False, GRAY)


def banner(slide, x, y, w, h, text, fill, accent, tcolor, size=13.5):
    _rect(slide, x, y, w, h, fill, None)
    _rect(slide, x + 0.12, y + 0.28, 0.13, h - 0.56, accent, rounded=False)
    tb = slide.shapes.add_textbox(Cm(x + 0.4), Cm(y), Cm(w - 0.55), Cm(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Cm(0.1)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    p.line_spacing = LS
    r = p.add_run(); r.text = text
    set_font(r, size, True, tcolor)


def table(slide, x, y, w, h, data, col_w=None, fsize=S_TABLE, header="2F5597",
          first_col_bold=False):
    rows, cols = len(data), len(data[0])
    gt = slide.shapes.add_table(rows, cols, Cm(x), Cm(y), Cm(w), Cm(h))
    tbl = gt.table
    if col_w:
        for i, cw in enumerate(col_w):
            tbl.columns[i].width = Cm(cw)
    for r in range(rows):
        tbl.rows[r].height = Cm(h / rows)
        for c in range(cols):
            cell = tbl.cell(r, c)
            cell.text = ""
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Cm(0.15)
            cell.margin_right = Cm(0.15)
            cell.margin_top = Cm(0.03)
            cell.margin_bottom = Cm(0.03)
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if c > 0 else PP_ALIGN.LEFT
            run = p.add_run()
            run.text = str(data[r][c])
            if r == 0:
                set_font(run, fsize, True, "FFFFFF")
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(header)
            else:
                set_font(run, fsize, first_col_bold and c == 0, BODY)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(
                    "F2F2F2" if r % 2 == 0 else "FFFFFF")
    return tbl


def picture(slide, path, x, y, w, h, border=True):
    im = Image.open(path)
    ar = im.width / im.height
    if w / h > ar:
        pw, ph = h * ar, h
    else:
        pw, ph = w, w / ar
    px = x + (w - pw) / 2
    py = y + (h - ph) / 2
    pic = slide.shapes.add_picture(str(path), Cm(px), Cm(py), Cm(pw), Cm(ph))
    if border:
        pic.line.color.rgb = RGBColor.from_string("D6E4F0")
        pic.line.width = Pt(0.75)
    return pic


def arrow(slide, x, y, w=0.9, h=0.5, color=BLUE):
    shp = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Cm(x), Cm(y), Cm(w), Cm(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor.from_string(color)
    shp.line.fill.background()
    return shp


class Builder:
    def __init__(self):
        self.prs = Presentation(str(TEMPLATE))
        self.base = self.prs.slides[0]
        self.layout = self.prs.slide_masters[0].slide_layouts[6]  # BLANK

    def new_slide(self, title):
        s = self.prs.slides.add_slide(self.layout)
        for shp in list(s.shapes):
            shp._element.getparent().remove(shp._element)
        rid_map = {}
        for rid, rel in self.base.part.rels.items():
            if rel.reltype.endswith("/image"):
                rid_map[rid] = s.part.relate_to(rel.target_part, rel.reltype)
        for shp in self.base.shapes:
            if shp.name not in DECOR:
                continue
            el = copy.deepcopy(shp._element)
            for blip in el.iter(qn("a:blip")):
                old = blip.get(qn("r:embed"))
                if old in rid_map:
                    blip.set(qn("r:embed"), rid_map[old])
            s.shapes._spTree.append(el)
        textbox(s, 2.8, 0.12, 24.0, 1.05, title, size=S_TITLE, bold=True, color=BLUE,
                anchor=MSO_ANCHOR.MIDDLE)
        return s

    def notes(self, slide, text):
        slide.notes_slide.notes_text_frame.text = text

    # ---------------- 一、实验平台 ----------------
    def platform(self):
        s = self.new_slide("一、实验平台")
        metric_strip(s, 0.9, 2.4, 32.0, 2.3, [
            ("143 cm", "镜头 → 桌面", BLUE),
            ("113.5 cm", "标定面工作距离 WD", GREEN),
            ("87.2 × 69.7 cm", "视野（测量区 77×60）", ORANGE),
        ])

        data = [
            ["项目", "参数"],
            ["相机", "海康 MV-CU013-A0UC｜1280×1024｜全局快门"],
            ["镜头", "MVL-HF0828M-6MPE｜8 mm 定焦"],
            ["光源", "2 × 今能 100 W LED 工作灯（无调光）"],
            ["桁架", "底部 12 cm｜高 14 cm｜顶面 26 cm"],
            ["曝光 / 光圈 / 增益", "10 ms｜F2.8｜6 dB"],
            ["标定板", "Q12-200-15（200×200，格 15 mm）"],
        ]
        table(s, 0.9, 5.2, 16.4, 10.6, data, col_w=[5.4, 11.0], fsize=12,
              first_col_bold=True)

        picture(s, BASE / "1792846636855.jpg", 18.2, 5.2, 7.6, 5.7)
        picture(s, BASE / "1792846636840.jpg", 26.3, 5.2, 7.6, 5.7)
        textbox(s, 18.2, 11.1, 15.7, 1.4,
                "两盏工作灯分列两侧，相机三脚架固定在桌面正上方；\n"
                "地面暂用白桌，后续铺黑底布突出白色桁架。", size=S_CAP, color=GRAY)
        accent_card(s, 18.2, 12.7, 15.7, 3.4, "本阶段平台状态",
                    "相机、镜头、光源、机位已固定；曝光/光圈/增益锁定\n"
                    "标定板、桁架、小车到位", tsize=14, bsize=11.5)
        self.notes(s, "平台关键尺寸：镜头到桌面 143 cm，标定面 WD 113.5 cm，"
                      "桁架底部 12 cm、高 14 cm。")

    # ---------------- 二、相机标定 ----------------
    def calibration(self):
        s = self.new_slide("二、相机标定")
        accent_card(s, 0.9, 2.5, 15.4, 4.8, "标定板规格（Q12-200-15）",
                    "外框 200 × 200 mm，图案 180 × 135 mm\n"
                    "方格 15 mm，12 × 9 格 → OpenCV 内角点 11 × 8\n"
                    "玻璃基板，DFOPTIX")
        accent_card(s, 0.9, 7.6, 15.4, 8.3, "标定流程",
                    "① 相机固定、调焦（WD ≈ 113 cm）\n"
                    "② 标定板置于桁架顶面（跟踪面）\n"
                    "③ 采集图像，板面不反光\n"
                    "④ SB 角点检测：88 个内角点\n"
                    "⑤ RANSAC 求单应 H（cm → px）\n"
                    "⑥ 5 cm 网格叠加 + 重投影校验")
        picture(s, BASE / "fig_calib.png", 17.2, 2.5, 15.6, 10.8)
        stat_card(s, 17.2, 13.6, 7.6, 2.4, "0.042", "px", "重投影 RMS")
        textbox(s, 25.1, 13.7, 7.8, 2.2,
                "px/cm 14.67（X）/ 14.70（Y）\nWD 113.5 cm｜测量区 77 × 60 cm",
                size=S_CAP, color=GRAY, anchor=MSO_ANCHOR.MIDDLE)
        self.notes(s, "标定板内角点 11×8，88 点，RMS 0.042 px；单应把像素映射到 cm。")

    # ---------------- 三、算法移植 ----------------
    def v21(self):
        s = self.new_slide("三、算法移植")
        steps = ["相机取流", "灰度 + MOG2", "形态学 + 单轮廓", "图像矩质心", "单应 H", "差分 + αβ"]
        x = 0.9
        for i, st in enumerate(steps):
            shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(2.4), Cm(4.3), Cm(1.4))
            shp.adjustments[0] = 0.12
            shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor.from_string(STAT_FILL)
            shp.line.color.rgb = RGBColor.from_string(CARD_LINE)
            tf = shp.text_frame
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
            r = p.add_run(); r.text = st
            set_font(r, 12.5, True, DARK)
            if i < len(steps) - 1:
                arrow(s, x + 4.35, 2.83, 0.75, 0.55)
            x += 5.1
        textbox(s, 0.9, 3.95, 31.8, 0.8,
                "V2.1 = 第一学期算法直接迁移：纯 MOG2 前景 → 最大轮廓；阴影被并成前景，"
                "失败率 19.6%/36.1%、误差 −29.8%/−34.6%，不可用。",
                size=S_BODY2, color=RED, bold=True)
        picture(s, BASE / "fig_shadow.png", 0.9, 4.9, 15.0, 9.8)
        textbox(s, 0.9, 14.85, 15.0, 0.9,
                "运行画面：桁架右后方是强光投下的长阴影（MOG2 会把它当成前景）",
                size=S_CAP, color=GRAY, align=PP_ALIGN.CENTER)
        picture(s, ROOT / "第二学期/out/render_nofix/truss_21_15s_v21.png", 16.6, 4.9, 16.2, 9.8)
        textbox(s, 16.6, 14.85, 16.2, 0.9,
                "V2.1 效果：轨迹跳变、速度震荡、失败率 19.6%",
                size=S_CAP, color=GRAY, align=PP_ALIGN.CENTER)
        self.notes(s, "V2.1 失败率 19.6%/36.1%，误差 −29.8%/−34.6%，阴影是主因。")

    # ---------------- 四、算法改进（上） ----------------
    def v22(self):
        s = self.new_slide("四、算法改进")
        items = [
            ("曝光优先", "10 ms 锁定一个 100 Hz 周期，消除频闪"),
            ("亮度门限", "前景 = 运动 ∧ 够亮（桁架 177 / 阴影 <50 / 背景 83）"),
            ("自适应阈值", "中位 + 0.5×(P95 − 中位)，换光照不用改常数"),
            ("阴影检测", "MOG2 shadowThreshold 调整（辅助手段）"),
            ("灯位与遮光", "双灯对称、避免直射镜头（硬件层）"),
        ]
        y = 2.5
        for i, (t, b) in enumerate(items):
            accent_card(s, 0.9, y, 13.6, 2.3, t, b, accent=BLUE if i < 3 else ORANGE)
            y += 2.5
        textbox(s, 0.9, 15.0, 13.6, 0.7,
                "参考 codex 分支《强光目标检测与跟踪算法调研》", size=S_CAP, color=GRAY)
        picture(s, ROOT / "第二学期/out/render_nofix/truss_21_15s_v22.png", 14.9, 2.5, 14.1, 9.4)
        banner(s, 14.9, 12.3, 18.0, 3.9,
               "V2.2：固定亮度门限 100\n失败率 0%（19.6% → 0%），但速度仍偏低 11%\n"
               "21→18.6（−11.6%）｜30→26.6（−11.2%）",
               "FDECEC", RED, RED, size=12.5)
        self.notes(s, "V2.2 加固定门限：失败率 0%，但速度误差仍有 ~11%。")

    # ---------------- 四、算法改进（下） ----------------
    def v23(self):
        s = self.new_slide("四、算法改进")
        items = [
            ("自适应门限", "随画面亮度自动跟随，为 L0–L4 准备"),
            ("Alpha-Beta", "α=0.15、β=0.005，替代逐帧差分"),
            ("自动稳态窗", "目标完全在 ROI 内 + ±15% + 连续 ≥1.0 s"),
            ("逐帧日志", "记录每帧检出/面积/坐标，支撑失败率统计"),
        ]
        y = 2.5
        for i, (t, b) in enumerate(items):
            accent_card(s, 0.9, y, 12.8, 2.3, t, b)
            y += 2.5
        picture(s, ROOT / "第二学期/out/render_nofix/truss_21_15s_v23.png", 14.2, 2.5, 13.5, 9.0)
        data = [
            ["版本", "21 cm/s", "30 cm/s", "失败率"],
            ["V2.1", "14.7", "19.6", "19.6/36.1%"],
            ["V2.2", "18.6", "26.6", "0 / 0%"],
            ["V2.3", "18.9", "26.8", "0 / 0%"],
        ]
        table(s, 0.9, 13.0, 12.8, 3.4, data, col_w=[2.6, 3.0, 3.0, 4.2], fsize=11.5,
              first_col_bold=True)
        banner(s, 14.2, 13.0, 18.7, 3.4,
               "V2.2 → V2.3 只变 ≤2%：算法改进对 ~11% 误差没有影响 → 转向几何排查。",
               "FFF6D9", "BF9000", "7F6000", size=13)
        self.notes(s, "V2.3 加自适应门限/αβ/稳态窗，但相对 V2.2 只差 ≤2%，证明误差不是算法造成的。")

    # ---------------- 五、误差分析（上） ----------------
    def exclude(self):
        s = self.new_slide("五、误差分析")
        data = [
            ["可能原因", "量级", "判断"],
            ["算法差异（V2.2 vs V2.3）", "≤ 2%", "排除"],
            ["时间基准（60 vs 61 fps）", "1.7%", "排除"],
            ["标定板 / 尺度（手推 30 cm 两次差 3%）", "~5%", "量级不足"],
        ]
        table(s, 0.9, 2.5, 20.4, 4.2, data, col_w=[10.4, 4.5, 5.5], fsize=12.5,
              first_col_bold=True)
        accent_card(s, 0.9, 7.3, 20.4, 3.3, "现象",
                    "两段不同速度，测量/设定比值都是 0.894~0.900\n"
                    "→ 乘性系统偏差，不是随机误差、不是算法噪声")
        accent_card(s, 0.9, 11.1, 20.4, 4.4, "唯一剩下的几何量",
                    "标定面（板在桁架顶面）与跟踪面（可见结构）的高度差\n"
                    "→ 同一段像素位移在两个平面上代表的厘米数不同",
                    accent=ORANGE)
        stat_card(s, 22.4, 2.5, 10.4, 3.6, "0.894~0.900", "", "两段 测量/设定 比值")
        accent_card(s, 22.4, 6.6, 10.4, 8.9, "为什么先怀疑算法",
                    "V2.1 → V2.2 改门限，误差 −30% → −11%\n"
                    "V2.2 → V2.3 改门限/平滑/窗口，误差几乎不变\n"
                    "说明算法已到极限，剩余偏差与算法无关\n\n"
                    "于是回到几何：标定面在哪、跟踪面在哪？")
        self.notes(s, "先排除算法、时间、板件三类原因，误差稳定在 ~11%，指向几何。")

    # ---------------- 五、误差分析（下） ----------------
    def plane(self):
        s = self.new_slide("五、误差分析")
        textbox(s, 0.9, 2.5, 16.0, 8.6, [
            ("推导（高度差 → 比值 → 补偿）", S_CARD_T, True, DARK),
            ("r = 测量位移 / 实际位移 = WD_c / WD_t", 14, False, BODY),
            ("Δh = WD_c · (1/r − 1)", 14, False, BODY),
            ("   取 Δh = 桁架高 14 cm → r = 113.5/127.5 ≈ 0.89", 14, False, BODY),
            ("   实测 r = 18.89/21 = 0.900，26.83/30 = 0.894", 12, False, GRAY),
        ], spacing=1.35)
        stat_card(s, 0.9, 7.0, 7.6, 3.0, "14.0", "cm", "高度差 Δh（= 桁架高）", accent=RED)
        accent_card(s, 8.9, 7.0, 8.0, 3.0, "产生原因",
                    "板在顶面，俯视看穿镂空\n可见结构以底部为主\n→ 等效平面接近底部",
                    accent=ORANGE, tsize=13.5, bsize=11)
        banner(s, 0.9, 10.6, 16.0, 2.2,
               "补偿 k = (113.5+14)/113.5 = 1.1233", "E9F5E9", GREEN, GREEN, size=13)
        textbox(s, 0.9, 13.2, 16.0, 2.6, [
            ("补偿后：21 → 21.11（+0.5%）｜30 → 29.60（−1.3%）", 14, True, GREEN),
            ("两段同时对上，一个参数解释了全部系统偏差", S_BODY2, False, GRAY),
        ], spacing=1.2)
        picture(s, BASE / "fig_plane_error.png", 17.2, 2.5, 15.6, 11.0)
        textbox(s, 17.2, 13.8, 15.6, 1.6,
                "同一段位移，两个高度的平面差 Δh，造成速度按 WD_c/WD_t 成比例偏小。",
                size=S_CAP, color=GRAY)
        self.notes(s, "Δh 取桁架高 14 cm；实测 r≈0.894~0.900 与预测 0.89 一致；补偿后 +0.5%/−1.3%。")

    # ---------------- 六、初步成果 ----------------
    def results(self):
        s = self.new_slide("六、初步成果")
        picture(s, ROOT / "第二学期/out/render/truss_21_15s_v23.png", 0.9, 2.4, 15.6, 9.9)
        picture(s, ROOT / "第二学期/out/render/truss_30_15s_v23.png", 17.3, 2.4, 15.6, 9.9)
        textbox(s, 0.9, 12.45, 15.6, 0.7, "21 cm/s：实测 21.11，误差 +0.5%",
                size=13, color=GREEN, align=PP_ALIGN.CENTER)
        textbox(s, 17.3, 12.45, 15.6, 0.7, "30 cm/s：实测 29.60，误差 −1.3%",
                size=13, color=GREEN, align=PP_ALIGN.CENTER)
        data = [
            ["工况", "目标", "实测", "误差", "失败率", "判定"],
            ["第一段", "21 cm/s", "21.11", "+0.5%", "0%", "达标"],
            ["第二段", "30 cm/s", "29.60", "−1.3%", "0%", "达标"],
        ]
        table(s, 0.9, 13.5, 31.9, 2.5, data, col_w=[3.6, 4.4, 4.4, 4.4, 4.4, 10.7],
              fsize=12.5, first_col_bold=True)
        self.notes(s, "修正后 21→21.11（+0.5%）、30→29.60（−1.3%），失败率 0%；两项指标均达标。")

    # ---------------- 七、后续规划 ----------------
    def future(self):
        s = self.new_slide("七、后续规划")
        items = [
            ("多光照等级", "L0–L4，双灯到区域中心\n距离分级，记录灯位与参数"),
            ("重复采集", "每档 3 次\n保证结果可复现"),
            ("退化分析", "速度误差 / 失败率\n随光照等级的退化曲线"),
            ("成果整理", "报告、代码、数据、演示\n形成本学期完整交付"),
        ]
        x = 0.9
        for i, (t, b) in enumerate(items):
            num = f"0{i+1}"
            card_x = x
            accent_card(s, card_x, 2.7, 7.2, 4.5, f"{num}  {t}", b)
            x += 8.1
            if i < len(items) - 1:
                arrow(s, card_x + 7.25, 4.65, 0.8, 0.55)
        accent_card(s, 0.9, 7.9, 16.0, 4.5, "近期动作",
                    "黑布到位后重标（背景变黑）\n"
                    "→ 实时版 main_v2\n"
                    "→ L0–L4 十组正式实验")
        accent_card(s, 17.3, 7.9, 15.6, 4.5, "验收口径",
                    "指标 1：强光（L2）下稳态速度相对误差 ≤20%\n"
                    "指标 2：检测失败率 ≤15%（L0–L2）\n"
                    "L3/L4 只记录现象、不参与判定", accent=GREEN)
        banner(s, 0.9, 12.9, 32.0, 2.4,
               "本周：相机标定 + 三版算法迁移/改进 + 等效平面误差定位与补偿；下周进入多光照等级实验。",
               "E9F5E9", GREEN, GREEN, size=13)
        self.notes(s, "后续：多光照等级实验、重复采集、退化曲线、成果整理。")

    def build(self):
        self.platform()
        self.calibration()
        self.v21()
        self.v22()
        self.v23()
        self.exclude()
        self.plane()
        self.results()
        self.future()
        sldIdLst = self.prs.slides._sldIdLst
        for sldId in list(sldIdLst)[:7]:
            rId = sldId.get(qn("r:id"))
            self.prs.part.drop_rel(rId)
            sldIdLst.remove(sldId)
        self.prs.save(str(OUT))
        print(f"saved {OUT} slides={len(self.prs.slides)}")


if __name__ == "__main__":
    Builder().build()
