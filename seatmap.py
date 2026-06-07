#!/usr/bin/env python3
"""
seatmap.py  ——  议会席位图（傻瓜式） / Parliament Seat Map (no-brainer)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  用法 / Usage：
    1. 用记事本打开同目录下的 data.txt / Open data.txt in the same folder with Notepad
    2. 按格式填入党派、席位、颜色 / Fill in parties, seats, colors per the format
    3. 双击运行本文件 → 自动生成 seatmap.svg（浏览器打开即可查看）
       Double-click to run → auto-generates SVG (open in browser to view)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  无需安装任何第三方库，Python 自带即可运行
  No third-party libraries needed; runs with built-in Python
"""

import io, json, math, os, re, sys, tempfile
from pathlib import Path

# ════════════════════ 可调参数 / Tunable Parameters ════════════════════
# 如果你觉得图太大/太小/点太大/太小，改下面几个数字就行
# If the chart is too big/small or dots are too big/small, tweak the numbers below

WIDTH      = 1200        # 图片宽度（像素），越大越清晰 / Image width (px), larger = sharper
DOT_SIZE   = 14          # 每个席位小圆点的直径（像素） / Diameter of each seat dot (px)
EMPTY      = 0           # 空缺席位数（灰色空心圆），0 表示没有空席 / Empty seats (grey hollow circles), 0 = none
OUTPUT     = None        # 设为 None 则用标题自动命名文件；也可手动指定固定文件名
                          # Set to None to auto-name file from title; or manually specify a fixed filename

# ════════════════════ 内部参数（一般不用动） / Internal Params (usually don't touch) ═════════════════════
PAD        = 40          # 四边留白 / Padding on all sides
MIN_LAYERS = 5           # 最少层数，小国会至少撑到这个层数 / Minimum layers, small parliaments expand to at least this
MAX_LAYERS = 30          # 最多层数，防止席位过多时层数爆炸 / Maximum layers, prevents layer explosion for huge parliaments
GAP        = 5.0         # 席位之间固定的边缘间距（像素），席位多则扇环更厚而非间距更密
                          # Fixed edge gap between seats (px); more seats → thicker arc, not tighter spacing

# 空缺席位标记 / Empty seat marker
EMPTY_SEAT = object()


# ════════════════════ data.txt 解析 / data.txt Parsing ════════════════════

def parse_data_txt(path):
    """
    解析 data.txt，格式极其简单 / Parse data.txt, format is super simple：
    
        # 这是注释（以 # 开头） / This is a comment (starts with #)
        标题 / title = 第42届议会 / 42nd Parliament
        
        保守党 / Conservative    210    #3366CC
        工党 / Labour            180    #CC3333
        自由民主党 / LibDem        40    #FF9933
        绿党 / Green              15    #33AA55
        
    规则 / Rules：
      - # 开头的行为注释，忽略 / Lines starting with # are comments, ignored
      - 「标题 = xxx」设定标题（可选） / 「title = xxx」sets the title (optional)
      - 其余有效行：党派名  席位数  颜色  （空格/Tab 分隔均可）
        Remaining valid lines: party_name  seat_count  color  (space/Tab separated)
      - 颜色写 #RRGGBB 或纯 RRGGBB 都行 / Color can be #RRGGBB or plain RRGGBB
    """
    if not os.path.isfile(path):
        print(f"[X] 找不到 / Not found: {path}，请在同目录下创建 data.txt！ / Please create data.txt in the same folder!")
        print()
        print("   data.txt 格式示例 / Format example：")
        print("   ─────────────────────────────────────")
        print("   标题 / title = 我的议会 / My Parliament")
        print()
        print("   保守党 / Conservative    210    #3366CC")
        print("   工党 / Labour            180    #CC3333")
        print("   自由民主党 / LibDem        40    #FF9933")
        print("   ─────────────────────────────────────")
        sys.exit(1)

    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    title = ""
    parties = []

    for line in lines:
        line = line.strip()
        # 跳过空行和注释 / Skip blank lines and comments
        if not line or line.startswith("#"):
            continue
        # 标题行：标题 = xxx / Title line: title = xxx
        if line.startswith("标题") and "=" in line:
            _, val = line.split("=", 1)
            title = val.strip()
            continue
        if line.startswith("title") and "=" in line.lower():
            _, val = line.split("=", 1)
            title = val.strip()
            continue
        # 数据行：从右往左解析 / Data line: parse from right to left
        # 最后两个字段一定是「席位数」和「颜色」，前面剩下的全部是党派名
        # The last two fields are always seat_count and color; everything before is the party name
        parts = line.split()
        if len(parts) < 3:
            continue
        # 从右端取颜色和席位 / Grab color and seat count from the right end
        color = parts[-1]
        try:
            seats = int(parts[-2])
        except ValueError:
            continue
        # 剩下的全部拼成党派名 / Everything else is the party name
        name = " ".join(parts[:-2])
        if seats > 0:
            parties.append({"name": name, "seats": seats, "color": color})

    if not parties:
        print("[X] data.txt 中没有有效的党派数据！ / No valid party data in data.txt!")
        print()
        print("   请确保每行格式为：党派名  席位数  颜色 / Please ensure each line is: party_name  seat_count  color")
        print("   例如 / e.g.：保守党 / Conservative  210  #3366CC")
        sys.exit(1)

    return title, parties


# ════════════════════ 布局算法 / Layout Algorithm ════════════════════

def build_seat_list(parties, empty_count=0):
    """各党派展开为一维席位列表，末尾追加空席 / Expand each party into a flat seat list, append empty seats at end"""
    seats = []
    for p in parties:
        seats.extend([p] * int(p["seats"]))
    if empty_count > 0:
        seats.extend([EMPTY_SEAT] * empty_count)
    return seats


def smart_ring_gap(total, radius_max, dot_r, fixed_gap, min_layers, max_layers, canvas_width, pad):
    """
    智能环宽函数 / Smart ring gap function：
      席位之间的弧上边缘间距保持固定（fixed_gap），席位多 → 层数多 → 扇环更厚。
      只在以下情况微调：
        1. 层数 < min_layers：适度缩小间距撑到最少层数（避免扇环过薄）
        2. 层数 > max_layers：最内层用紧凑间距排剩余席位（避免圆心处堆积）
      ────────────────────────────────────────────────────────────────
      Fixed edge gap between seats; more seats → more layers → thicker arc.
      Only tweaks in edge cases:
        1. layers < min_layers: moderately shrink spacing for minimum thickness
        2. layers > max_layers: pack remaining seats tightly on innermost layer
    """
    spacing = dot_r * 2 + fixed_gap

    def simulate_layers(s, respect_min_r=True):
        """
        模拟排布。respect_min_r=True 时 r < dot_r 不再建新层；
        False 时继续排到完（用于层数上限检测）。
        """
        remaining = total
        r = radius_max
        layers = 0
        cx = canvas_width / 2
        oob = 0

        while remaining > 0 and layers < 300:
            if respect_min_r and r < dot_r:
                # 半径太小，剩余席位不再开新层，记为最后一层 / Radius too small, stop here
                layers += 1
                break
            capacity = max(1, int(math.pi * r / s))
            take = min(capacity, remaining)
            remaining -= take
            layers += 1
            r -= s

            if layers == 1 and take > 1:
                ang = s / radius_max
                half = (take - 1) * ang / 2
                left_x = cx + radius_max * math.cos(math.pi / 2 + half)
                right_x = cx + radius_max * math.cos(math.pi / 2 - half)
                oob = max(0, pad - left_x) + max(0, right_x - (canvas_width - pad))

        return layers, oob

    # 先用固定间距模拟 / First simulate with fixed spacing
    layers, oob = simulate_layers(spacing)

    # 层数太少（扇环太薄）：适度缩小间距 / Too few layers (arc too thin): moderately shrink spacing
    if layers < min_layers:
        target = min_layers
        lo, hi = dot_r * 2, spacing
        for _ in range(40):
            mid = (lo + hi) / 2.0
            l, _ = simulate_layers(mid)
            if l >= target:
                hi = mid
            else:
                lo = mid
        spacing = hi
        layers, oob = simulate_layers(spacing)

    # 层数爆炸（席位太多）：外 MAX_LAYERS 层用固定间距，剩余全塞最内层
    # Layers exploding: outer MAX_LAYERS layers use fixed spacing, rest crammed into innermost
    raw_layers, _ = simulate_layers(spacing, respect_min_r=False)
    if raw_layers > max_layers:
        # 标记需要在内层紧凑排布 / Flag that inner layer needs compact packing
        spacing = spacing  # 保持固定间距不变 / keep fixed spacing unchanged

    # 越界回退：缩小间距 / Out-of-bounds fallback: shrink spacing
    if oob > 0:
        for _ in range(40):
            spacing += 1.0
            _, new_oob = simulate_layers(spacing)
            if new_oob == 0:
                break
            if spacing > radius_max:
                break

    arc_gap = spacing - dot_r * 2
    return max(0.0, arc_gap)


def chamber_layout(total, cx, bottom_y, radius_max, dot_r, arc_gap, max_layers=30):
    """
    核心布局算法 / Core layout algorithm：
      - 每个席位之间弧上圆心间距固定 = dot_size + arc_gap
        Fixed arc distance between seat centers = dot_size + arc_gap
      - 从最外层开始逐层填充 / Fill layer by layer from outermost
      - 前 max_layers-1 层用固定间距；超出部分紧凑排在最内层（保持扇环比例）
        First max_layers-1 layers use fixed spacing; overflow packed tightly on innermost layer
      - 不是强制半圆，弧扫多大角度由该层席位数量决定
        Not a forced semicircle; arc sweep angle is determined by seat count on that layer
    返回 [(x, y), ...] / Returns [(x, y), ...]
    """
    positions = []
    if total <= 0:
        return positions

    # 圆心之间沿弧的间距（像素） / Arc distance between centers (px)
    spacing = dot_r * 2 + arc_gap

    # 先决定分几层、每层放几个 / First decide how many layers and seats per layer
    layers = []
    remaining = total
    layer_idx = 0

    # 前 max_layers-1 层：正常间距排布 / First max_layers-1 layers: normal spacing
    while remaining > 0 and layer_idx < max_layers - 1:
        r = radius_max - layer_idx * spacing
        if r < dot_r:
            # 半径太小，剩余全塞这一层 / Radius too small, cram rest here
            layers.append(remaining)
            remaining = 0
            break
        arc_len = math.pi * r
        capacity = max(1, int(arc_len / spacing))
        take = min(capacity, remaining)
        layers.append(take)
        remaining -= take
        layer_idx += 1

    # 如果还有剩余席位，全塞最后一层 / If seats remain, cram all into innermost layer
    if remaining > 0:
        layers.append(remaining)
        layer_idx += 1

    # 逐层绘制 / Draw layer by layer
    for li, count in enumerate(layers):
        r = max(dot_r, radius_max - li * spacing)

        # 最后一层如果席位密度过高，使用紧凑间距 / Innermost layer: use compact spacing if crowded
        if li == len(layers) - 1 and count > 1 and r <= dot_r * 3:
            # 紧凑模式：席位之间边缘间距 = dot_r（比正常间距小）/ Compact mode: edge gap = dot_r
            compact_spacing = dot_r * 2 + dot_r
            compact_angular = compact_spacing / r
            compact_total = (count - 1) * compact_angular
            compact_half = compact_total / 2.0
            for i in range(count):
                theta = (math.pi / 2 + compact_half) - i * compact_angular
                x = cx + r * math.cos(theta)
                y = bottom_y - r * math.sin(theta)
                positions.append((x, y))
            continue

        if count == 1:
            x = cx
            y = bottom_y - r
            positions.append((x, y))
        else:
            angular_spacing = spacing / r
            total_angle = (count - 1) * angular_spacing
            half_angle = total_angle / 2.0
            for i in range(count):
                theta = (math.pi / 2 + half_angle) - i * angular_spacing
                x = cx + r * math.cos(theta)
                y = bottom_y - r * math.sin(theta)
                positions.append((x, y))

    return positions


# ════════════════════ SVG 渲染 / SVG Rendering ════════════════════

def render_svg(title, parties, seats, out_path, width, dot_size, empty_count):
    dot_r = dot_size / 2
    height = int(width * 0.65)
    cx = width / 2
    bottom_y = height - PAD
    # radius_max 同时受高度和宽度约束，确保席位不超出画布 / constrained by both height and width
    radius_max = min((height - PAD * 2) * 0.92,
                     (width - PAD * 2) / 2)
    total = len(seats)

    # 智能环宽：固定间距优先，席位多则层数多 / Smart ring gap: fixed spacing first, more seats = more layers
    arc_gap = smart_ring_gap(total, radius_max, dot_r, GAP, MIN_LAYERS, MAX_LAYERS, width, PAD)

    positions = chamber_layout(total, cx, bottom_y, radius_max, dot_r, arc_gap, MAX_LAYERS)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'style="background:rgb(248,248,248)">\n'
    ]
    if title:
        parts.append(
            f'  <text x="{PAD}" y="{PAD+48}" '
            f'font-family="sans-serif" font-size="16" fill="#222">'
            f'{title.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}'
            f'</text>\n'
        )

    def _box(d):
        return d * 0.7

    for (x, y), seat in zip(positions, seats):
        if seat is EMPTY_SEAT:
            parts.append(
                f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r:.1f}" '
                f'fill="#e0e0e0" stroke="#b0b0b0" stroke-width="{max(0.5, dot_r*0.15):.1f}"/>\n'
            )
        else:
            c = seat["color"]
            if not c.startswith("#"):
                c = "#" + c
            parts.append(
                f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r:.1f}" fill="{c}"/>\n'
            )

    lx = width - PAD - 220
    ly = PAD + 18
    for p in parties:
        pc = p["color"]
        if not pc.startswith("#"):
            pc = "#" + pc
        parts.append(
            f'  <rect x="{lx}" y="{ly}" width="{_box(dot_size)}" '
            f'height="{_box(dot_size)}" fill="{pc}" rx="2"/>\n'
        )
        parts.append(
            f'  <text x="{lx+_box(dot_size)+6}" y="{ly+_box(dot_size)+1}" '
            f'font-family="sans-serif" font-size="13" fill="#333">'
            f'{p["name"].replace("&","&amp;").replace("<","&lt;")} ({p["seats"]})</text>\n'
        )
        ly += _box(dot_size) + 8
    if empty_count > 0:
        parts.append(
            f'  <rect x="{lx}" y="{ly}" width="{_box(dot_size)}" '
            f'height="{_box(dot_size)}" fill="none" stroke="#b0b0b0" stroke-width="1" rx="2"/>\n'
        )
        parts.append(
            f'  <text x="{lx+_box(dot_size)+6}" y="{ly+_box(dot_size)+1}" '
            f'font-family="sans-serif" font-size="13" fill="#333">空席 / Empty ({empty_count})</text>\n'
        )

    parts.append('</svg>')
    Path(out_path).write_text(''.join(parts), encoding='utf-8')
    filled = total - empty_count
    if empty_count > 0:
        print(f"[OK] SVG 已生成 / SVG generated：{Path(out_path).resolve()}  （{filled} 已分配 / allocated + {empty_count} 空席 / empty = {total} 席 / seats）")
    else:
        print(f"[OK] SVG 已生成 / SVG generated：{Path(out_path).resolve()}  （{total} 席 / seats）")


# ════════════════════ 主流程 / Main ════════════════════

def main():
    # 固定读取同目录下的 data.txt / Always read data.txt in the same folder
    script_dir = Path(__file__).parent
    data_path = script_dir / "data.txt"

    print("═" * 50)
    print("  半圆议会席位图生成器 / Semicircle Parliament Seat Map Generator")
    print("═" * 50)
    print()
    print(f"[i] 读取数据 / Reading data：{data_path}")

    title, parties = parse_data_txt(str(data_path))

    seats = build_seat_list(parties, EMPTY)
    total = len(seats)
    if total == 0:
        print("[X] 总席位 = 0，请检查 data.txt / Total seats = 0, please check data.txt")
        sys.exit(1)

    print(f"[=] {len(parties)} 个党派 / parties，共 / total {total} 席 / seats" + (f"（含 / incl. {EMPTY} 空席 / empty）" if EMPTY else ""))
    if title:
        print(f"[T] 标题 / Title：{title}")
    # 预计算环宽用于显示 / Pre-compute arc gap for display
    dot_r = DOT_SIZE / 2
    height = int(WIDTH * 0.65)
    radius_max = min((height - PAD * 2) * 0.92,
                     (WIDTH - PAD * 2) / 2)
    arc_gap = smart_ring_gap(total, radius_max, dot_r, GAP, MIN_LAYERS, MAX_LAYERS, WIDTH, PAD)
    print(f"[G] 固定边缘间距 / Fixed edge gap：{GAP:.1f} px → 实际环宽 / actual arc_gap：{arc_gap:.1f} px（层数 / layers：{MIN_LAYERS}~{MAX_LAYERS}）")
    print()

    if OUTPUT:
        out = str(script_dir / OUTPUT)
    else:
        # 用标题命名文件，去除不能当文件名的字符，默认 fallback 为 seatmap
        # Auto-name file from title, strip invalid filename chars, default fallback = seatmap
        safe_title = title.strip() if title else ""
        if safe_title:
            # 去掉不能当文件名的字符：<>:"/\|?* / Strip invalid filename chars: <>:"/\|?*
            safe_title = re.sub(r'[<>:"/\\|?*]', '', safe_title)
            safe_title = safe_title.strip()
        if not safe_title:
            safe_title = "seatmap"
        out = str(script_dir / f"{safe_title}.svg")
    render_svg(title, parties, seats, out, WIDTH, DOT_SIZE, EMPTY)

    print()
    print("[Done] 完成！按任意键退出... / Done! Press any key to exit...")
    try:
        input()
    except EOFError:
        pass


if __name__ == "__main__":
    main()



# © 2026 常乐风。保留部分权利。
# 本作品采用《知识共享 署名-非商业性使用 4.0 国际许可协议》(CC BY-NC 4.0) 进行许可。
#
# © 2026 Chang Lefeng. Some rights reserved.
# This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0) License.
