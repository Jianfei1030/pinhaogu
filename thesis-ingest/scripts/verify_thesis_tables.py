#!/usr/bin/env python3
"""
验证题材数据库表结构

验证内容：
1. thesis_list 表结构（字段和类型）
2. thesis_stocks_template 表结构（字段和类型）
3. 索引存在性
"""

import sqlite3
from pathlib import Path


def get_table_info(cursor: sqlite3.Cursor, table_name: str) -> list:
    """获取表的字段信息"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return cursor.fetchall()


def get_indexes(cursor: sqlite3.Cursor, table_name: str) -> list:
    """获取表的索引信息"""
    cursor.execute(f"PRAGMA index_list({table_name})")
    return cursor.fetchall()


def verify_thesis_list(cursor: sqlite3.Cursor) -> bool:
    """验证 thesis_list 表结构"""
    print("=" * 50)
    print("验证 thesis_list 表")
    print("=" * 50)

    expected_fields = {
        "id": "INTEGER",
        "thesis_name": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "stock_count": "INTEGER",
        "description": "TEXT",
    }

    expected_indexes = [
        "idx_thesis_list_name",
        "idx_thesis_list_updated",
    ]

    # 检查表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='thesis_list'
    """)
    if not cursor.fetchone():
        print("✗ thesis_list 表不存在")
        return False
    print("✓ thesis_list 表存在")

    # 检查字段
    table_info = get_table_info(cursor, "thesis_list")
    actual_fields = {row[1]: row[2] for row in table_info}

    print("\n字段检查:")
    all_fields_ok = True
    for field, expected_type in expected_fields.items():
        if field in actual_fields:
            actual_type = actual_fields[field]
            if expected_type in actual_type:
                print(f"  ✓ {field}: {actual_type}")
            else:
                print(f"  ✗ {field}: 期望 {expected_type}, 实际 {actual_type}")
                all_fields_ok = False
        else:
            print(f"  ✗ {field}: 字段缺失")
            all_fields_ok = False

    # 检查索引
    print("\n索引检查:")
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='thesis_list' AND name LIKE 'idx_%'
    """)
    actual_indexes = [row[0] for row in cursor.fetchall()]

    all_indexes_ok = True
    for idx in expected_indexes:
        if idx in actual_indexes:
            print(f"  ✓ {idx}")
        else:
            print(f"  ✗ {idx}: 索引缺失")
            all_indexes_ok = False

    return all_fields_ok and all_indexes_ok


def verify_thesis_stocks_template(cursor: sqlite3.Cursor) -> bool:
    """验证 thesis_stocks_template 表结构"""
    print("\n" + "=" * 50)
    print("验证 thesis_stocks_template 表")
    print("=" * 50)

    expected_fields = {
        "id": "INTEGER",
        "stock_code": "TEXT",
        "stock_name": "TEXT",
        "thesis_description": "TEXT",
        "created_at": "TEXT",
    }

    expected_indexes = [
        "idx_template_code",
        "idx_template_name",
    ]

    # 检查表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='thesis_stocks_template'
    """)
    if not cursor.fetchone():
        print("✗ thesis_stocks_template 表不存在")
        return False
    print("✓ thesis_stocks_template 表存在")

    # 检查字段
    table_info = get_table_info(cursor, "thesis_stocks_template")
    actual_fields = {row[1]: row[2] for row in table_info}

    print("\n字段检查:")
    all_fields_ok = True
    for field, expected_type in expected_fields.items():
        if field in actual_fields:
            actual_type = actual_fields[field]
            if expected_type in actual_type:
                print(f"  ✓ {field}: {actual_type}")
            else:
                print(f"  ✗ {field}: 期望 {expected_type}, 实际 {actual_type}")
                all_fields_ok = False
        else:
            print(f"  ✗ {field}: 字段缺失")
            all_fields_ok = False

    # 检查 UNIQUE 约束
    print("\n约束检查:")
    # PRAGMA table_info 返回的 pk 字段（第6列）表示是否为主键或唯一约束的一部分
    for row in table_info:
        if row[1] == "stock_code" and row[5]:  # row[5] 是 pk 字段，非零表示有约束
            print(f"  ✓ stock_code 有 UNIQUE 约束")
            break
    else:
        # 检查是否有 UNIQUE 索引
        cursor.execute("PRAGMA index_list(thesis_stocks_template)")
        indexes = cursor.fetchall()
        for idx in indexes:
            if idx[2]:  # unique 字段
                cursor.execute(f"PRAGMA index_info({idx[1]})")
                idx_cols = cursor.fetchall()
                for col in idx_cols:
                    if col[2] == "stock_code":
                        print(f"  ✓ stock_code 有 UNIQUE 约束 (via index {idx[1]})")
                        break
                break
        else:
            print(f"  ✗ stock_code 缺少 UNIQUE 约束")
            all_fields_ok = False

    # 检查索引
    print("\n索引检查:")
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='thesis_stocks_template' AND name LIKE 'idx_%'
    """)
    actual_indexes = [row[0] for row in cursor.fetchall()]

    all_indexes_ok = True
    for idx in expected_indexes:
        if idx in actual_indexes:
            print(f"  ✓ {idx}")
        else:
            print(f"  ✗ {idx}: 索引缺失")
            all_indexes_ok = False

    return all_fields_ok and all_indexes_ok


def main():
    # 路径配置
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    db_path = project_root / "thesis.db"

    print(f"数据库文件: {db_path}")
    print(f"文件存在: {db_path.exists()}")

    if not db_path.exists():
        print("✗ 数据库文件不存在")
        return 1

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 验证 thesis_list
        thesis_list_ok = verify_thesis_list(cursor)

        # 验证 thesis_stocks_template
        template_ok = verify_thesis_stocks_template(cursor)

        # 总结
        print("\n" + "=" * 50)
        print("验证结果")
        print("=" * 50)

        if thesis_list_ok and template_ok:
            print("\n✓ 验证通过")
            print("  - thesis_list 表结构正确")
            print("  - thesis_stocks_template 表结构正确")
            print("  - 所有索引已创建")
            return 0
        else:
            print("\n✗ 验证失败")
            if not thesis_list_ok:
                print("  - thesis_list 表存在问题")
            if not template_ok:
                print("  - thesis_stocks_template 表存在问题")
            return 1

    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())