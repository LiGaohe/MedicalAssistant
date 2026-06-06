"""
Benchmark 实验数据库模型

独立于主项目 medical.db，用于存储量化评估实验运行记录。
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

BenchmarkBase = declarative_base()


class BenchmarkRun(BenchmarkBase):
    __tablename__ = "benchmark_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_id = Column(String(50), nullable=False, index=True)
    config_key = Column(String(50), nullable=False, index=True)
    visit_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="running")
    emr_raw_draft = Column(JSON, nullable=True)
    emr_pre_revision = Column(JSON, nullable=True)
    emr_result = Column(JSON, nullable=True)
    emr_no_term_norm = Column(JSON, nullable=True)
    emr_no_hallucination = Column(JSON, nullable=True)
    hallucination_result = Column(JSON, nullable=True)
    verification_issues = Column(JSON, nullable=True)
    key_facts = Column(JSON, nullable=True)
    elapsed_seconds = Column(Float, nullable=True)
    llm_call_count = Column(Integer, nullable=False, default=0)
    char_count = Column(Integer, nullable=False, default=0)
    token_count = Column(Integer, nullable=False, default=0)
    stage_breakdown = Column(JSON, nullable=True)  # 新增：保存每个阶段的LLM调用统计
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    stages = relationship("BenchmarkStage", back_populates="run", cascade="all, delete-orphan")
    evaluations = relationship("BenchmarkEvaluation", back_populates="run", cascade="all, delete-orphan")
    llm_calls = relationship("BenchmarkLLMCall", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_benchmark_runs_sample_config", "sample_id", "config_key"),
    )


class BenchmarkStage(BenchmarkBase):
    __tablename__ = "benchmark_stages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("benchmark_runs.id"), nullable=False, index=True)
    stage_name = Column(String(100), nullable=False)
    stage_index = Column(Integer, nullable=False)
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    elapsed_seconds = Column(Float, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    run = relationship("BenchmarkRun", back_populates="stages")


class BenchmarkEvaluation(BenchmarkBase):
    __tablename__ = "benchmark_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("benchmark_runs.id"), nullable=False, index=True)
    consistency_result = Column(JSON, nullable=True)
    completeness_result = Column(JSON, nullable=True)
    quality_result = Column(JSON, nullable=True)
    safety_result = Column(JSON, nullable=True)
    support_rate = Column(Float, nullable=True)
    hallucination_rate = Column(Float, nullable=True)
    recall_rate = Column(Float, nullable=True)
    omission_rate = Column(Float, nullable=True)
    structure_completeness = Column(Float, nullable=True)
    field_missing_rate = Column(Float, nullable=True)
    diagnosis_match = Column(Boolean, nullable=True)
    overall_score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    run = relationship("BenchmarkRun", back_populates="evaluations")
    llm_calls = relationship("BenchmarkLLMCall", back_populates="evaluation", cascade="all, delete-orphan")


class BenchmarkLLMCall(BenchmarkBase):
    __tablename__ = "benchmark_llm_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("benchmark_runs.id"), nullable=False, index=True)
    evaluation_id = Column(Integer, ForeignKey("benchmark_evaluations.id"), nullable=True, index=True)
    stage = Column(String(100), nullable=False)
    evaluator = Column(String(100), nullable=True)
    prompt_length = Column(Integer, nullable=False)
    response_length = Column(Integer, nullable=False)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    run = relationship("BenchmarkRun", back_populates="llm_calls")
    evaluation = relationship("BenchmarkEvaluation", back_populates="llm_calls")


class BenchmarkSummary(BenchmarkBase):
    __tablename__ = "benchmark_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(50), nullable=False, index=True)
    total_samples = Column(Integer, nullable=False)
    success_samples = Column(Integer, nullable=False)
    failed_samples = Column(Integer, nullable=False)
    avg_elapsed_seconds = Column(Float, nullable=True)
    avg_llm_call_count = Column(Float, nullable=True)
    avg_char_count = Column(Float, nullable=True)
    avg_support_rate = Column(Float, nullable=True)
    avg_hallucination_rate = Column(Float, nullable=True)
    avg_recall_rate = Column(Float, nullable=True)
    avg_omission_rate = Column(Float, nullable=True)
    avg_structure_completeness = Column(Float, nullable=True)
    avg_field_missing_rate = Column(Float, nullable=True)
    avg_diagnosis_match = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())