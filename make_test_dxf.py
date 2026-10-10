#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成测试 DXF：覆盖手册里的各种坑"""
import ezdxf

doc = ezdxf.new("R2010")
msp = doc.modelspace()
W, R, G = 7, 1, 3  # 白=切透 红=雕刻 绿=镂空


def rect(x, y, w, h, color):
    p = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for a, b in zip(p, p[1:] + p[:1]):
        msp.add_line(a, b, dxfattribs={"color": color})


# 1. 小方块 30x30（白）→ 应打1个
rect(0, 0, 30, 30, W)
# 2. 中矩形 80x40（白）→ 应打2个（平行边错位）
rect(50, 0, 80, 40, W)
# 3. 长条 200x30（白）→ 应打短边
rect(150, 0, 200, 30, W)
# 4. 大板 200x180（白）→ 应打3个
rect(0, 60, 200, 180, W)
# 5. 圆弧边零件：白直线+白圆弧 → 断口只打直线
msp.add_line((380, 0), (460, 0), dxfattribs={"color": W})
msp.add_line((380, 0), (380, 60), dxfattribs={"color": W})
msp.add_arc(center=(420, 60), radius=40, start_angle=180, end_angle=360,
            dxfattribs={"color": W})
msp.add_line((460, 0), (460, 60), dxfattribs={"color": W})
# 6. 红圆（雕刻，不动）、绿矩形（镂空，不动）
msp.add_circle(center=(500, 100), radius=20, dxfattribs={"color": R})
rect(540, 60, 60, 40, G)
# 7. 重复线（白）：同一条画两遍 → 应删1条
msp.add_line((620, 0), (700, 0), dxfattribs={"color": W})
msp.add_line((620, 0), (700, 0), dxfattribs={"color": W})
msp.add_line((620, 0), (620, 50), dxfattribs={"color": W})
msp.add_line((700, 0), (700, 50), dxfattribs={"color": W})
msp.add_line((620, 50), (700, 50), dxfattribs={"color": W})
# 8. 碎线 0.1mm → 应删
msp.add_line((720, 0), (720.1, 0), dxfattribs={"color": W})
# 9. 近重合分叉线：两条几乎重叠 → 应删短的
msp.add_line((740, 0), (820, 0), dxfattribs={"color": W})
msp.add_line((740, 0.15), (820, 0.15), dxfattribs={"color": W})
msp.add_line((740, 0), (740, 40), dxfattribs={"color": W})
msp.add_line((820, 0), (820, 40), dxfattribs={"color": W})
msp.add_line((740, 40), (820, 40), dxfattribs={"color": W})
# 10. 红字编号（必须原样保留输出）
msp.add_text("A-01", height=5, dxfattribs={"color": R}).set_placement((10, 280))
msp.add_mtext("零件说明", dxfattribs={"color": R}).set_location((60, 280, 0))
# 11. 间距过近：两白线间距 0.8mm → 应告警
msp.add_line((0, 320), (100, 320), dxfattribs={"color": W})
msp.add_line((0, 320.8), (100, 320.8), dxfattribs={"color": W})
# 12. 嵌套块：内块画白矩形 → 外块引用内块 → 模型空间引用外块
inner = doc.blocks.new("INNER_BLK")
for a, b in [((0, 0), (40, 0)), ((40, 0), (40, 25)),
             ((40, 25), (0, 25)), ((0, 25), (0, 0))]:
    inner.add_line(a, b, dxfattribs={"color": W})
outer = doc.blocks.new("OUTER_BLK")
outer.add_blockref("INNER_BLK", (0, 0))
msp.add_blockref("OUTER_BLK", (880, 0))
msp.add_blockref("OUTER_BLK", (880, 60))  # 插两次

doc.saveas("test_input.dxf")
print("test_input.dxf 已生成")

# 11. 样条测试图（单独文件，应触发中止）
doc2 = ezdxf.new("R2010")
m2 = doc2.modelspace()
m2.add_line((0, 0), (50, 0), dxfattribs={"color": W})
m2.add_line((50, 0), (50, 50), dxfattribs={"color": W})
m2.add_spline(fit_points=[(50, 50), (70, 70), (100, 50)], dxfattribs={"color": W})
doc2.saveas("test_spline.dxf")
print("test_spline.dxf 已生成")
