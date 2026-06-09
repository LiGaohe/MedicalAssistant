"""
检查benchmark数据库表结构
"""
import sqlite3
import os

def check_schema():
    db_path = "data/database/benchmark.db"

    if not os.path.exists(db_path):
        print(f"错误：数据库文件不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("数据库表结构检查")
    print("=" * 80)

    # 获取所有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()

    for table in tables:
        table_name = table[0]
        print(f"\n【表: {table_name}】")
        print("-" * 80)

        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        print("列信息:")
        for col in columns:
            print(f"  {col[1]} ({col[2]}) - {'NOT NULL' if col[3] else 'NULL'} - 默认值: {col[4]}")

        # 获取记录数
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"\n记录数: {count}")

        # 如果有记录，显示第一条
        if count > 0:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
            first_row = cursor.fetchone()
            print("\n第一条记录示例:")
            for i, col in enumerate(columns):
                value = first_row[i] if i < len(first_row) else "N/A"
                # 截断长文本
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                print(f"  {col[1]}: {value}")

    conn.close()

if __name__ == "__main__":
    check_schema()