"""
Benchmark 数据库迁移脚本

安全添加新字段到现有表，不删除现有数据。

用法:
  python scripts/migrate_benchmark_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from backend.benchmark_db import BENCHMARK_DATABASE_URL, get_benchmark_db_path
from backend.models.benchmark import BenchmarkRun
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


NEW_COLUMNS = [
    ("emr_raw_draft", "JSON"),
    ("emr_pre_revision", "JSON"),
    ("key_facts", "JSON"),
]


def check_column_exists(engine, table_name: str, column_name: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        columns = [row[1] for row in result.fetchall()]
        return column_name in columns


def add_column_if_not_exists(engine, table_name: str, column_name: str, column_type: str):
    if check_column_exists(engine, table_name, column_name):
        logger.info(f"列 {column_name} 已存在于表 {table_name}, 跳过")
        return False
    
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
        conn.commit()
    logger.info(f"已添加列 {column_name} 到表 {table_name}")
    return True


def migrate():
    db_path = get_benchmark_db_path()
    if not db_path.exists():
        logger.info(f"数据库文件不存在: {db_path}, 将在首次运行时创建")
        return
    
    logger.info(f"开始迁移数据库: {db_path}")
    
    engine = create_engine(BENCHMARK_DATABASE_URL, connect_args={"check_same_thread": False})
    
    table_name = BenchmarkRun.__tablename__
    
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"))
        if not result.fetchone():
            logger.info(f"表 {table_name} 不存在, 将在首次运行时创建")
            return
    
    added_count = 0
    for column_name, column_type in NEW_COLUMNS:
        if add_column_if_not_exists(engine, table_name, column_name, column_type):
            added_count += 1
    
    if added_count == 0:
        logger.info("所有新列已存在，无需迁移")
    else:
        logger.info(f"迁移完成，添加了 {added_count} 个新列")
    
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        count = result.fetchone()[0]
        logger.info(f"表 {table_name} 现有数据: {count} 条记录")


if __name__ == "__main__":
    migrate()