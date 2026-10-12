#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键规范化（痛点二）：SVG / PDF / DXF → 颜色规范的 DXF，再进 auto_tab 打断口。

默认颜色映射：黑色 → 白色(切透, ACI 7)。
AI(Illustrator) 导出的图经常是黑线，激光要的是白线切透，一键改完。

用法：
    python normalize.py 输入.svg --out 规范.dxf
    python normalize.py 输入.pdf --out 规范.dxf
    python normalize.py 输入.dxf --out 规范.dxf --map black:white,blue:white
"""
import argparse
import math
import os
import sys

import ezdxf

ACI_WHITE = 7

# 颜色名 → RGB
NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128),
}
ACI_BY_NAME = {"white": 7, "red": 1, "green": 3, "yellow": 2, "cyan": 4,
               "blue": 5, "magenta": 6, "black": 7, "gray": 8, "grey": 8}


def parse_map(s):
    """'black:white,blue:white' → {src_rgb: aci}，只支持黑/白/红/绿/蓝等常用名"""
    m = {}
    if not s:
        return m
    for pair in s.split(","):
        if ":" not in pair:
            continue
        src, dst = pair.strip().split(":", 1)
        src, dst = src.strip().lower(), dst.strip().lower()
        if src in NAMED and dst in ACI_BY_NAME:
            m[NAMED[src]] = ACI_BY_NAME[dst]
    return m


def default_map():
    return {(0, 0, 0): ACI_WHITE}


def svg_color_to_rgb(stroke):
    if not stroke or stroke == "none":
        return None
    s = stroke.strip().lower()
    if s in NAMED:
        return NAMED[s]
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            try:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                return None
    return None


def rgb_near(a, b, tol=30):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def map_rgb(rgb, cmap):
    if rgb is None:
        return None
    for src, aci in cmap.items():
        if rgb_near(rgb, src):
            return aci
    return None


def add_polyline(msp, pts, aci):
    if len(pts) < 2:
        return
    if aci is None:
        aci = ACI_WHITE
    pl = msp.add_lwpolyline([(p[0], p[1]) for p in pts],
                            dxfattribs={"color": aci})
    if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        pl.closed = True


def svg_to_dxf(path, msp, cmap, scale, stats):
    from svgpathtools import svg2paths2, Line
    paths, attrs, _ = svg2paths2(path)
    for p, attr in zip(paths, attrs):
        rgb = svg_color_to_rgb(attr.get("stroke", "black"))
        aci = map_rgb(rgb, cmap)
        if aci is None:
            # 非映射颜色：黑线默认也进白（AI 图常见），其余跳过
            aci = ACI_WHITE if (rgb and rgb_near(rgb, (0, 0, 0))) else None
            if aci is None:
                stats["skip_color"] += 1
                continue
        pts = []
        for seg in p:
            if isinstance(seg, Line):
                # 直线：只取端点，不切分（切分会破坏断口算法的整边识别）
                seg_pts = [(seg.start.real * scale, seg.start.imag * scale),
                           (seg.end.real * scale, seg.end.imag * scale)]
            else:
                # 曲线：按长度采样
                try:
                    L = seg.length()
                except Exception:
                    L = 0
                n = max(2, min(64, int(L / 2) + 2))
                seg_pts = []
                for i in range(n + 1):
                    try:
                        z = seg.point(i / n)
                        seg_pts.append((z.real * scale, z.imag * scale))
                    except Exception:
                        break
            if not seg_pts:
                continue
            if pts and seg_pts:
                # 连续段首尾相接则合并
                if math.hypot(pts[-1][0] - seg_pts[0][0],
                              pts[-1][1] - seg_pts[0][1]) < 1e-6:
                    seg_pts = seg_pts[1:]
            pts.extend(seg_pts)
        if len(pts) >= 2:
            add_polyline(msp, pts, aci)
            stats["entities"] += 1
        else:
            stats["skip_empty"] += 1


def pdf_to_dxf(path, msp, cmap, stats):
    import pymupdf
    doc = pymupdf.open(path)
    PT2MM = 25.4 / 72.0
    for page in doc:
        for d in page.get_drawings():
            col = d.get("color")
            rgb = None
            if col:
                rgb = tuple(int(round(c * 255)) for c in col[:3])
            aci = map_rgb(rgb, cmap)
            if aci is None:
                stats["skip_color"] += 1
                continue
            for item in d["items"]:
                kind = item[0]
                pts = []
                if kind == "l":
                    pts = [(item[1].x * PT2MM, item[1].y * PT2MM),
                           (item[2].x * PT2MM, item[2].y * PT2MM)]
                elif kind == "c":
                    # 贝塞尔曲线采样
                    p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
                    for i in range(17):
                        t = i / 16
                        mt = 1 - t
                        x = (mt**3 * p0.x + 3 * mt**2 * t * p1.x +
                             3 * mt * t**2 * p2.x + t**3 * p3.x) * PT2MM
                        y = (mt**3 * p0.y + 3 * mt**2 * t * p1.y +
                             3 * mt * t**2 * p2.y + t**3 * p3.y) * PT2MM
                        pts.append((x, y))
                elif kind == "re":
                    r = item[1]
                    x0, y0 = r.x0 * PT2MM, r.y0 * PT2MM
                    x1, y1 = r.x1 * PT2MM, r.y1 * PT2MM
                    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                if len(pts) >= 2:
                    add_polyline(msp, pts, aci)
                    stats["entities"] += 1
    doc.close()


def remap_dxf_colors(src_doc, msp, cmap, stats):
    """DXF → DXF：只做颜色映射（AI 导出的 DXF 颜色不对时用）"""
    for e in src_doc.modelspace():
        t = e.dxftype()
        if t not in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "POLYLINE"):
            continue
        # 取源颜色
        rgb = None
        aci_src = None
        try:
            tc = e.dxf.get("true_color", None)
            if tc:
                v = int(tc)
                rgb = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
            else:
                aci_src = int(e.dxf.get("color", 256))
                if aci_src == 1:
                    rgb = (255, 0, 0)
                elif aci_src == 7:
                    rgb = (255, 255, 255)
                elif aci_src in (0, 8, 9, 250, 251, 252, 253, 254):
                    rgb = (0, 0, 0)
        except Exception:
            pass
        aci = map_rgb(rgb, cmap)
        if aci is None:
            # 保持原样
            try:
                aci = aci_src if aci_src not in (None, 256, 0) else 7
            except Exception:
                aci = 7
        try:
            if t == "LINE":
                msp.add_line((e.dxf.start.x, e.dxf.start.y),
                             (e.dxf.end.x, e.dxf.end.y),
                             dxfattribs={"color": aci})
            elif t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                pl = msp.add_lwpolyline(pts, dxfattribs={"color": aci})
                pl.closed = e.closed
            elif t == "ARC":
                msp.add_arc(center=(e.dxf.center.x, e.dxf.center.y),
                            radius=e.dxf.radius,
                            start_angle=e.dxf.start_angle,
                            end_angle=e.dxf.end_angle,
                            dxfattribs={"color": aci})
            elif t == "CIRCLE":
                msp.add_circle(center=(e.dxf.center.x, e.dxf.center.y),
                               radius=e.dxf.radius, dxfattribs={"color": aci})
            elif t == "POLYLINE":
                pts = [(float(v.dxf.location.x), float(v.dxf.location.y))
                       for v in e.vertices]
                if len(pts) >= 2:
                    pl = msp.add_lwpolyline(pts, dxfattribs={"color": aci})
                    try:
                        pl.closed = bool(e.is_closed)
                    except Exception:
                        pass
            stats["entities"] += 1
        except Exception:
            stats["skip_empty"] += 1


def main():
    ap = argparse.ArgumentParser(description="一键规范化：SVG/PDF/DXF → 规范颜色DXF")
    ap.add_argument("input", help="输入文件 (.svg/.pdf/.dxf)")
    ap.add_argument("--out", help="输出 DXF（默认 输入_规范.dxf）")
    ap.add_argument("--map", default="",
                    help="颜色映射，如 black:white,blue:white（默认 black:white）")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="SVG 缩放（SVG单位→mm，默认1）")
    a = ap.parse_args()

    ext = os.path.splitext(a.input)[1].lower()
    out = a.out or os.path.splitext(a.input)[0] + "_规范.dxf"
    cmap = default_map()
    cmap.update(parse_map(a.map))

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    stats = {"entities": 0, "skip_color": 0, "skip_empty": 0}

    if ext == ".svg":
        svg_to_dxf(a.input, msp, cmap, a.scale, stats)
    elif ext == ".pdf":
        pdf_to_dxf(a.input, msp, cmap, stats)
    elif ext == ".dxf":
        src = ezdxf.readfile(a.input)
        remap_dxf_colors(src, msp, cmap, stats)
    else:
        print(f"不支持的格式：{ext}（支持 .svg/.pdf/.dxf）")
        sys.exit(1)

    doc.saveas(out)
    print(f"输入：{a.input}")
    print(f"  转出实体 {stats['entities']} 个，跳过非映射颜色 {stats['skip_color']} 个")
    print(f"输出：{out}")


if __name__ == "__main__":
    main()
