"""
为 Benchmark 数据库添加 Token 字段

运行方式:
  python scripts/add_token_fields.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/database/benchmark.db")


def add_token_fields():
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(benchmark_llm_calls)")
    columns = [col[1] for col in cursor.fetchall()]

    new_columns = [
        ("prompt_tokens", "INTEGER"),
        ("completion_tokens", "INTEGER"),
        ("total_tokens", "INTEGER"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in columns:
            print(f"添加字段: {col_name}")
            cursor.execute(f"ALTER TABLE benchmark_llm_calls ADD COLUMN {col_name} {col_type}")
        else:
            print(f"字段已存在: {col_name}")

    conn.commit()
    conn.close()
    print("数据库更新完成")


if __name__ == "__main__":
    add_token_fields()