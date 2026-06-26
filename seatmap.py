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
# 如果你觉得图太大/太小，改下面几个数字就行
# If the chart is too big/small, tweak the numbers below

WIDTH      = 360         # 图片宽度（像素） / Image width (px)
HEIGHT     = 185         # 图片高度（像素） / Image height (px)
EMPTY      = 0           # 空缺席位数（灰色空心圆），0 表示没有空席 / Empty seats (grey hollow circles), 0 = none
OUTPUT     = None        # 设为 None 则用标题自动命名文件；也可手动指定固定文件名
                          # Set to None to auto-name file from title; or manually specify a fixed filename

SEAT_SCALE  = 0.75       # 席位圆点缩放系数，让所有圆点变小 / Seat dot scale factor, makes all dots smaller

# ════════════════════ 内部参数（一般不用动） / Internal Params (usually don't touch) ═════════════════════
PAD        = 8           # 四边留白 / Padding on all sides
FONT_SIZE  = 18          # 底部数字字号（固定，作为布局基准）/ Bottom number font size (fixed, layout anchor)
EDGE_GAP   = 1.0         # 席位之间边缘间距（像素），保证席位不粘连 / Edge gap between seats (px), ensures seats don't touch
MAX_LAYERS = 30          # 最多层数，防止席位过多时层数爆炸 / Maximum layers, prevents layer explosion for huge parliaments
MIN_LAYERS = 3           # 最少层数 / Minimum layers

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


def auto_layout(total, radius_max, font_size, min_layers, max_layers, edge_gap):
    """
    自动布局 / Auto layout：
      根据总席位数自动计算席位圆点半径(dot_r)和层数(layers)。
      数字字号固定为基准，弧顶到数字之间约5个字号高度。
      席位之间保留固定边缘间距，保证视觉上不粘连。
      ────────────────────────────────────────────────────────────────
      Given total seats, auto-compute dot radius and number of layers.
      Font size is fixed as the anchor; arc top to number ~5 font heights.
      Fixed edge gap between seats ensures they never visually merge.
    
    返回 (dot_r, layers) / Returns (dot_r, layers)
    """
    # 层间距 = 直径 + 边缘间距 / Layer spacing = diameter + edge gap
    # 席位圆心弧上间距 = 直径 + 边缘间距 / Arc spacing between centers = diameter + edge gap
    
    def capacity_for_dot_r(dr, L):
        """给定 dot_r 和层数，计算总容量"""
        spacing = dr * 2 + edge_gap
        cap = 0
        for layer in range(L):
            r = radius_max - layer * spacing
            if r < dr:
                cap += 1
            else:
                cap += max(1, int(math.pi * r / spacing))
        return cap
    
    # 二分搜索：找到刚好容纳 total 席位的最大 dot_r（给定层数）
    def find_dot_r_for_layers(total_seats, L):
        # 宽范围的二分搜索
        lo, hi = 0.5, radius_max
        for _ in range(80):
            mid = (lo + hi) / 2
            if capacity_for_dot_r(mid, L) >= total_seats:
                lo = mid  # 容量够，尝试更大的 dot_r
            else:
                hi = mid  # 容量不够，缩小 dot_r
        return lo  # 返回最大可行的 dot_r
    
    # 用公式估算目标层数：total ≈ k * L²，系数随 edge_gap 调整
    # Estimate target layers: total ≈ k * L², coefficient varies with edge_gap
    k = 3.2 + edge_gap * 0.5
    target_L = max(min_layers, min(max_layers, int(math.sqrt(total / k) + 0.5)))
    
    # 先试目标层数，不够就逐层增加
    for L in range(target_L, max_layers + 1):
        dr = find_dot_r_for_layers(total, L)
        cap = capacity_for_dot_r(dr, L)
        if cap >= total:
            return dr, L
    
    # 兜底
    dr = find_dot_r_for_layers(total, max_layers)
    return dr, max_layers


def chamber_layout(total, cx, bottom_y, radius_max, dot_r, layers, edge_gap):
    """
    核心布局算法 / Core layout algorithm：
      - 席位之间保留固定边缘间距，圆心间距 = 直径 + edge_gap
        Fixed edge gap between seats, center spacing = diameter + edge_gap
      - 从最外层开始逐层填充，共 layers 层
        Fill layer by layer from outermost, total `layers` layers
      - 不是强制半圆，弧扫多大角度由该层席位数量决定
        Not a forced semicircle; arc sweep angle is determined by seat count on that layer
    返回 [(x, y), ...] / Returns [(x, y), ...]
    """
    positions = []
    if total <= 0:
        return positions

    spacing = dot_r * 2 + edge_gap  # 圆心间距 / center spacing

    # 计算每层放几个 / Decide seats per layer
    layer_counts = []
    remaining = total
    for li in range(layers):
        r = radius_max - li * spacing
        if r < dot_r:
            cap = 1
        else:
            cap = max(1, int(math.pi * r / spacing))
        take = min(cap, remaining)
        layer_counts.append(take)
        remaining -= take
        if remaining <= 0:
            break

    # 如果还有剩余，全塞最后一层 / If seats remain, cram into last layer
    if remaining > 0 and layer_counts:
        layer_counts[-1] += remaining

    # 逐层绘制 / Draw layer by layer
    for li, count in enumerate(layer_counts):
        r = max(dot_r, radius_max - li * spacing)

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

def render_svg(title, parties, seats, out_path, width, height, empty_count):
    cx = width / 2
    bottom_y = height - PAD
    total = len(seats)

    # 数字放在画布底部，预留呼吸空间 / Number at canvas bottom with breathing room
    number_y = height - FONT_SIZE * 0.85

    # 弧顶到数字之间约 5 个字号高度 / Arc top to number: ~5 font heights
    arc_top_y = number_y - 5 * FONT_SIZE
    radius_max = bottom_y - arc_top_y

    # 同时受宽度约束 / Also constrained by width
    radius_max = min(radius_max, (width - PAD * 2) / 2)

    # 自动布局 / Auto layout
    dot_r, layers = auto_layout(total, radius_max, FONT_SIZE, MIN_LAYERS, MAX_LAYERS, EDGE_GAP)

    positions = chamber_layout(total, cx, bottom_y, radius_max, dot_r, layers, EDGE_GAP)

    # 缩小席位圆圈视觉尺寸 / Shrink visual seat circle size
    dot_r *= SEAT_SCALE

    # 根据实际弧底位置调整数字 Y：数字放在最外层席位底部下方，但不超过底部留白
    # Adjust number Y: place below outermost seat bottoms, but clamp to bottom padding
    if positions:
        arc_bottom_y = max(y for _, y in positions) + dot_r  # 席位底部边缘
        number_y = height - 11
        # 确保数字不超出底部留白 / Ensure number stays within bottom padding
        number_y = min(height - PAD * 0.6, number_y)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'style="background:rgb(248,248,248)">\n'
    ]

    for (x, y), seat in zip(positions, seats):
        if seat is EMPTY_SEAT:
            stroke_w = max(0.5, dot_r * 0.15)
            parts.append(
                f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r:.1f}" '
                f'fill="#e0e0e0" stroke="#b0b0b0" stroke-width="{stroke_w:.1f}"/>\n'
            )
        else:
            c = seat["color"]
            if not c.startswith("#"):
                c = "#" + c
            parts.append(
                f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r:.1f}" fill="{c}"/>\n'
            )

    # 底部中心：加粗席位总数
    # Bottom center: bold total seat count
    parts.append(
        f'  <text x="{width/2:.1f}" y="{number_y:.1f}" '
        f'font-family="sans-serif" font-size="{FONT_SIZE}" font-weight="700" '
        f'fill="#333" text-anchor="middle">{total}</text>\n'
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
    # 兼容 exe 打包：PyInstaller 打包后 __file__ 指向临时目录，改用 sys.executable
    # Compatible with exe: PyInstaller redirects __file__ to temp, use sys.executable instead
    if getattr(sys, 'frozen', False):
        script_dir = Path(sys.executable).parent
    else:
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
    # 预计算布局信息用于显示 / Pre-compute layout info for display
    bottom_y = HEIGHT - PAD
    number_y = HEIGHT - FONT_SIZE * 0.85
    arc_top_y = number_y - 5 * FONT_SIZE
    radius_max = bottom_y - arc_top_y
    radius_max = min(radius_max, (WIDTH - PAD * 2) / 2)
    dot_r, layers = auto_layout(total, radius_max, FONT_SIZE, MIN_LAYERS, MAX_LAYERS, EDGE_GAP)
    print(f"[L] 自动布局 / Auto layout：dot_r={dot_r:.1f}px（直径={dot_r*2:.1f}px），层数 / layers={layers}，边缘间距 / edge gap={EDGE_GAP:.1f}px")
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
    render_svg(title, parties, seats, out, WIDTH, HEIGHT, EMPTY)

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
