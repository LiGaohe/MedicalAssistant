"""
Benchmark 数据库初始化模块

独立于主项目 database.py，使用固定的 benchmark.db 路径。
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.benchmark import BenchmarkBase

BENCHMARK_DATABASE_URL = "sqlite:///data/database/benchmark.db"


def get_benchmark_db_path() -> Path:
    return Path("data/database/benchmark.db")


def init_benchmark_db():
    db_path = get_benchmark_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        BENCHMARK_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

    BenchmarkBase.metadata.create_all(bind=engine)

    return engine


BenchmarkEngine = None
BenchmarkSessionLocal = None


def get_benchmark_engine():
    global BenchmarkEngine
    if BenchmarkEngine is None:
        BenchmarkEngine = init_benchmark_db()
    return BenchmarkEngine


def get_benchmark_session():
    global BenchmarkSessionLocal
    if BenchmarkSessionLocal is None:
        engine = get_benchmark_engine()
        BenchmarkSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return BenchmarkSessionLocal()


def close_benchmark_session(session):
    if session:
        session.close()


def reset_benchmark_engine():
    global BenchmarkEngine, BenchmarkSessionLocal
    BenchmarkEngine = None
    BenchmarkSessionLocal = None