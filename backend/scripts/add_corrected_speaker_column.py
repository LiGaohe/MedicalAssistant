"""
数据库迁移脚本：添加 corrected_speaker 字段到 transcript_turns 表

运行方式：
    python -m backend.scripts.add_corrected_speaker_column
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from backend.database import engine, SessionLocal


def migrate():
    """添加 corrected_speaker 字段到 transcript_turns 表"""
    
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM pragma_table_info('transcript_turns') WHERE name='corrected_speaker'"
        ))
        exists = result.fetchone() is not None
        
        if exists:
            print("✓ corrected_speaker 字段已存在，无需迁移")
            return
        
        print("正在添加 corrected_speaker 字段...")
        conn.execute(text(
            "ALTER TABLE transcript_turns ADD COLUMN corrected_speaker VARCHAR"
        ))
        conn.commit()
        print("✓ corrected_speaker 字段添加成功")


if __name__ == "__main__":
    migrate()
