#!/usr/bin/env python3
"""
插入题材到 thesis_list 表
用法: python3 scripts/insert_thesis_list.py --thesis-name "AI 硬件"
"""
import argparse
import json
import sqlite3
from pathlib import Path

# 工作目录
WORK_DIR = Path(__file__).parent.parent
DB_PATH = WORK_DIR / "thesis.db"
OUTPUT_DIR = WORK_DIR / "output"


def get_thesis_info(thesis_name: str) -> dict:
    """从 OCR 结构化结果中获取题材信息"""
    json_files = list(OUTPUT_DIR.glob("ocr_structured_v2_*.json"))
    if not json_files:
        return {"name": thesis_name, "stock_count": 0}
    
    # 读取最新的 JSON 文件
    latest_file = max(json_files, key=lambda f: f.stat().st_mtime)
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 检查题材名匹配（支持 OCR 误差，如 "Al硬件" vs "AI 硬件"）
    json_thesis_name = data.get("thesis_name", "")
    stocks = data.get("stocks", [])
    
    # 如果传入的题材名和 JSON 中的题材名相似（忽略大小写和空格）
    normalized_input = thesis_name.lower().replace(" ", "")
    normalized_json = json_thesis_name.lower().replace(" ", "")
    
    if normalized_input == normalized_json or "ai" in normalized_input and "硬件" in normalized_json:
        return {"name": thesis_name, "stock_count": len(stocks)}
    
    return {"name": thesis_name, "stock_count": 0}


def insert_thesis(thesis_name: str, stock_count: int = 0, description: str = "") -> bool:
    """插入题材到数据库，返回是否插入成功"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO thesis_list (thesis_name, stock_count, description)
            VALUES (?, ?, ?)
        """, (thesis_name, stock_count, description))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # 题材已存在
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="插入题材到 thesis_list 表")
    parser.add_argument("--thesis-name", required=True, help="题材名称")
    parser.add_argument("--description", default="", help="题材描述")
    args = parser.parse_args()
    
    # 获取题材信息
    info = get_thesis_info(args.thesis_name)
    thesis_name = info["name"]
    stock_count = info["stock_count"]
    description = args.description
    
    print(f"题材名称: {thesis_name}")
    print(f"成分股数量: {stock_count}")
    
    # 插入数据库
    if insert_thesis(thesis_name, stock_count, description):
        print(f"✅ 成功插入: {thesis_name}")
    else:
        print(f"⚠️ 题材已存在: {thesis_name}")
    
    # 验证插入
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, thesis_name, stock_count, created_at FROM thesis_list WHERE thesis_name = ?", (thesis_name,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"\n数据库记录:")
        print(f"  ID: {row[0]}")
        print(f"  题材名: {row[1]}")
        print(f"  成分股数: {row[2]}")
        print(f"  创建时间: {row[3]}")


if __name__ == "__main__":
    main()