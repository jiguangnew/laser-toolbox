#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_tab.py —— 激光切割图自动打断口（微连接）v1.0
依据《断口实战手册》v1.0 实现。

流程：炸开块引用 → 清重复线/碎线/样条检查 → 颜色规范校验 → 按规则打断口 → 输出DXF + 复核图

用法：
    python3 auto_tab.py 输入.dxf --thickness 3
    python3 auto_tab.py 输入.dxf --thickness 5 --out 输出.dxf
    python3 auto_tab.py 输入.dxf --tab-width 0.8          # 非常规厚度时手动指定断口宽度

颜色规范（ACI色号）：白=7（切透，打断口）/ 红=1（雕刻划痕，不动）/ 绿=3（镂空，不动）
"""
import argparse
import math
import os
import sys
from collections import defaultdict

import ezdxf
from ezdxf.math import Matrix44, Vec3

# ---------------- 常量 ----------------
ACI_WHITE, ACI_RED, ACI_GREEN = 7, 1, 3
BYLAYER = 256
TAB_WIDTH_TABLE = {3: 0.7, 5: 0.6}   # 板厚(mm) -> 断口宽度(mm)，手册实测值
EPS = 1e-6
DUP_TOL = 0.05          # 重复线判定：端点距离容差(mm)
NEAR_TOL = 0.30         # 近重合线判定：平行且间距容差(mm)
TINY_LEN = 0.30         # 碎线：短于此长度直接删(mm)
MIN_TAB_SEG = 8.0       # 能打断口的最短直线段(mm)
SMALL_PART = 50.0       # <50mm 算小图
BIG_PART = 150.0        # >=150mm 算大图


class Issue:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warn(self, msg):
        self.warnings.append(msg)

    def err(self, msg):
        self.errors.append(msg)

    def report(self):
        for w in self.warnings:
            print(f"  [警告] {w}")
        for e in self.errors:
            print(f"  [错误] {e}")


# ---------------- 颜色 ----------------
def resolve_color(doc, e):
    """返回实体的 ACI 色号（BYLAYER 时取图层色）"""
    c = e.dxf.get("color", BYLAYER)
    if c == BYLAYER:
        try:
            return doc.layers.get(e.dxf.layer).color
        except Exception:
            return ACI_WHITE
    if c == 0:  # BYBLOCK
        return ACI_WHITE
    return c


# ---------------- 炸开块引用 ----------------
def explode_inserts(doc, msp, issue):
    """递归炸开所有 INSERT（含嵌套），变换矩阵逐层累乘。返回新增实体数。"""
    count = [0]

    def collect(insert, matrix):
        try:
            blk = doc.blocks.get(insert.dxf.name)
        except Exception:
            issue.warn(f"块 '{insert.dxf.name}' 定义缺失，跳过")
            return
        m = matrix * insert.matrix44()
        for be in blk:
            t = be.dxftype()
            if t == "INSERT":
                collect(be, m)
            elif t in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE"):
                try:
                    ne = be.copy()
                    ne.transform(m)
                    # 炸开后颜色/图层继承宿主 INSERT 的显式设置
                    if insert.dxf.get("color", BYLAYER) not in (BYLAYER, 0):
                        ne.dxf.color = insert.dxf.color
                    msp.add_entity(ne)
                    count[0] += 1
                except Exception as ex:
                    issue.warn(f"炸开块内实体失败 ({t}): {ex}")
            # 块内其他类型忽略

    inserts = [e for e in msp if e.dxftype() == "INSERT"]
    for ins in inserts:
        collect(ins, Matrix44())
        msp.delete_entity(ins)
    return count[0], len(inserts)


# ---------------- 几何 ----------------
def seg_len(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def seg_key(p1, p2):
    """端点无序归一化 key，用于判重"""
    a = (round(p1[0] / DUP_TOL), round(p1[1] / DUP_TOL))
    b = (round(p2[0] / DUP_TOL), round(p2[1] / DUP_TOL))
    return (a, b) if a <= b else (b, a)


def extract_segments(doc, msp, issue):
    """
    把 LINE / LWPOLYLINE(直线段) 抽成线段表；ARC/CIRCLE/LWPOLYLINE圆弧段记为 curved；
    SPLINE 只记录问题（手册：不许用样条）。
    返回 (segments, curved, stats)
    segment: dict(p1, p2, color, src)
    curved:  dict(kind, color, entity) 原样保留输出
    """
    segments, curved, texts = [], [], []
    stats = defaultdict(int)
    for e in list(msp):
        t = e.dxftype()
        color = resolve_color(doc, e)
        if t == "LINE":
            p1 = (e.dxf.start.x, e.dxf.start.y)
            p2 = (e.dxf.end.x, e.dxf.end.y)
            segments.append(dict(p1=p1, p2=p2, color=color, src=t))
            stats["LINE"] += 1
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyb"))
            closed = e.closed
            n = len(pts)
            if n < 2:
                continue
            rng = range(n) if closed else range(n - 1)
            for i in rng:
                x1, y1, b1 = pts[i][0], pts[i][1], pts[i][2]
                x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
                if abs(b1) > 1e-9:
                    curved.append(dict(kind="arc_seg", color=color, entity=e, idx=i))
                    stats["LWP_ARC"] += 1
                else:
                    segments.append(dict(p1=(x1, y1), p2=(x2, y2), color=color, src="LWPOLYLINE"))
                    stats["LWP_LINE"] += 1
        elif t in ("ARC", "CIRCLE"):
            curved.append(dict(kind=t.lower(), color=color, entity=e))
            stats[t] += 1
        elif t == "POLYLINE":
            issue.warn("发现 POLYLINE（3D多段线），已跳过，请转成 LWPOLYLINE")
            stats["POLYLINE_SKIP"] += 1
        elif t == "SPLINE":
            issue.err("发现 SPLINE 样条曲线（手册禁止）：请在 CAD 里重画为直线/圆弧后再跑")
            stats["SPLINE"] += 1
        elif t in ("TEXT", "MTEXT"):
            # 编号文字：不断口，但必须原样保留（红字丢了客户没法拼装）
            texts.append(e)
            stats[t] += 1
        # INSERT 应已在之前炸开；其他类型忽略
    return segments, curved, texts, stats


def dedup_and_clean(segments, issue):
    """删重复线、碎线；检测近重合/分叉线。返回 (cleaned, removed_dup, removed_tiny, near_list)"""
    seen, cleaned = {}, []
    removed_dup = 0
    for s in segments:
        if seg_len(s["p1"], s["p2"]) < TINY_LEN:
            continue  # 碎线直接删，稍后统一计数
        k = seg_key(s["p1"], s["p2"])
        if k in seen:
            removed_dup += 1
            continue
        seen[k] = True
        cleaned.append(s)
    removed_tiny = len(segments) - len(cleaned) - removed_dup

    # 近重合/分叉检测：平行、间距小、投影重叠
    near = []
    n = len(cleaned)
    for i in range(n):
        p1, p2 = cleaned[i]["p1"], cleaned[i]["p2"]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.hypot(dx, dy)
        if L < EPS:
            continue
        ux, uy = dx / L, dy / L
        for j in range(i + 1, n):
            q1, q2 = cleaned[j]["p1"], cleaned[j]["p2"]
            ex, ey = q2[0] - q1[0], q2[1] - q1[1]
            L2 = math.hypot(ex, ey)
            if L2 < EPS:
                continue
            vx, vy = ex / L2, ey / L2
            if abs(ux * vy - uy * vx) > 0.02:  # 不平行
                continue
            dist = abs((q1[0] - p1[0]) * uy - (q1[1] - p1[1]) * ux)
            if dist > NEAR_TOL or dist < 1e-9:
                continue
            # 投影重叠
            def proj(p):
                return (p[0] - p1[0]) * ux + (p[1] - p1[1]) * uy
            a1, a2 = sorted([proj(q1), proj(q2)])
            overlap = min(a2, L) - max(a1, 0)
            if overlap > 0.5 * min(L, L2):
                near.append((i, j, round(dist, 3)))
    # 自动删除近重合线中较短的那条（手册：该删就删），保留记录
    to_del = set()
    for i, j, d in near:
        li = seg_len(cleaned[i]["p1"], cleaned[i]["p2"])
        lj = seg_len(cleaned[j]["p1"], cleaned[j]["p2"])
        to_del.add(j if lj <= li else i)
    final = [s for k, s in enumerate(cleaned) if k not in to_del]
    if to_del:
        issue.warn(f"删除 {len(to_del)} 条近重合/分叉线（间距<{NEAR_TOL}mm，会走两遍）")
    return final, removed_dup, removed_tiny, near


def seg_dist(p1, p2, q1, q2):
    """两线段最短距离"""
    def pt_seg(p, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2 if L2 > EPS else 0
        t = max(0, min(1, t))
        return math.hypot(p[0] - (a[0] + vx * t), p[1] - (a[1] + vy * t))
    return min(pt_seg(p1, q1, q2), pt_seg(p2, q1, q2),
               pt_seg(q1, p1, p2), pt_seg(q2, p1, p2))


def check_spacing(white_segs, issue, min_gap=1.2):
    """白线之间间距 <1.2mm 告警（低于此值两条线会连到一起）。相连的线段不算。"""
    bad = 0
    n = len(white_segs)
    for i in range(n):
        p1, p2 = white_segs[i]["p1"], white_segs[i]["p2"]
        for j in range(i + 1, n):
            q1, q2 = white_segs[j]["p1"], white_segs[j]["p2"]
            # 共端点 = 同一轮廓相连，跳过
            if any(math.hypot(a[0] - b[0], a[1] - b[1]) < 0.5
                   for a in (p1, p2) for b in (q1, q2)):
                continue
            if seg_dist(p1, p2, q1, q2) < min_gap:
                bad += 1
    if bad:
        issue.warn(f"发现 {bad} 处白线间距 <{min_gap}mm（低于此值切割时会连到一起），请检查排版")
    return bad


def check_colors(doc, msp, segments, curved, issue):
    """颜色规范校验：必须有白线；红/绿只统计不动。"""
    from collections import Counter
    c = Counter()
    for s in segments:
        c[s["color"]] += 1
    for cu in curved:
        c[cu["color"]] += 1
    n_white = c.get(ACI_WHITE, 0)
    n_red = c.get(ACI_RED, 0)
    n_green = c.get(ACI_GREEN, 0)
    n_other = sum(v for k, v in c.items() if k not in (ACI_WHITE, ACI_RED, ACI_GREEN))
    if n_white == 0:
        issue.err("没有找到白色(切透)线条，无断口可打")
    if n_other:
        issue.warn(f"发现 {n_other} 条非规范颜色线条（非红/白/绿），已忽略（不断口）")
    print(f"  颜色统计：白(切透)={n_white} 红(雕刻)={n_red} 绿(镂空)={n_green} 其他={n_other}")
    return n_white > 0

# ---------------- 打断口规则引擎 ----------------
def group_parts(white_segs, tol=0.5):
    """按端点连通性把白线分成零件（并查集）"""
    parent = list(range(len(white_segs)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pts = []
    for s in white_segs:
        pts.append(s["p1"]); pts.append(s["p2"])
    for i in range(len(white_segs)):
        for j in range(i + 1, len(white_segs)):
            si, sj = white_segs[i], white_segs[j]
            close = any(
                math.hypot(a[0] - b[0], a[1] - b[1]) < tol
                for a in (si["p1"], si["p2"]) for b in (sj["p1"], sj["p2"]))
            if close:
                union(i, j)
    groups = defaultdict(list)
    for i in range(len(white_segs)):
        groups[find(i)].append(i)
    return list(groups.values())


def part_bbox(white_segs, idxs):
    xs = [white_segs[i][k][0] for i in idxs for k in ("p1", "p2")]
    ys = [white_segs[i][k][1] for i in idxs for k in ("p1", "p2")]
    return (min(xs), min(ys), max(xs), max(ys))


def seg_dir(s):
    dx = s["p2"][0] - s["p1"][0]
    dy = s["p2"][1] - s["p1"][1]
    L = math.hypot(dx, dy)
    return (dx / L, dy / L, L) if L > EPS else (1, 0, 0)


def find_parallel_pair(white_segs, idxs):
    """找最长的一对平行边（用于错位打法）。返回 (i, j) 或 None"""
    best, best_score = None, 0
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            i, j = idxs[a], idxs[b]
            ux, uy, L1 = seg_dir(white_segs[i])
            vx, vy, L2 = seg_dir(white_segs[j])
            if abs(ux * vy - uy * vx) > 0.05:  # 不平行
                continue
            if min(L1, L2) / max(L1, L2) < 0.6:
                continue
            p1 = white_segs[i]["p1"]
            q1 = white_segs[j]["p1"]
            dist = abs((q1[0] - p1[0]) * uy - (q1[1] - p1[1]) * ux)
            if dist > 25 or dist < 0.5:
                continue
            def proj(p):
                return (p[0] - p1[0]) * ux + (p[1] - p1[1]) * uy
            a1, a2 = sorted([proj(q1), proj(white_segs[j]["p2"])])
            overlap = min(a2, L1) - max(a1, 0)
            if overlap < 0.4 * min(L1, L2):
                continue
            score = L1 + L2
            if score > best_score:
                best, best_score = (i, j), score
    return best


def plan_tabs(white_segs, idxs, tab_width, issue):
    """
    给一个零件规划断口。返回 [(seg_idx, t_frac), ...]，t_frac 为线段上的比例位置。
    规则（手册）：
      小图(<50mm): 1个，打最长直线中点
      中图(50~150mm): 2个，左右各一；有平行边则错位(1/3 & 2/3)
      大图(>=150mm): 3个
      长条形(长宽比>3): 打两侧短边，不打长边
    只打直线段中点附近，避开端点 tab_width 范围；圆弧不打（已在 curved 中分离）。
    """
    # 候选：够长的直线段
    cands = []
    for i in idxs:
        L = seg_len(white_segs[i]["p1"], white_segs[i]["p2"])
        if L >= MIN_TAB_SEG:
            cands.append((L, i))
    cands.sort(reverse=True)
    if not cands:
        return []
    x0, y0, x1, y1 = part_bbox(white_segs, idxs)
    w, h = x1 - x0, y1 - y0
    maxdim, mindim = max(w, h), min(w, h)
    aspect = maxdim / mindim if mindim > EPS else 99

    def ok(seg_idx, t):
        L = seg_len(white_segs[seg_idx]["p1"], white_segs[seg_idx]["p2"])
        d = t * L
        return d >= tab_width * 1.2 and (L - d) >= tab_width * 1.2

    plans = []
    # 退化情况：单条孤线 / 零高度 bbox，不按长条形处理
    degenerate = len(idxs) == 1 or mindim < 1.0
    is_strip = (not degenerate) and aspect > 3 and maxdim >= SMALL_PART

    def generic_on_longest(n_tabs):
        """在最长边上按数量打（兜底）"""
        out = []
        i = cands[0][1]
        if n_tabs == 1:
            ts = [0.5]
        elif n_tabs == 2:
            ts = [1/3, 2/3]
        else:
            ts = [0.25, 0.5, 0.75]
        for t in ts:
            if ok(i, t):
                out.append((i, t))
        return out

    if degenerate:
        plans = generic_on_longest(1 if maxdim < SMALL_PART else 2)
        return plans

    if is_strip:
        # 长条形：找短边（方向与最长边垂直的段）
        ux, uy, _ = seg_dir(white_segs[cands[0][1]])
        short_edges = []
        for L, i in cands:
            vx, vy, _ = seg_dir(white_segs[i])
            if abs(ux * vx + uy * vy) < 0.35:  # 近似垂直
                short_edges.append((L, i))
        short_edges.sort(reverse=True)
        for L, i in short_edges[:2]:
            if ok(i, 0.5):
                plans.append((i, 0.5))
        if len(plans) < 2:  # 短边不够长，退回长边错位打
            pair = find_parallel_pair(white_segs, idxs)
            if pair and ok(pair[0], 1/3) and ok(pair[1], 2/3):
                plans = [(pair[0], 1/3), (pair[1], 2/3)]
            else:
                plans = generic_on_longest(2)  # 实在没辙，在最长边上打2个
    elif maxdim < SMALL_PART:
        i = cands[0][1]
        if ok(i, 0.5):
            plans.append((i, 0.5))
    elif maxdim < BIG_PART:
        pair = find_parallel_pair(white_segs, idxs)
        if pair and ok(pair[0], 1/3) and ok(pair[1], 2/3):
            plans = [(pair[0], 1/3), (pair[1], 2/3)]  # 错位打法
        else:
            for L, i in cands[:2]:
                if ok(i, 0.5):
                    plans.append((i, 0.5))
    else:
        pair = find_parallel_pair(white_segs, idxs)
        if pair and ok(pair[0], 1/3) and ok(pair[1], 2/3):
            plans = [(pair[0], 1/3), (pair[1], 2/3)]
        else:
            for L, i in cands[:2]:
                if ok(i, 0.5):
                    plans.append((i, 0.5))
        # 第三个：最长边上再补一个（与已打点错开）
        used = {p[0] for p in plans}
        for L, i in cands:
            if i in used:
                continue
            if ok(i, 0.5):
                plans.append((i, 0.5))
                break
        if len(plans) == 2:  # 实在没第三条边，长边打双断口
            i = cands[0][1]
            if ok(i, 0.3) and ok(i, 0.7):
                plans = [(i, 0.3), (i, 0.7)]
                if pair:
                    plans.append((pair[1], 0.5))
    return plans


def apply_tabs(white_segs, plans, tab_width):
    """在线段上切出断口缺口：一条线段 -> 两条线段，中间留 tab_width 缺口。返回 (new_segs, tab_marks)。"""
    by_seg = defaultdict(list)
    for seg_idx, t in plans:
        by_seg[seg_idx].append(t)
    new_segs, tab_marks = [], []
    for idx, s in enumerate(white_segs):
        ts = sorted(by_seg.get(idx, []))
        if not ts:
            new_segs.append(s)
            continue
        p1, p2 = s["p1"], s["p2"]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        cuts = []  # 缺口区间（沿线距离）
        for t in ts:
            c = t * L
            cuts.append((c - tab_width / 2, c + tab_width / 2))
            tab_marks.append((p1[0] + ux * c, p1[1] + uy * c))
        cuts.sort()
        # 区间合并（防止重叠）
        merged = []
        for a, b in cuts:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        prev = 0.0
        for a, b in merged:
            if a - prev > 0.01:
                new_segs.append(dict(
                    p1=(p1[0] + ux * prev, p1[1] + uy * prev),
                    p2=(p1[0] + ux * a, p1[1] + uy * a),
                    color=s["color"], src=s["src"]))
            prev = b
        if L - prev > 0.01:
            new_segs.append(dict(
                p1=(p1[0] + ux * prev, p1[1] + uy * prev),
                p2=p2, color=s["color"], src=s["src"]))
    return new_segs, tab_marks

# ---------------- 输出 DXF ----------------
def copy_curved(msp, item):
    """把 curved 条目原样写回新图"""
    e, color = item["entity"], item["color"]
    t = e.dxftype()
    try:
        if t == "ARC":
            msp.add_arc(
                center=(e.dxf.center.x, e.dxf.center.y),
                radius=e.dxf.radius,
                start_angle=e.dxf.start_angle,
                end_angle=e.dxf.end_angle,
                dxfattribs={"color": color},
            )
        elif t == "CIRCLE":
            msp.add_circle(
                center=(e.dxf.center.x, e.dxf.center.y),
                radius=e.dxf.radius,
                dxfattribs={"color": color},
            )
        elif t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            pl = msp.add_lwpolyline(pts, dxfattribs={"color": color})
            pl.closed = e.closed
    except Exception:
        pass


def copy_text(msp, e):
    """TEXT/MTEXT 原样重建（内容/位置/高度/颜色/图层），跨 doc 安全复制"""
    t = e.dxftype()
    color = e.dxf.get("color", ACI_RED)
    layer = e.dxf.get("layer", "0")
    try:
        if t == "TEXT":
            msp.add_text(
                e.dxf.text,
                height=e.dxf.get("height", 2.5),
                dxfattribs={"color": color, "layer": layer,
                            "rotation": e.dxf.get("rotation", 0)},
            ).set_placement((e.dxf.insert.x, e.dxf.insert.y),
                            align=e.dxf.get("halign", 0) and "LEFT" or "LEFT")
        else:
            msp.add_mtext(
                e.text,
                dxfattribs={"color": color, "layer": layer},
            ).set_location((e.dxf.insert.x, e.dxf.insert.y, 0),
                           attachment_point=e.dxf.get("attachment_point", 1))
            msp[-1].dxf.char_height = e.dxf.get("char_height", 2.5)
    except Exception:
        pass


def build_output(white_segs_new, other_segs, curved, texts, tab_width):
    out = ezdxf.new("R2010")
    msp = out.modelspace()
    for s in white_segs_new:
        msp.add_line(s["p1"], s["p2"], dxfattribs={"color": ACI_WHITE})
    for s in other_segs:
        msp.add_line(s["p1"], s["p2"], dxfattribs={"color": s["color"]})
    seen = set()
    for cu in curved:
        eid = id(cu["entity"])
        if eid in seen:
            continue
        seen.add(eid)
        copy_curved(msp, cu)
    for t in texts:
        copy_text(msp, t)
    return out


# ---------------- 复核图 ----------------
def draw_review(out_base, white_segs, other_segs, curved, tab_marks, stats):
    """输出整板复核图 + 断口局部放大图（英文标注，避开中文字体问题）"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    def draw_ax(ax, segs_w, segs_o, marks, window=None):
        if segs_w:
            ax.add_collection(LineCollection(
                [[s["p1"], s["p2"]] for s in segs_w], colors="black", linewidths=0.8))
        if segs_o:
            cols = {ACI_RED: "red", ACI_GREEN: "green"}
            for c in (ACI_RED, ACI_GREEN):
                ss = [s for s in segs_o if s["color"] == c]
                if ss:
                    ax.add_collection(LineCollection(
                        [[s["p1"], s["p2"]] for s in ss],
                        colors=cols[c], linewidths=0.8))
        if marks:
            mx, my = zip(*marks)
            ax.scatter(mx, my, s=40, c="orange", edgecolors="red", zorder=5)
            for i, (x, y) in enumerate(marks):
                ax.annotate(str(i + 1), (x, y), fontsize=7, color="red",
                            xytext=(3, 3), textcoords="offset points")
        ax.set_aspect("equal")
        if window:
            (x0, y0, x1, y1) = window
            ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
        else:
            ax.autoscale_view(); ax.margins(0.03)

    # 整板图
    fig, ax = plt.subplots(figsize=(12, 9))
    draw_ax(ax, white_segs, other_segs, tab_marks)
    ax.set_title(f"Tab review: {len(tab_marks)} tabs, width={stats['tab_width']}mm, "
                 f"white={stats['n_white']} red={stats['n_red']} green={stats['n_green']}")
    fig.savefig(out_base + "_review.png", dpi=120, bbox_inches="tight")
    plt.close(fig)

    # 局部放大图（每张最多12个）
    per_fig = 12
    for fi in range(0, len(tab_marks), per_fig):
        chunk = tab_marks[fi:fi + per_fig]
        cols = 4
        rows = math.ceil(len(chunk) / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
        axes = [axes] if rows * cols == 1 else axes.flat
        R = 20  # 半窗 20mm
        for ax, (cx, cy) in zip(axes, chunk):
            draw_ax(ax, white_segs, other_segs, [(cx, cy)],
                    window=(cx - R, cy - R, cx + R, cy + R))
            ax.set_title(f"tab @({cx:.1f},{cy:.1f})")
        for ax in list(axes)[len(chunk):]:
            ax.axis("off")
        fig.suptitle(f"Tab close-ups {fi + 1}-{fi + len(chunk)}")
        fig.savefig(out_base + f"_review_detail_{fi // per_fig + 1}.png",
                    dpi=120, bbox_inches="tight")
        plt.close(fig)
    return out_base + "_review.png"


# ---------------- 主流程 ----------------
def main():
    global MIN_TAB_SEG
    ap = argparse.ArgumentParser(description="激光切割图自动打断口 v1.0")
    ap.add_argument("input", help="输入 DXF 文件")
    ap.add_argument("--thickness", type=float, default=None, help="板厚(mm)，3->0.7mm / 5->0.6mm 断口")
    ap.add_argument("--tab-width", type=float, default=None, help="手动指定断口宽度(mm)，优先级高于板厚查表")
    ap.add_argument("--out", default=None, help="输出 DXF 路径（默认 输入_断口.dxf）")
    ap.add_argument("--min-tab-len", type=float, default=MIN_TAB_SEG, help="能打断口的最短直线段(mm)")
    ap.add_argument("--no-png", action="store_true", help="不输出复核图")
    args = ap.parse_args()

    MIN_TAB_SEG = args.min_tab_len

    if args.tab_width:
        tab_width = args.tab_width
    elif args.thickness in TAB_WIDTH_TABLE:
        tab_width = TAB_WIDTH_TABLE[args.thickness]
    else:
        print(f"错误：板厚 {args.thickness} 没有实测断口宽度，请用 --tab-width 手动指定")
        sys.exit(2)

    issue = Issue()
    print(f"输入：{args.input}  板厚={args.thickness}mm  断口宽度={tab_width}mm")

    try:
        doc = ezdxf.readfile(args.input)
    except Exception as e:
        print(f"错误：DXF 读取失败：{e}")
        sys.exit(1)
    msp = doc.modelspace()

    # 预检样条：必须在 audit 之前 —— audit 会静默删除非法实体，
    # 等 audit 跑完再查就查不到了，几何丢了用户还不知道。
    n_spline = sum(1 for e in msp if e.dxftype() == "SPLINE")
    if n_spline:
        print(f"错误：发现 {n_spline} 条 SPLINE 样条曲线（手册禁止用样条）。")
        print("请在 CAD 里重画为直线/圆弧后再跑。已中止，未改动任何文件。")
        sys.exit(1)

    from collections import Counter
    before = Counter(e.dxftype() for e in msp)
    auditor = doc.audit()
    if auditor.has_errors:
        print(f"  [警告] 输入文件 audit 发现 {len(auditor.errors)} 个错误")
    after = Counter(e.dxftype() for e in msp)
    for t, n in before.items():
        lost = n - after.get(t, 0)
        if lost > 0:
            issue.warn(f"audit 删除了 {lost} 个 {t} 实体（输入文件可能损坏），请检查输入文件")

    # 1. 炸开块
    n_new, n_ins = explode_inserts(doc, msp, issue)
    print(f"  炸开 {n_ins} 个块引用，展开出 {n_new} 个实体")

    # 2. 抽线段 + 样条检查
    segments, curved, texts, stats = extract_segments(doc, msp, issue)
    if stats.get("SPLINE"):
        issue.report()
        print("存在样条曲线，已中止。请按手册重画为直线/圆弧后再跑。")
        sys.exit(1)
    print(f"  实体统计：{dict(stats)}")

    # 3. 清重复线/碎线/近重合线
    segments, n_dup, n_tiny, near = dedup_and_clean(segments, issue)
    print(f"  清理：重复线 {n_dup} 条，碎线 {n_tiny} 条，近重合 {len(near)} 处")

    # 4. 颜色校验
    if not check_colors(doc, msp, segments, curved, issue):
        issue.report()
        sys.exit(1)

    # 4b. 间距检查（教程要求：白线间距 <1.2mm 会连到一起）
    white_pre = [s for s in segments if s["color"] == ACI_WHITE]
    check_spacing(white_pre, issue)

    # 5. 按规则打断口（只打白线直线段）
    white_idx = [i for i, s in enumerate(segments) if s["color"] == ACI_WHITE]
    white_segs = [segments[i] for i in white_idx]
    other_segs = [s for s in segments if s["color"] != ACI_WHITE]
    curved_white = [c for c in curved if c["color"] == ACI_WHITE]
    curved_other = [c for c in curved if c["color"] != ACI_WHITE]

    parts = group_parts(white_segs)
    print(f"  白线零件分组：{len(parts)} 组")
    all_plans, tab_marks_all = [], []
    for pi, idxs in enumerate(parts):
        plans = plan_tabs(white_segs, idxs, tab_width, issue)
        # plans 用的是 white_segs 下标，直接可用
        all_plans.extend(plans)
        x0, y0, x1, y1 = part_bbox(white_segs, idxs)
        print(f"    零件{pi + 1}：{len(idxs)} 段，{x1 - x0:.0f}x{y1 - y0:.0f}mm，打 {len(plans)} 个断口")
    new_white, tab_marks = apply_tabs(white_segs, all_plans, tab_width)
    print(f"  共打断口 {len(tab_marks)} 个")

    # 6. 输出 DXF
    out_path = args.out or os.path.splitext(args.input)[0] + "_断口.dxf"
    out = build_output(new_white, other_segs, curved_white + curved_other, texts, tab_width)
    out.saveas(out_path)
    # 复核：重新打开审计
    chk = ezdxf.readfile(out_path)
    chk_aud = chk.audit()
    n_out = len(list(chk.modelspace()))
    n_ins_out = sum(1 for e in chk.modelspace() if e.dxftype() == "INSERT")
    print(f"  输出：{out_path}（{n_out} 实体，残留 INSERT={n_ins_out}，"
          f"audit 错误={len(chk_aud.errors)}）")

    # 7. 复核图
    if not args.no_png:
        base = os.path.splitext(out_path)[0]
        c = defaultdict(int)
        for s in segments:
            c[s["color"]] += 1
        for cu in curved:
            c[cu["color"]] += 1
        rp = draw_review(base, new_white, other_segs, curved,
                         tab_marks,
                         dict(tab_width=tab_width, n_white=c[ACI_WHITE],
                              n_red=c[ACI_RED], n_green=c[ACI_GREEN]))
        print(f"  复核图：{rp}（+ 局部放大图）")

    issue.report()
    print("完成。请放大复核图确认每个缺口实际存在，再交付。")


if __name__ == "__main__":
    main()
