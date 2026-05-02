#!/usr/bin/env python3
"""
split_for_multimodal.py - 将长图切成适合多模态模型理解的若干段

T2.5mm1 任务脚本
- 输入: 开盘啦长截图
- 输出: 分段图片 + manifest (JSON + MD) + contact sheet
"""

import os
import sys
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import argparse


def parse_args():
    parser = argparse.ArgumentParser(description='Split long image into segments for multimodal analysis')
    parser.add_argument('input_image', help='Input image path')
    parser.add_argument('--output-dir', default='output', help='Output directory')
    parser.add_argument('--prefix', default='mm_segments', help='Output prefix')
    parser.add_argument('--overlap-pct', type=float, default=0.08, help='Overlap percentage (0.05-0.10)')
    parser.add_argument('--target-segments', type=int, default=10, help='Target number of segments')
    parser.add_argument('--crop-top', type=int, default=180, help='Pixels to crop from top (status bar)')
    parser.add_argument('--crop-bottom', type=int, default=150, help='Pixels to crop from bottom (nav bar)')
    return parser.parse_args()


def create_contact_sheet(segments_info, output_path, thumb_height=400):
    """Create a contact sheet showing all segments with their boundaries."""
    # Load first segment to get width
    first_img = Image.open(segments_info[0]['image_path'])
    seg_width = first_img.width
    
    # Calculate layout
    num_segs = len(segments_info)
    cols = min(2, num_segs)
    rows = (num_segs + cols - 1) // cols
    
    thumb_width = int(seg_width * thumb_height / segments_info[0]['crop_bbox'][3])
    
    # Create canvas
    margin = 20
    text_height = 40
    canvas_width = cols * (thumb_width + margin) + margin
    canvas_height = rows * (thumb_height + text_height + margin) + margin
    
    canvas = Image.new('RGB', (canvas_width, canvas_height), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 16)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            font = ImageFont.load_default()
    
    for idx, seg_info in enumerate(segments_info):
        row = idx // cols
        col = idx % cols
        
        x = margin + col * (thumb_width + margin)
        y = margin + row * (thumb_height + text_height + margin)
        
        # Load and resize segment
        img = Image.open(seg_info['image_path'])
        img_thumb = img.resize((thumb_width, thumb_height), Image.LANCZOS)
        
        # Draw border
        draw.rectangle([x-2, y-2, x+thumb_width+2, y+thumb_height+2], outline=(100, 100, 100), width=2)
        
        # Paste thumbnail
        canvas.paste(img_thumb, (x, y))
        
        # Draw label
        label = f"Segment {seg_info['segment_id']:02d}: y={seg_info['crop_bbox'][1]}-{seg_info['crop_bbox'][3]}"
        draw.text((x, y + thumb_height + 5), label, fill=(200, 200, 200), font=font)
    
    canvas.save(output_path, 'PNG', quality=95)
    print(f"Contact sheet saved: {output_path}")
    return output_path


def split_image(input_path, output_dir, prefix, overlap_pct, target_segments, crop_top, crop_bottom):
    """Main splitting logic."""
    
    # Load image
    img = Image.open(input_path)
    orig_width, orig_height = img.size
    print(f"Original image: {orig_width}x{orig_height}")
    
    # Crop top and bottom (remove status bar and nav bar)
    crop_y1 = crop_top
    crop_y2 = orig_height - crop_bottom
    cropped_img = img.crop((0, crop_y1, orig_width, crop_y2))
    cropped_height = cropped_img.height
    print(f"After cropping: {orig_width}x{cropped_height} (removed top {crop_top}, bottom {crop_bottom})")
    
    # Calculate segment parameters
    # Each segment height = total_height / target_segments, adjusted for overlap
    base_seg_height = cropped_height / target_segments
    overlap_pixels = int(base_seg_height * overlap_pct)
    seg_height = int(base_seg_height + overlap_pixels)
    
    print(f"Base segment height: {base_seg_height:.1f}px")
    print(f"Overlap: {overlap_pixels}px ({overlap_pct*100:.1f}%)")
    print(f"Actual segment height: {seg_height}px")
    
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seg_dir_name = f"{prefix}_{timestamp}"
    seg_dir = os.path.join(output_dir, seg_dir_name)
    os.makedirs(seg_dir, exist_ok=True)
    print(f"Output directory: {seg_dir}")
    
    # Generate segments
    segments = []
    seg_id = 1
    y = 0
    
    while y < cropped_height:
        y1 = y
        y2 = min(y + seg_height, cropped_height)
        
        # Calculate overlap with previous
        overlap_with_prev = 0
        if seg_id > 1:
            prev_end = segments[-1]['crop_bbox'][3] - crop_y1
            overlap_with_prev = max(0, prev_end - y1)
        
        # Crop from the cropped image
        seg_img = cropped_img.crop((0, y1, orig_width, y2))
        
        # Save segment
        seg_filename = f"segment_{seg_id:02d}.png"
        seg_path = os.path.join(seg_dir, seg_filename)
        seg_img.save(seg_path, 'PNG', quality=95)
        
        # Record segment info
        seg_info = {
            "segment_id": seg_id,
            "image_path": seg_path,
            "crop_bbox": [0, y1 + crop_y1, orig_width, y2 + crop_y1],  # Original image coordinates
            "relative_bbox": [0, y1, orig_width, y2],  # Cropped image coordinates
            "size": [seg_img.width, seg_img.height],
            "overlap_with_prev": overlap_with_prev,
            "notes": f"Covers rows approximately {y1}-{y2} in cropped image"
        }
        segments.append(seg_info)
        
        print(f"  Segment {seg_id:02d}: y={y1+crop_y1}-{y2+crop_y1} ({seg_img.height}px, overlap={overlap_with_prev}px)")
        
        # Move to next position (with step = base_seg_height to maintain overlap)
        y = int(seg_id * base_seg_height)
        seg_id += 1
        
        if y2 >= cropped_height:
            break
    
    # Create manifest
    manifest = {
        "image_path": input_path,
        "image_size": [orig_width, orig_height],
        "cropped_region": {
            "top_crop": crop_top,
            "bottom_crop": crop_bottom,
            "cropped_height": cropped_height
        },
        "strategy": {
            "method": "equal_height_with_overlap",
            "target_segments": target_segments,
            "actual_segments": len(segments),
            "overlap_percentage": overlap_pct,
            "overlap_pixels": overlap_pixels
        },
        "segment_count": len(segments),
        "segments": segments,
        "timestamp": timestamp,
        "next_step": "T2.5mm2: Use multimodal model to parse each segment for table structure and content"
    }
    
    # Save JSON manifest
    json_path = os.path.join(output_dir, f"{prefix}_manifest_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nJSON manifest saved: {json_path}")
    
    # Generate Markdown manifest
    md_content = generate_markdown_manifest(manifest, input_path, seg_dir)
    md_path = os.path.join(output_dir, f"{prefix}_manifest_{timestamp}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"Markdown manifest saved: {md_path}")
    
    # Create contact sheet
    contact_path = os.path.join(output_dir, f"{prefix}_manifest_{timestamp}_contact.png")
    create_contact_sheet(segments, contact_path)
    
    return manifest, json_path, md_path, contact_path


def generate_markdown_manifest(manifest, input_path, seg_dir):
    """Generate Markdown manifest content."""
    
    md = f"""# Segment Manifest - Multimodal Split Results

## Overview

| Property | Value |
|----------|-------|
| Original Image | `{manifest['image_path']}` |
| Image Size | {manifest['image_size'][0]} x {manifest['image_size'][1]} px |
| Cropped Height | {manifest['cropped_region']['cropped_height']} px |
| Top Crop | {manifest['cropped_region']['top_crop']} px (status bar removed) |
| Bottom Crop | {manifest['cropped_region']['bottom_crop']} px (nav bar removed) |
| Segment Count | {manifest['segment_count']} |
| Overlap | {manifest['strategy']['overlap_percentage']*100:.1f}% ({manifest['strategy']['overlap_pixels']} px) |
| Timestamp | {manifest['timestamp']} |

## Splitting Strategy

This manifest was generated by **T2.5mm1** (Segment Splitting for Multimodal Analysis).

### Why This Split?

1. **Row Context Preservation**: Each segment maintains continuous row context from the table
2. **Overlap Buffer**: {manifest['strategy']['overlap_percentage']*100:.1f}% overlap prevents information loss at segment boundaries
3. **Size Optimization**: Each segment is sized for optimal multimodal model comprehension
4. **Noise Reduction**: Top status bar and bottom navigation bar have been cropped

### Segment Distribution

The original image was divided into **{manifest['segment_count']} segments** of approximately equal height, with intentional overlap between consecutive segments to ensure no table rows are lost at boundaries.

## Segment Details

| ID | File | Y-Range (Original) | Y-Range (Cropped) | Size | Overlap with Prev |
|----|------|-------------------|-------------------|------|-------------------|
"""
    
    for seg in manifest['segments']:
        orig_range = f"{seg['crop_bbox'][1]}-{seg['crop_bbox'][3]}"
        rel_range = f"{seg['relative_bbox'][1]}-{seg['relative_bbox'][3]}"
        size_str = f"{seg['size'][0]}x{seg['size'][1]}"
        overlap_str = f"{seg['overlap_with_prev']} px" if seg['overlap_with_prev'] > 0 else "N/A (first)"
        md += f"| {seg['segment_id']:02d} | `{os.path.basename(seg['image_path'])}` | {orig_range} | {rel_range} | {size_str} | {overlap_str} |\n"
    
    md += f"""
## File Locations

- **Segments Directory**: `{seg_dir}/`
- **JSON Manifest**: `mm_segments_manifest_{manifest['timestamp']}.json`
- **Contact Sheet**: `mm_segments_manifest_{manifest['timestamp']}_contact.png`

## Next Step: T2.5mm2

**Consume these segments** using a multimodal model (e.g., GPT-4V, Claude, Gemini) to:

1. Parse table structure from each segment
2. Extract category hierarchies (大类/小类)
3. Identify stock codes and names
4. Output structured data per segment

### Recommended Processing Order

```python
import json

# Load manifest
with open('mm_segments_manifest_{manifest['timestamp']}.json') as f:
    manifest = json.load(f)

# Process each segment
for seg in manifest['segments']:
    # Load segment image
    img_path = seg['image_path']
    
    # Send to multimodal model with prompt:
    # "Parse this table segment. Extract: category, subcategory, stock names"
    
    # Store results with segment_id for later merging
```

## Notes

- **Do not modify segment files** - they are referenced by absolute paths in the manifest
- **Overlap regions** may contain duplicate rows when merging results from T2.5mm2
- **Contact sheet** provides visual verification of segment coverage

---
*Generated by split_for_multimodal.py | Task T2.5mm1*
"""
    return md


def main():
    args = parse_args()
    
    if not os.path.exists(args.input_image):
        print(f"Error: Input image not found: {args.input_image}")
        sys.exit(1)
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("="*60)
    print("Split for Multimodal Analysis - T2.5mm1")
    print("="*60)
    
    manifest, json_path, md_path, contact_path = split_image(
        args.input_image,
        args.output_dir,
        args.prefix,
        args.overlap_pct,
        args.target_segments,
        args.crop_top,
        args.crop_bottom
    )
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    print(f"Total segments: {manifest['segment_count']}")
    print(f"JSON manifest: {json_path}")
    print(f"Markdown manifest: {md_path}")
    print(f"Contact sheet: {contact_path}")
    print(f"Segments directory: {os.path.dirname(manifest['segments'][0]['image_path'])}")
    print("\nT2.5mm1 complete. Ready for T2.5mm2 (multimodal parsing).")


if __name__ == "__main__":
    main()
