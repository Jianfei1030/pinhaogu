#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify thesis-ingest database state.

Usage:
    cd os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest
    python3 scripts/verify_thesis_data.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def fetch_one(cur: sqlite3.Cursor, sql: str, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify thesis-ingest data")
    parser.add_argument("--db", default="thesis.db", help="Database file name")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    db_path = base_dir / args.db
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_json = output_dir / f"thesis_verify_result_{ts}.json"
    report_md = output_dir / f"thesis_verify_result_{ts}.md"

    checks = []
    errors = []
    warnings = []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # A. Basic structure
        has_thesis_list = table_exists(cur, "thesis_list")
        checks.append({"name": "thesis_list exists", "pass": has_thesis_list})
        if not has_thesis_list:
            errors.append("Missing table: thesis_list")
            # Cannot continue without thesis_list
            payload = {
                "timestamp": ts,
                "status": "FAIL",
                "db": str(db_path),
                "summary": {},
                "checks": checks,
                "errors": errors,
                "warnings": warnings,
            }
            report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        has_template = table_exists(cur, "thesis_stocks_template")
        checks.append({"name": "thesis_stocks_template exists", "pass": has_template})
        if not has_template:
            errors.append("Missing table: thesis_stocks_template")

        dynamic_table_count = fetch_one(
            cur,
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'thesis_stocks_%' AND name != 'thesis_stocks_template'",
        )

        # B. thesis_list semantic checks
        thesis_list_count = fetch_one(cur, "SELECT COUNT(*) FROM thesis_list")

        # Check for empty description
        empty_description_count = fetch_one(cur, "SELECT COUNT(*) FROM thesis_list WHERE description IS NULL OR TRIM(description) = ''")
        checks.append({
            "name": "thesis_list has no empty description",
            "pass": empty_description_count == 0,
            "actual": empty_description_count,
        })
        if empty_description_count != 0:
            errors.append(f"Found {empty_description_count} empty descriptions")

        # Check for empty thesis_name
        empty_name_count = fetch_one(cur, "SELECT COUNT(*) FROM thesis_list WHERE thesis_name IS NULL OR TRIM(thesis_name) = ''")
        checks.append({
            "name": "thesis_list has no empty thesis_name",
            "pass": empty_name_count == 0,
            "actual": empty_name_count,
        })
        if empty_name_count != 0:
            errors.append(f"Found {empty_name_count} empty thesis_name")

        # Check for duplicate thesis_name
        duplicate_name_count = fetch_one(
            cur,
            "SELECT COUNT(*) FROM (SELECT thesis_name, COUNT(*) c FROM thesis_list GROUP BY thesis_name HAVING c > 1)",
        )
        checks.append({
            "name": "thesis_list has no duplicate thesis_name",
            "pass": duplicate_name_count == 0,
            "actual": duplicate_name_count,
        })
        if duplicate_name_count != 0:
            errors.append(f"Found {duplicate_name_count} duplicated thesis_name entries")

        # C. table_name mapping validation
        null_table_name_count = fetch_one(cur, "SELECT COUNT(*) FROM thesis_list WHERE table_name IS NULL")
        checks.append({
            "name": "all thesis_list entries have table_name",
            "pass": null_table_name_count == 0,
            "actual": null_table_name_count,
        })
        if null_table_name_count != 0:
            errors.append(f"Found {null_table_name_count} entries with NULL table_name")

        # D. Validate each thesis: table exists and stock_count matches
        cur.execute("SELECT thesis_name, table_name, stock_count FROM thesis_list")
        rows = cur.fetchall()

        table_mismatch_count = 0
        missing_table_count = 0
        thesis_samples = {}
        table_samples = {}

        for row in rows:
            thesis_name = row["thesis_name"]
            table_name = row["table_name"]
            expected_count = row["stock_count"]

            thesis_info = {
                "table_name": table_name,
                "stock_count": expected_count,
            }

            if not table_name:
                missing_table_count += 1
                thesis_info["table_exists"] = False
                thesis_info["row_count_match"] = False
                thesis_info["actual_row_count"] = None
                thesis_samples[thesis_name] = thesis_info
                continue

            # Check if table exists
            exists = table_exists(cur, table_name)
            thesis_info["table_exists"] = exists

            if not exists:
                missing_table_count += 1
                errors.append(f"Table {table_name} for thesis '{thesis_name}' does not exist")
                thesis_info["row_count_match"] = False
                thesis_info["actual_row_count"] = None
                thesis_samples[thesis_name] = thesis_info
                continue

            # Check row count
            actual_count = fetch_one(cur, f'SELECT COUNT(*) FROM "{table_name}"')
            thesis_info["actual_row_count"] = actual_count
            thesis_info["row_count_match"] = (actual_count == expected_count)

            if actual_count != expected_count:
                table_mismatch_count += 1
                warnings.append(f"Thesis '{thesis_name}': stock_count={expected_count}, actual rows={actual_count}")

            thesis_samples[thesis_name] = thesis_info

            # Sample rows for first 3 tables
            if len(table_samples) < 3:
                cur.execute(f'SELECT stock_code, stock_name, thesis_description FROM "{table_name}" ORDER BY stock_code LIMIT 3')
                sample_rows = [dict(r) for r in cur.fetchall()]
                table_samples[table_name] = {
                    "thesis_name": thesis_name,
                    "row_count": actual_count,
                    "sample_rows": sample_rows,
                }

        checks.append({
            "name": "all referenced tables exist",
            "pass": missing_table_count == 0,
            "actual": f"{len(rows) - missing_table_count}/{len(rows)}",
        })

        checks.append({
            "name": "stock_count matches actual table rows",
            "pass": table_mismatch_count == 0,
            "actual": f"{len(rows) - table_mismatch_count}/{len(rows)}",
        })

        # E. Summary
        passed = len(errors) == 0
        partial_pass = len(errors) == 0 and len(warnings) > 0
        status = "PASS" if passed and not partial_pass else ("PARTIAL_PASS" if partial_pass else "FAIL")

        payload = {
            "timestamp": ts,
            "status": status,
            "db": str(db_path),
            "summary": {
                "thesis_list_count": thesis_list_count,
                "dynamic_table_count": dynamic_table_count,
                "table_name_filled_count": len(rows) - null_table_name_count,
                "table_name_null_count": null_table_name_count,
                "missing_table_count": missing_table_count,
                "stock_count_mismatch_count": table_mismatch_count,
            },
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "thesis_samples": thesis_samples,
            "table_samples": table_samples,
        }
        report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # Generate markdown report
        lines = [
            "# Thesis Verify Result",
            "",
            f"- 时间: `{ts}`",
            f"- 状态: **{status}**",
            f"- thesis_list 条数: **{thesis_list_count}**",
            f"- thesis_stocks_* 表数: **{dynamic_table_count}**",
            f"- table_name 填充: **{len(rows) - null_table_name_count}/{len(rows)}**",
            f"- stock_count 匹配: **{len(rows) - table_mismatch_count}/{len(rows)}**",
            "",
            "## Summary",
            "",
        ]
        for key, value in payload["summary"].items():
            lines.append(f"- {key}: {value}")

        if thesis_samples:
            lines.extend(["", "## Theme Samples (first 10)", ""])
            for i, (theme, info) in enumerate(list(thesis_samples.items())[:10]):
                lines.append(f"- `{theme}`")
                lines.append(f"  - table_name: `{info.get('table_name', 'NULL')}`")
                lines.append(f"  - stock_count: {info.get('stock_count', 'N/A')}")
                lines.append(f"  - actual_rows: {info.get('actual_row_count', 'N/A')}")
                lines.append(f"  - match: {'✓' if info.get('row_count_match') else '✗'}")

        if table_samples:
            lines.extend(["", "## Table Samples", ""])
            for table_name, sample in table_samples.items():
                lines.append(f"- `{table_name}` | thesis: {sample['thesis_name']} | row_count: {sample['row_count']}")
                for row in sample.get("sample_rows", []):
                    lines.append(f"  - {row['stock_code']} {row['stock_name']} | {row['thesis_description']}")

        if errors:
            lines.extend(["", "## Errors", ""])
            for err in errors:
                lines.append(f"- {err}")

        if warnings:
            lines.extend(["", "## Warnings", ""])
            for warn in warnings:
                lines.append(f"- {warn}")

        report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        print(json.dumps({
            "status": payload["status"],
            "summary": payload["summary"],
            "report_json": str(report_json),
            "report_md": str(report_md),
            "errors": errors,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2))
        return 0 if passed else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())