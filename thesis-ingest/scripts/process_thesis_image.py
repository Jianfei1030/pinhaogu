#!/usr/bin/env python3
"""
Thesis image processing orchestrator.

Two modes:
  A) Default: --image only → 6-step pipeline from image to DB
  B) Shortcut: --image + --input-json → skip to insert step (2 steps)
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 确保 scripts/ 目录在 Python path 中
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def get_latest_file(output_dir: Path, prefix: str, suffix: str = ".json") -> Optional[Path]:
    """Get most recent file or directory matching prefix in output_dir.
    Excludes run record files (containing '_run_')."""
    if not output_dir.exists():
        return None
    # Search for both files and directories, excluding run records
    candidates = sorted(
        [p for p in output_dir.glob(f"{prefix}*{suffix}")
         if p.is_file() and '_run_' not in p.name],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if candidates:
        return candidates[0]
    # If no file found and suffix is empty, also check for directories
    if not suffix or suffix == "":
        dir_candidates = sorted(
            [p for p in output_dir.glob(f"{prefix}*")
             if p.is_dir() and '_run_' not in p.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if dir_candidates:
            return dir_candidates[0]
    return None


def get_fixed_file(output_dir: Path, name: str) -> Optional[Path]:
    """Get a file or directory by exact name in output_dir."""
    target = output_dir / name
    if target.exists():
        return target
    return None


def run_step(
    step_num: int,
    total_steps: int,
    step_name: str,
    cmd: list[str],
    output_dir: Path,
    output_prefix: str,
    output_suffix: str = ".json",
    fixed_output_name: str = None,
) -> dict:
    """Run a subprocess step and return result dict."""
    print(f"\n阶段 {step_num}/{total_steps}: {step_name}")
    print(f"  命令: {' '.join(cmd)}")

    result = {
        "step": step_name,
        "command": " ".join(cmd),
        "input": None,
        "output": None,
        "status": "fail",
        "error": None,
    }

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if proc.returncode != 0:
            result["error"] = proc.stderr or proc.stdout or "Unknown error"
            print(f"  ❌ 失败: {result['error'][:200]}")
            return result

        # Find output file or directory
        if fixed_output_name:
            output_file = get_fixed_file(output_dir, fixed_output_name)
        else:
            output_file = get_latest_file(output_dir, output_prefix, output_suffix)
        if output_file:
            result["output"] = str(output_file)
            print(f"  ✅ 输出: {output_file.name}")
        else:
            print(f"  ✅ 完成（未检测到输出文件）")

        result["status"] = "success"

    except subprocess.TimeoutExpired:
        result["error"] = "Timeout (>300s)"
        print(f"  ❌ 超时")
    except Exception as e:
        result["error"] = str(e)
        print(f"  ❌ 异常: {e}")

    return result


def _resolve_python() -> str:
    """优先使用本项目 .venv 的 Python，否则 fallback 到系统 python3。"""
    venv_python = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"


def main():
    parser = argparse.ArgumentParser(description="Thesis image processing orchestrator")
    parser.add_argument("--image", required=True, help="Path to thesis image")
    parser.add_argument("--input-json", help="Shortcut: skip to insert step with existing JSON")
    parser.add_argument("--output-dir", default="output", help="Output directory (default: output)")
    parser.add_argument("--db", default="thesis.db", help="Database path (default: thesis.db)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay for MM API calls")
    parser.add_argument("--model", default=None, help="图片识别模型后端: qwen 或 copilot")
    args = parser.parse_args()

    # 确定 Python 可执行文件
    python_exe = _resolve_python()

    # Validate inputs
    image_path = Path(args.image)
    if not image_path.exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)

    # 按题材名创建输出子目录，每次运行清空重建
    theme_name = image_path.stem
    output_dir = Path(args.output_dir) / theme_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db)
    scripts_dir = Path(__file__).parent

    # Determine mode
    shortcut_mode = bool(args.input_json)

    if shortcut_mode:
        input_json = Path(args.input_json)
        if not input_json.exists():
            print(f"❌ Input JSON not found: {input_json}")
            sys.exit(1)
        total_steps = 2
        print(f"🚀 快捷模式: 从 {input_json.name} 开始，共 {total_steps} 步")
    else:
        total_steps = 6
        print(f"🚀 完整模式: 从原图起步，共 {total_steps} 步")

    # Run summary
    run_summary = {
        "timestamp": datetime.now().isoformat(),
        "mode": "shortcut" if shortcut_mode else "full",
        "image": str(image_path),
        "steps": [],
        "final_status": "running",
    }
    
    try:
        step_idx = 0
        
        if not shortcut_mode:
            # === Step 1: plan_semantic_cuts ===
            step_idx += 1
            result = run_step(
                step_idx, total_steps,
                "plan_semantic_cuts",
                [
                    python_exe, str(scripts_dir / "plan_semantic_cuts.py"),
                    "--output-dir", str(output_dir),
                    "--image", str(image_path),
                    "--fixed-name",
                ],
                output_dir, "path_cut_plan_",
                fixed_output_name="cut_plan.json",
            )
            run_summary["steps"].append(result)
            if result["status"] == "fail":
                raise RuntimeError(f"Step {step_idx} failed")
            
            # === Step 2: split_by_path_plan ===
            step_idx += 1
            plan_json = result["output"]
            result = run_step(
                step_idx, total_steps,
                "split_by_path_plan",
                [
                    python_exe, str(scripts_dir / "split_by_path_plan.py"),
                    "--plan", plan_json,
                    "--image", str(image_path),
                    "--output-dir", str(output_dir),
                    "--fixed-name",
                ],
                output_dir, "path_segments_", "",
                fixed_output_name="segments",
            )
            run_summary["steps"].append(result)
            if result["status"] == "fail":
                raise RuntimeError(f"Step {step_idx} failed")
            
            # === Step 3: parse_path_segments_mm ===
            step_idx += 1
            segments_dir = result["output"]
            # Find manifest JSON in the segments directory
            manifest_json = None
            if segments_dir and Path(segments_dir).is_dir():
                # fixed-name mode: look for manifest.json
                fixed_manifest = Path(segments_dir) / "manifest.json"
                if fixed_manifest.exists():
                    manifest_json = fixed_manifest
                else:
                    manifest_candidates = sorted(
                        Path(segments_dir).glob("path_segments_manifest_*.json"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True
                    )
                    if manifest_candidates:
                        manifest_json = manifest_candidates[0]
            if not manifest_json:
                # Fallback: search in output_dir
                manifest_json = get_latest_file(output_dir, "path_segments_manifest_", ".json")

            cmd = [
                python_exe, str(scripts_dir / "parse_path_segments_mm.py"),
                "--manifest", str(manifest_json),
                "--output-dir", str(output_dir),
                "--delay", str(args.delay),
                "--fixed-name",
            ]
            if args.model:
                cmd.extend(["--model", args.model])
            # 从图片文件名推断根题材名
            root_name = image_path.stem
            cmd.extend(["--root-name", root_name])
            result = run_step(
                step_idx, total_steps,
                "parse_path_segments_mm",
                cmd,
                output_dir, "path_segment_parse_",
                fixed_output_name="segment_parse.json",
            )
            run_summary["steps"].append(result)
            if result["status"] == "fail":
                raise RuntimeError(f"Step {step_idx} failed")
            
            # === Step 4: expand_path_ancestors ===
            step_idx += 1
            parse_json = result["output"]
            result = run_step(
                step_idx, total_steps,
                "expand_path_ancestors",
                [
                    python_exe, str(scripts_dir / "expand_path_ancestors.py"),
                    "--source", parse_json,
                    "--output-dir", str(output_dir),
                    "--fixed-name",
                ],
                output_dir, "path_ancestor_candidates_",
                fixed_output_name="ancestor_candidates.json",
            )
            run_summary["steps"].append(result)
            if result["status"] == "fail":
                raise RuntimeError(f"Step {step_idx} failed")
            
            input_json = Path(result["output"])
        
        # === Step 5 (or 1 in shortcut): insert_thesis_tree ===
        step_idx += 1
        cmd = [
            python_exe, str(scripts_dir / "insert_thesis_tree.py"),
            "--input", str(input_json),
            "--db", str(db_path),
        ]
        if not shortcut_mode:
            cmd.extend(["--source-image", str(image_path.name)])
            # 从图片文件名推断根题材名（去掉扩展名）
            root_name = image_path.stem
            cmd.extend(["--root-name", root_name])
        result = run_step(
            step_idx, total_steps,
            "insert_thesis_tree",
            cmd,
            output_dir, ""  # No output file for insert
        )
        run_summary["steps"].append(result)
        if result["status"] == "fail":
            raise RuntimeError(f"Step {step_idx} failed")

        # === Step 6 (or 2 in shortcut): verify_thesis_report ===
        step_idx += 1
        root_name = image_path.stem
        result = run_step(
            step_idx, total_steps,
            "verify_thesis_report",
            [
                python_exe, str(scripts_dir / "verify_thesis_report.py"),
                "--image-name", root_name,
                "--db", str(db_path),
                "--output-dir", str(output_dir),
                "--fixed-name",
            ],
            output_dir, "verify_report_",
            fixed_output_name="verify_report.md",
        )
        run_summary["steps"].append(result)
        # 校验报告失败不终止流程（只是报告），但记录状态

        # Success!
        run_summary["final_status"] = "success"
        print(f"\n✅ 全部 {total_steps} 步完成")
        
    except Exception as e:
        run_summary["final_status"] = "failed"
        run_summary["error"] = str(e)
        print(f"\n❌ 流程失败: {e}")
    
    # Write run summary
    summary_json = output_dir / "run_summary.json"
    summary_json.write_text(json.dumps(run_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 Run summary: {summary_json}")

    # Write MD summary if success
    if run_summary["final_status"] == "success":
        summary_md = output_dir / "run_summary.md"
        md_lines = [
            f"# Thesis Processing Summary",
            f"",
            f"**Timestamp**: {run_summary['timestamp']}",
            f"**Mode**: {run_summary['mode']}",
            f"**Image**: `{image_path.name}`",
            f"**Status**: ✅ SUCCESS",
            f"",
            f"## Steps",
            f"",
        ]
        for i, step in enumerate(run_summary["steps"], 1):
            md_lines.append(f"{i}. **{step['step']}**: {step['status']}")
            if step.get("output"):
                md_lines.append(f"   - Output: `{Path(step['output']).name}`")
        
        summary_md.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"📄 MD summary: {summary_md}")
    
    # Exit with appropriate code
    if run_summary["final_status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()