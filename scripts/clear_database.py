"""
清理数据库脚本

删除转写结果和病历记录，保留大模型配置
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from backend.database import engine, SessionLocal
from backend.utils.logger import logger


def clear_database(keep_llm_config: bool = True):
    """
    清理数据库中的转写结果和病历记录
    
    Args:
        keep_llm_config: 是否保留大模型配置，默认True
    """
    tables_to_clear = [
        "evaluation_records",
        "emr_records",
        "extracted_items",
        "normalized_terms",
        "evidence_spans",
        "asr_corrections",
        "tasks",
        "transcript_turns",
        "visits",
    ]
    
    db = SessionLocal()
    try:
        with engine.connect() as conn:
            for table in tables_to_clear:
                try:
                    result = conn.execute(text(f"DELETE FROM {table}"))
                    conn.commit()
                    logger.info(f"已清理表 {table}，删除 {result.rowcount} 条记录")
                except Exception as e:
                    logger.warning(f"清理表 {table} 失败: {e}")
        
        if not keep_llm_config:
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("DELETE FROM llm_configs"))
                    conn.commit()
                    logger.info(f"已清理表 llm_configs，删除 {result.rowcount} 条记录")
            except Exception as e:
                logger.warning(f"清理表 llm_configs 失败: {e}")
        
        logger.info("数据库清理完成")
        print("\n✅ 数据库清理完成！")
        print(f"   - 已删除转写结果和病历记录")
        if keep_llm_config:
            print(f"   - 已保留大模型配置")
        
    except Exception as e:
        logger.error(f"数据库清理失败: {e}")
        print(f"\n❌ 数据库清理失败: {e}")
    finally:
        db.close()


def show_stats():
    """显示数据库统计信息"""
    tables = [
        ("visits", "就诊记录"),
        ("transcript_turns", "转写对话"),
        ("emr_records", "病历记录"),
        ("evaluation_records", "评估记录"),
        ("evidence_spans", "证据片段"),
        ("normalized_terms", "规范化术语"),
        ("extracted_items", "抽取要素"),
        ("llm_configs", "大模型配置"),
    ]
    
    print("\n📊 数据库统计信息:")
    print("-" * 40)
    
    with engine.connect() as conn:
        for table_name, display_name in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                print(f"   {display_name}: {count} 条")
            except Exception:
                print(f"   {display_name}: 表不存在")
    
    print("-" * 40)


if __name__ == "__main__":
    print("=" * 50)
    print("数据库清理工具")
    print("=" * 50)
    
    show_stats()
    
    confirm = input("\n⚠️  确定要清理数据库吗？(yes/no): ")
    
    if confirm.lower() == "yes":
        clear_database(keep_llm_config=True)
        show_stats()
    else:
        print("\n已取消操作")
