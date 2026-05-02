#!/usr/bin/env python3
"""
Insert thesis stocks from path_ancestor_candidates JSON into thesis.db.

Usage:
    cd thesis-ingest
    python3 scripts/insert_thesis_stocks.py --input output/path_ancestor_candidates_20260409_224845.json

Business rules:
    1. Use prefix path thesis_name (not bare node names)
    2. Normalize "AI硬件" to "AI 硬件"
    3. Use canonical stock_name from lookup
    4. thesis_description contains source path
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add workspace to path for lookup service
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "workspace"))

from services.stock_lookup_service import lookup_a_stock_code_by_name

# =============================================================================
# Table Name Sanitization
# =============================================================================

def sanitize_table_name(thesis_name: str) -> str:
    """
    Convert thesis name to stable, valid SQL table name.
    
    Strategy: Use MD5 hash of thesis_name to ensure:
    - Stable and reproducible
    - Handles spaces, slashes, Chinese, brackets, etc.
    - No SQL injection risk
    - Short and queryable
    
    Format: thesis_stocks_<8-char-md5-prefix>
    """
    # Normalize thesis_name for hashing
    normalized = thesis_name.strip()
    
    # Generate MD5 hash and take first 8 chars for readable table name
    hash_hex = hashlib.md5(normalized.encode('utf-8')).hexdigest()[:8]
    
    return f"thesis_stocks_{hash_hex}"


# =============================================================================
# Path Processing
# =============================================================================

def normalize_root_name(name: str) -> str:
    """Normalize 'AI硬件' to 'AI 硬件'."""
    if name == "AI硬件":
        return "AI 硬件"
    return name


def build_prefix_paths(path_raw: list) -> list:
    """
    Build all prefix paths from path_raw list.
    
    Example: ["AI硬件", "光模块", "法拉第旋光片"]
    Returns: [
        "AI 硬件",
        "AI 硬件 / 光模块",
        "AI 硬件 / 光模块 / 法拉第旋光片"
    ]
    """
    normalized_path = [normalize_root_name(n) for n in path_raw]
    
    prefix_paths = []
    for i in range(len(normalized_path)):
        prefix = " / ".join(normalized_path[:i+1])
        prefix_paths.append(prefix)
    
    return prefix_paths


# =============================================================================
# Database Operations
# =============================================================================

def create_stocks_table(conn: sqlite3.Connection, table_name: str):
    """Create dynamic stocks table if not exists."""
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT UNIQUE,
            stock_name TEXT NOT NULL,
            thesis_description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    
    # Create indexes
    cursor.execute(f'''
        CREATE INDEX IF NOT EXISTS idx_{table_name}_code ON {table_name}(stock_code)
    ''')
    cursor.execute(f'''
        CREATE INDEX IF NOT EXISTS idx_{table_name}_name ON {table_name}(stock_name)
    ''')
    
    conn.commit()


def upsert_thesis_list(conn: sqlite3.Connection, thesis_name: str, table_name: str):
    """Insert or update thesis_list entry."""
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute('SELECT table_name FROM thesis_list WHERE thesis_name = ?', (thesis_name,))
    row = cursor.fetchone()
    
    if row:
        # Update updated_at and ensure table_name matches
        cursor.execute('''
            UPDATE thesis_list 
            SET table_name = ?, updated_at = datetime('now', 'localtime')
            WHERE thesis_name = ?
        ''', (table_name, thesis_name))
    else:
        # Insert new
        cursor.execute('''
            INSERT INTO thesis_list (thesis_name, table_name, stock_count, created_at, updated_at)
            VALUES (?, ?, 0, datetime('now', 'localtime'), datetime('now', 'localtime'))
        ''', (thesis_name, table_name))
    
    conn.commit()


def insert_stock_to_table(conn: sqlite3.Connection, table_name: str, 
                          stock_code: str, stock_name: str, thesis_description: str) -> bool:
    """
    Insert stock into table with dedup by stock_code.
    Returns True if inserted, False if duplicate.
    """
    cursor = conn.cursor()
    
    try:
        cursor.execute(f'''
            INSERT INTO {table_name} (stock_code, stock_name, thesis_description)
            VALUES (?, ?, ?)
        ''', (stock_code, stock_name, thesis_description))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Duplicate by stock_code
        return False


def update_stock_count(conn: sqlite3.Connection, thesis_name: str):
    """Update stock_count in thesis_list based on actual table count."""
    cursor = conn.cursor()
    
    # Get table_name
    cursor.execute('SELECT table_name FROM thesis_list WHERE thesis_name = ?', (thesis_name,))
    row = cursor.fetchone()
    if not row:
        return
    
    table_name = row[0]
    
    # Count stocks in table
    cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
    count = cursor.fetchone()[0]
    
    # Update thesis_list
    cursor.execute('''
        UPDATE thesis_list 
        SET stock_count = ?, updated_at = datetime('now', 'localtime')
        WHERE thesis_name = ?
    ''', (count, thesis_name))
    conn.commit()


# =============================================================================
# Main Processing
# =============================================================================

def process_candidates(json_path: Path, db_path: Path) -> dict:
    """
    Main processing logic.
    Returns result summary dict.
    """
    # Load JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    items = data.get('items', [])
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    
    # Track results
    thesis_to_table = {}
    thesis_to_stocks = {}  # thesis_name -> set of (stock_code, stock_name, description)
    unique_stocks = set()
    missing_stocks = []
    
    print(f"📄 输入文件: {json_path.name}")
    print(f"📊 Source items: {len(items)}")
    print()
    
    # Process each item
    for item in items:
        path_raw = item.get('path_raw', [])
        stock_text_raw = item.get('stock_text_raw', '')
        path_display = item.get('path_display', '')
        notes = item.get('notes', '')
        
        # Build prefix paths
        prefix_paths = build_prefix_paths(path_raw)
        
        # Parse stock names
        stock_names = stock_text_raw.split()
        
        for stock_name_raw in stock_names:
            # Lookup stock code
            lookup_result = lookup_a_stock_code_by_name(stock_name_raw)
            
            if not lookup_result:
                missing_stocks.append(stock_name_raw)
                continue
            
            stock_code = lookup_result['stock_code']
            stock_name = lookup_result['stock_name']  # canonical name
            unique_stocks.add(stock_name)
            
            # Build thesis_description
            source_path = " / ".join([normalize_root_name(n) for n in path_raw])
            thesis_description = f"来源路径: {source_path}"
            if notes:
                thesis_description += f"\n备注: {notes}"
            
            # Add to all prefix thesis
            for thesis_name in prefix_paths:
                if thesis_name not in thesis_to_stocks:
                    thesis_to_stocks[thesis_name] = set()
                thesis_to_stocks[thesis_name].add((stock_code, stock_name, thesis_description))
    
    print(f"🔍 Unique thesis names: {len(thesis_to_stocks)}")
    print(f"📈 Unique stocks: {len(unique_stocks)}")
    print(f"❌ Missing lookups: {len(missing_stocks)}")
    if missing_stocks:
        print(f"   Missing: {missing_stocks}")
    print()
    
    # Write to database
    print("写入数据库...")
    
    for thesis_name, stocks in thesis_to_stocks.items():
        table_name = sanitize_table_name(thesis_name)
        thesis_to_table[thesis_name] = table_name
        
        # Create table
        create_stocks_table(conn, table_name)
        
        # Upsert thesis_list
        upsert_thesis_list(conn, thesis_name, table_name)
        
        # Insert stocks
        inserted_count = 0
        for stock_code, stock_name, thesis_description in stocks:
            if insert_stock_to_table(conn, table_name, stock_code, stock_name, thesis_description):
                inserted_count += 1
        
        # Update stock_count
        update_stock_count(conn, thesis_name)
        
        print(f"  ✓ {thesis_name} → {table_name} ({len(stocks)} stocks)")
    
    conn.close()
    
    # Build result summary
    result = {
        'input_file': str(json_path),
        'source_item_count': len(items),
        'unique_stock_count': len(unique_stocks),
        'unique_thesis_count': len(thesis_to_stocks),
        'missing_lookup_count': len(missing_stocks),
        'missing_stocks': missing_stocks,
        'thesis_to_table': thesis_to_table,
        'table_counts': {}
    }
    
    # Get actual table counts
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for thesis_name, table_name in thesis_to_table.items():
        cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
        result['table_counts'][thesis_name] = cursor.fetchone()[0]
    conn.close()
    
    return result


def write_summary_files(result: dict, output_dir: Path, timestamp: str):
    """Write JSON and MD summary files."""
    
    # JSON summary
    json_path = output_dir / f"thesis_insert_result_{timestamp}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    # MD summary
    md_path = output_dir / f"thesis_insert_result_{timestamp}.md"
    md_content = f"""# Thesis Insert Result

## 输入
- 文件: `{result['input_file']}`
- Source items: {result['source_item_count']}
- Unique stocks: {result['unique_stock_count']}
- Unique thesis: {result['unique_thesis_count']}
- Missing lookups: {result['missing_lookup_count']}

## 题材 → 表名映射

| thesis_name | table_name | stock_count |
|------------|------------|-------------|
"""
    for thesis_name, table_name in result['thesis_to_table'].items():
        count = result['table_counts'].get(thesis_name, 0)
        md_content += f"| {thesis_name} | {table_name} | {count} |\n"
    
    md_content += f"""
## 表统计

共 {len(result['thesis_to_table'])} 张 thesis_stocks_* 表。
"""
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description='Insert thesis stocks from candidates JSON')
    parser.add_argument('--input', required=True, help='Input JSON file path')
    parser.add_argument('--db', default='thesis.db', help='Database file (default: thesis.db)')
    args = parser.parse_args()
    
    # Resolve paths
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / args.db
    json_path = base_dir / args.input
    output_dir = base_dir / "output"
    
    # Validate
    if not json_path.exists():
        print(f"✗ JSON file not found: {json_path}")
        return 1
    
    if not db_path.exists():
        print(f"✗ Database not found: {db_path}")
        return 1
    
    # Process
    result = process_candidates(json_path, db_path)
    
    # Write summary
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_summary, md_summary = write_summary_files(result, output_dir, timestamp)
    
    print()
    print("=" * 60)
    print("✅ 写库完成")
    print(f"   题材数: {result['unique_thesis_count']}")
    print(f"   成分股数: {result['unique_stock_count']}")
    print(f"   摘要文件: {json_summary.name}")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    exit(main())