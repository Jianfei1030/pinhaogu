#!/usr/bin/env python3
"""
开盘啦题材表格智能裁剪工具
============================
自动检测并切除手机截图中的冗余区域（状态栏、App导航栏、底部Footer、Home Indicator），
只保留核心题材表格内容。

Algorithm:
    - Top: 扫描找连续亮行（红色标题块），回退找到实际顶部
    - Bottom: 从底部向上找最后一个亮像素>8%的行，跳过免责声明/评论区的低对比度文字
    - 安全原则：检测不到冗余 = 不裁，绝不 fallback 到硬编码
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def crop_kpb_table(image_path, output_path=None):
    img = Image.open(image_path)
    arr = np.array(img)
    h, w = arr.shape[:2]

    if w < 200 or h < 200:
        raise ValueError("图片尺寸过小 (%dx%d)，可能不是有效的截图" % (w, h))

    title_top = _find_title_top(arr, h, w)
    content_bottom = _find_content_bottom(arr, h, w, title_top)

    needs_crop = (title_top > 0) or (content_bottom < h)

    if not needs_crop:
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, quality=95)
        return img, 0, h

    cropped = img.crop((0, title_top, w, content_bottom))

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path, quality=95)

    return cropped, title_top, content_bottom


def _find_title_top(arr, h, w):
    """找到主表格（红框表格）的顶部位置。

    算法（两阶段）：
    1. 快速路径：找第一段连续 20+ 行 bright_pct > 80% 的区域。
       大表格的红色标题栏亮度极高（>90%），而上方的 tabs/控件
       亮度通常 < 30%，可以有效区分。
       找到后回退 80 行，寻找暗区边界（pixel mean < 30）作为裁切点。

    2. 回退路径（快速路径未命中时）：
       用暗 gap + 红色标题栏 + 左红边验证的结构化方法，
       适用于亮度不那么极端的截图。

    安全原则：检测不到 = 不裁（return 0）。
    """

    arr16 = arr.astype(np.int16)

    def row_bright_pct(y):
        return float(np.mean(np.any(arr[y] > 150, axis=1)) * 100)

    def row_redness(y):
        row = arr16[y]
        return float(np.mean(row[:, 0] - np.maximum(row[:, 1], row[:, 2])))

    # === 快速路径：bright_pct > 80% 连续 20 行 ===
    BRIGHT_FAST_THRESHOLD = 80.0
    BRIGHT_FAST_RUN = 20
    BACKTRACK_ROWS = 80

    run_start = -1
    run_len = 0
    bright_run_start = -1

    for y in range(h):
        bpct = row_bright_pct(y)
        if bpct > BRIGHT_FAST_THRESHOLD:
            if run_start < 0:
                run_start = y
            run_len += 1
            if run_len >= BRIGHT_FAST_RUN:
                bright_run_start = run_start
                break
        else:
            run_start = -1
            run_len = 0

    if bright_run_start > 0:
        # 回退 BACKTRACK_ROWS 行，寻找暗区边界
        backtrack_start = max(0, bright_run_start - BACKTRACK_ROWS)
        for y in range(bright_run_start - 1, backtrack_start - 1, -1):
            mean_val = float(np.mean(arr[y]))
            if mean_val < 30:
                return y + 1
        # 如果没找到暗边界，用回退区间的起始位置
        return backtrack_start

    # === 回退路径：结构化检测 ===
    scan_limit = min(450, h // 3)
    GAP_BRIGHT_MAX = 5.0
    GAP_REDNESS_MAX = 2.0
    MIN_GAP_ROWS = 15
    TITLE_REDNESS_MIN = 6.0
    TITLE_BRIGHT_MIN = 8.0
    MIN_TITLE_RUN = 8
    LEFT_BORDER_SEARCH_W = min(80, w // 6)
    LEFT_BORDER_MIN_FRAC = 0.28

    def red_mask_window(y0, y1):
        sub = arr16[y0:y1]
        r = sub[:, :, 0]
        g = sub[:, :, 1]
        b = sub[:, :, 2]
        return (r > g + 6) & (r > b + 6) & (r > 35)

    # 1) 找顶部第一段有效暗区 gap
    dark_count = 0
    gap_end = -1
    seen_non_dark = False
    for y in range(0, scan_limit):
        bright = row_bright_pct(y)
        red = row_redness(y)

        if bright > GAP_BRIGHT_MAX or red > GAP_REDNESS_MAX:
            seen_non_dark = True

        if seen_non_dark and bright < GAP_BRIGHT_MAX and red < GAP_REDNESS_MAX:
            dark_count += 1
            if dark_count >= MIN_GAP_ROWS:
                gap_end = y + 1
                break
        else:
            dark_count = 0

    # 2) gap 后找第一段连续"标题栏候选区" + 左侧红竖边验证
    if gap_end > 0:
        run = 0
        run_start = -1
        for y in range(gap_end, scan_limit):
            bright = row_bright_pct(y)
            red = row_redness(y)
            if red >= TITLE_REDNESS_MIN and bright >= TITLE_BRIGHT_MIN:
                if run == 0:
                    run_start = y
                run += 1
                if run >= MIN_TITLE_RUN:
                    y0 = run_start
                    # 回溯：从 run_start 向上找到红度首次达标的位置
                    for yy in range(y0 - 1, max(gap_end, y0 - 50), -1):
                        if row_redness(yy) >= TITLE_REDNESS_MIN:
                            y0 = yy
                        else:
                            break
                    # 验证：从标题栏区域内的任意位置往下检查左侧红边
                    check_start = y0 + 30  # 标题栏中部
                    check_end = min(h, check_start + 220)
                    red_mask = red_mask_window(check_start, check_end)
                    col_frac = red_mask.mean(axis=0)
                    left_border_frac = float(col_frac[:LEFT_BORDER_SEARCH_W].max())
                    if left_border_frac >= LEFT_BORDER_MIN_FRAC:
                        return y0
            else:
                # 中断时，如果之前积累了足够的 run，检查它
                if run >= MIN_TITLE_RUN:
                    y0 = run_start
                    for yy in range(y0 - 1, max(gap_end, y0 - 50), -1):
                        if row_redness(yy) >= TITLE_REDNESS_MIN:
                            y0 = yy
                        else:
                            break
                    check_start = y0 + 30
                    check_end = min(h, check_start + 220)
                    red_mask = red_mask_window(check_start, check_end)
                    col_frac = red_mask.mean(axis=0)
                    left_border_frac = float(col_frac[:LEFT_BORDER_SEARCH_W].max())
                    if left_border_frac >= LEFT_BORDER_MIN_FRAC:
                        return y0
                run = 0
                run_start = -1

    # 3) 最终 fallback：保守亮度规则
    consecutive_bright = 0
    for y in range(100, min(300, h // 3)):
        bright_pct = row_bright_pct(y)
        if bright_pct > 40:
            consecutive_bright += 1
            if consecutive_bright >= 10:
                return y - 9
        else:
            consecutive_bright = 0

    return 0


def _find_content_bottom(arr, h, w, title_top):
    """从底部向上找到最后一个有内容的行。

    策略：从底部向上扫描（跳过 Home Indicator 区域），
    第一个亮像素 > 8% 的行就是表格的最后一行。
    表格行通常 8-20% 亮像素，免责声明/页脚只有 0-5%。
    """
    CONTENT_BRIGHT_THRESHOLD = 8.0

    # 从底部向上扫描，跳过 Home Indicator 区域（最后50px）
    for y in range(min(h - 50, h - 1), title_top, -1):
        bright_pct = np.sum(arr[y] > 150) / w * 100
        if bright_pct > CONTENT_BRIGHT_THRESHOLD:
            return min(y + 3, h)

    return h


def detect_redundancy(image_path):
    img = Image.open(image_path)
    arr = np.array(img)
    h, w = arr.shape[:2]

    if w < 200 or h < 200:
        raise ValueError("图片尺寸过小 (%dx%d)，可能不是有效的截图" % (w, h))

    title_top = _find_title_top(arr, h, w)
    content_bottom = _find_content_bottom(arr, h, w, title_top)

    top_redundant = title_top
    bottom_redundant = h - content_bottom

    return {
        "needs_crop": top_redundant > 0 or bottom_redundant > 0,
        "title_top": title_top,
        "content_bottom": content_bottom,
        "top_redundant_px": top_redundant,
        "bottom_redundant_px": bottom_redundant,
        "image_size": (w, h),
    }


def process_batch(image_paths, outdir=None, verbose=True):
    results = []

    for i, img_path in enumerate(image_paths):
        if not os.path.exists(img_path):
            print("  ❌ 文件不存在: %s" % img_path)
            continue

        if outdir:
            Path(outdir).mkdir(parents=True, exist_ok=True)
            out_path = os.path.join(outdir, os.path.splitext(os.path.basename(img_path))[0] + "_cropped.jpg")
        else:
            base = os.path.splitext(img_path)[0]
            out_path = base + "_cropped.jpg"

        if verbose:
            print("  [%d/%d] %s ..." % (i + 1, len(image_paths), os.path.basename(img_path)))

        try:
            cropped, top, bottom = crop_kpb_table(img_path, out_path)
            if verbose:
                print("    ✅ 裁剪后: %dx%d (切除顶部 %dpx, 底部 %dpx)" % (
                    cropped.width, cropped.height, top, cropped.height + top - bottom if bottom else 0))
            results.append((img_path, out_path, top, bottom))
        except Exception as e:
            print("    ❌ 处理失败: %s" % e)
            results.append((img_path, None, None, None))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="开盘啦题材表格智能裁剪工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kpb_crop.py screenshot.jpg
  python kpb_crop.py screenshot.jpg -o cropped.jpg
  python kpb_crop.py img1.jpg img2.jpg img3.jpg
  python kpb_crop.py *.jpg --outdir ./cropped
        """
    )
    parser.add_argument("images", nargs="+", help="输入图片路径（支持多张）")
    parser.add_argument("-o", "--output", help="输出图片路径（仅单张时有效）")
    parser.add_argument("--outdir", help="输出目录（批量处理时有效）")
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式")
    parser.add_argument("--detect-only", action="store_true", help="仅检测，不裁剪")

    args = parser.parse_args()

    if args.detect_only:
        for img_path in args.images:
            if not os.path.exists(img_path):
                print("❌ 文件不存在: %s" % img_path)
                continue
            result = detect_redundancy(img_path)
            status = "需要裁剪" if result["needs_crop"] else "无需裁剪（内容完整）"
            print("%s: %s" % (os.path.basename(img_path), status))
            print("  尺寸: %dx%d" % result["image_size"])
            print("  顶部冗余: %dpx" % result["top_redundant_px"])
            print("  底部冗余: %dpx" % result["bottom_redundant_px"])
        return

    if len(args.images) == 1 and args.output:
        img_path = args.images[0]
        cropped, top, bottom = crop_kpb_table(img_path, args.output)
        if not args.quiet:
            print("裁剪完成: %s" % args.output)
    else:
        results = process_batch(args.images, outdir=args.outdir, verbose=not args.quiet)
        success = sum(1 for r in results if r[1] is not None)
        if not args.quiet:
            print("\n处理完成: %d/%d 成功" % (success, len(results)))
        if success == 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
