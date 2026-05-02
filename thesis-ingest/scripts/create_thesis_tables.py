#!/usr/bin/env python3
"""
创建题材数据库表

功能：
1. 读取 thesis_schema.sql 并执行
2. 创建 thesis.db 数据库文件
3. 创建 thesis_list 表
4. 创建 thesis_stocks_template 表（模板）
"""

import sqlite3
from pathlib import Path


def main():
    # 路径配置
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    schema_path = project_root / "database" / "thesis_schema.sql"
    db_path = project_root / "thesis.db"

    print(f"项目根目录: {project_root}")
    print(f"Schema 文件: {schema_path}")
    print(f"数据库文件: {db_path}")
    print("-" * 50)

    # 检查 schema 文件
    if not schema_path.exists():
        print(f"错误: Schema 文件不存在: {schema_path}")
        return 1

    # 读取 schema
    print(f"读取 Schema...")
    schema_sql = schema_path.read_text(encoding="utf-8")

    # 创建数据库连接
    print(f"创建数据库连接...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 执行 schema
        print(f"执行 Schema...")
        cursor.executescript(schema_sql)
        conn.commit()
        print(f"Schema 执行成功")

        # 验证表创建
        print("-" * 50)
        print("验证表创建:")

        # 检查 thesis_list 表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='thesis_list'
        """)
        if cursor.fetchone():
            print("✓ thesis_list 表创建成功")
        else:
            print("✗ thesis_list 表创建失败")
            return 1

        # 检查 thesis_stocks_template 表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='thesis_stocks_template'
        """)
        if cursor.fetchone():
            print("✓ thesis_stocks_template 表创建成功")
        else:
            print("✗ thesis_stocks_template 表创建失败")
            return 1

        # 检查索引
        print("-" * 50)
        print("验证索引创建:")

        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name LIKE 'idx_%'
            ORDER BY name
        """)
        indexes = cursor.fetchall()
        for idx in indexes:
            print(f"✓ 索引: {idx[0]}")

        # 显示数据库文件信息
        print("-" * 50)
        print(f"数据库创建完成: {db_path}")
        print(f"文件大小: {db_path.stat().st_size} bytes")

        return 0

    except Exception as e:
        print(f"错误: {e}")
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())