#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激光打断口 · 拖拽版（痛点一）
用法：把 DXF / SVG / PDF 文件直接拖到这个 exe 图标上，自动完成：
    格式规范化（SVG/PDF→DXF，黑→白）→ 自动打断口 → 输出到原目录
文件名带 _3mm / _5mm 自动识别板厚，否则默认 3mm。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import normalize
from normalize import default_map, parse_map


def thickness_from_name(path):
    base = os.path.basename(path).lower()
    if "_5mm" in base:
        return 5.0
    if "_3mm" in base:
        return 3.0
    return 3.0


def process_one(f):
    f = f.strip().strip('"')
    if not os.path.isfile(f):
        print(f"[跳过] 找不到文件：{f}")
        return
    ext = os.path.splitext(f)[1].lower()
    if ext not in (".dxf", ".svg", ".pdf"):
        print(f"[跳过] 不支持的格式：{f}")
        return
    th = thickness_from_name(f)
    tab_w = 0.7 if th <= 3 else 0.6
    base = os.path.splitext(f)[0]
    print(f"\n处理：{os.path.basename(f)}（板厚 {th}mm）")

    # 1. 规范化（SVG/PDF→DXF；DXF 颜色重映射）
    norm_dxf = base + "_规范.dxf"
    import ezdxf
    from collections import Counter
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    stats = {"entities": 0, "skip_color": 0, "skip_empty": 0}
    cmap = default_map()
    if ext == ".svg":
        normalize.svg_to_dxf(f, msp, cmap, 1.0, stats)
    elif ext == ".pdf":
        normalize.pdf_to_dxf(f, msp, cmap, stats)
    else:
        src = ezdxf.readfile(f)
        normalize.remap_dxf_colors(src, msp, cmap, stats)
    if stats["entities"] == 0:
        print("  [跳过] 没有转出任何实体")
        return
    doc.saveas(norm_dxf)
    print(f"  规范化：{stats['entities']} 个实体")

    # 2. 打断口（调 auto_tab 主流程）
    import auto_tab
    out_dxf = base + "_断口.dxf"
    sys_argv_backup = sys.argv
    sys.argv = ["auto_tab.py", norm_dxf, "--thickness", str(th),
                "--tab-width", str(tab_w), "--out", out_dxf]
    try:
        auto_tab.main()
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"  [失败] 打断口退出码 {e.code}")
            return
    finally:
        sys.argv = sys_argv_backup
    print(f"  完成 → {os.path.basename(out_dxf)}")


def main():
    files = sys.argv[1:]
    if not files:
        print("把 DXF / SVG / PDF 文件拖到我身上，即可自动打断口。")
        input("按回车退出…")
        return
    for f in files:
        try:
            process_one(f)
        except Exception as e:
            print(f"[出错] {f}: {e}")
    print("\n全部完成。")
    input("按回车退出…")


if __name__ == "__main__":
    main()
