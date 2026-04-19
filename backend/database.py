from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from .config import settings
from .utils.logger import logger


Path("data/database").mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_table_columns(table_name: str) -> set:
    """获取数据库表中已存在的列名"""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    columns = inspector.get_columns(table_name)
    return {col['name'] for col in columns}


def _get_model_columns(model_class) -> dict:
    """获取模型定义中的列信息"""
    columns = {}
    for col in model_class.__table__.columns:
        columns[col.name] = col.type
    return columns


def _add_missing_columns(model_class):
    """检测并添加缺失的列"""
    table_name = model_class.__tablename__
    existing_columns = _get_table_columns(table_name)
    model_columns = _get_model_columns(model_class)
    
    missing_columns = set(model_columns.keys()) - existing_columns
    
    if not missing_columns:
        return
    
    logger.info(f"表 {table_name} 缺失列: {missing_columns}")
    
    with engine.connect() as conn:
        for col_name in missing_columns:
            col_type = model_columns[col_name]
            type_str = _sqlalchemy_type_to_sql(col_type)
            
            try:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {type_str}"
                conn.execute(text(sql))
                conn.commit()
                logger.info(f"已添加列: {table_name}.{col_name} ({type_str})")
            except Exception as e:
                logger.warning(f"添加列失败 {table_name}.{col_name}: {e}")


def _sqlalchemy_type_to_sql(col_type) -> str:
    """将SQLAlchemy类型转换为SQL类型字符串"""
    type_name = type(col_type).__name__.upper()
    
    type_mapping = {
        'INTEGER': 'INTEGER',
        'STRING': 'TEXT',
        'TEXT': 'TEXT',
        'FLOAT': 'REAL',
        'BOOLEAN': 'INTEGER',
        'DATETIME': 'TEXT',
        'JSON': 'TEXT',
    }
    
    if type_name in type_mapping:
        return type_mapping[type_name]
    
    if hasattr(col_type, 'length') and col_type.length:
        return f'VARCHAR({col_type.length})'
    
    return 'TEXT'


def init_db():
    from .models import (
        Visit, TranscriptTurn, Task, ASRCorrection, LLMConfig,
        EvidenceSpan, NormalizedTerm, ExtractedItem, EMRRecord
    )
    
    Base.metadata.create_all(bind=engine)
    
    models = [
        Visit, TranscriptTurn, Task, ASRCorrection, LLMConfig,
        EvidenceSpan, NormalizedTerm, ExtractedItem, EMRRecord
    ]
    
    for model in models:
        try:
            _add_missing_columns(model)
        except Exception as e:
            logger.warning(f"检查表 {model.__tablename__} 时出错: {e}")
    
    logger.info("数据库初始化完成")
