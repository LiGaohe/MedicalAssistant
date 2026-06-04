"""
检查数据库中缺失中间EMR结果的样本

中间EMR结果包括：
- emr_raw_draft (阶段2后的草稿)
- emr_pre_revision (阶段5前的EMR)
"""

import sys
sys.path.insert(0, 'd:/practice/MedicalAssisstant')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.models.benchmark import BenchmarkRun, BenchmarkBase
import json

# 连接benchmark数据库
DB_PATH = "sqlite:///d:/practice/MedicalAssisstant/data/database/benchmark.db"
engine = create_engine(DB_PATH)
Session = sessionmaker(bind=engine)
session = Session()

def is_empty_emr(emr_json):
    """检查EMR是否为空"""
    if emr_json is None:
        return True
    
    # 处理字符串类型的JSON（SQLite存储格式）
    if isinstance(emr_json, str):
        if not emr_json.strip():
            return True
        try:
            import json
            emr_json = json.loads(emr_json)
        except:
            return True
    
    if isinstance(emr_json, dict):
        # 检查是否有实质内容
        if not emr_json:
            return True
        # 检查是否只有空字段
        for key, value in emr_json.items():
            if value and (isinstance(value, str) and value.strip() or isinstance(value, dict) and value):
                return False
        return True
    return False

def check_missing_intermediate():
    """检查缺失中间结果的样本"""
    
    # 查询所有config_key='full'的记录（因为中间结果存储在full配置的记录中）
    # 使用子查询获取每个sample_id的最新记录（按id降序，因为id是自增的）
    from sqlalchemy import func, desc
    
    # 获取每个样本的最新记录ID（按id降序）
    subquery = session.query(
        BenchmarkRun.sample_id,
        func.max(BenchmarkRun.id).label('max_id')
    ).filter(
        BenchmarkRun.config_key == "full",
        BenchmarkRun.status == "completed"
    ).group_by(BenchmarkRun.sample_id).subquery()
    
    runs = session.query(BenchmarkRun).join(
        subquery,
        BenchmarkRun.id == subquery.c.max_id
    ).all()
    
    print(f"\n=== 检查中间EMR结果缺失情况（仅检查每个样本的最新记录） ===")
    print(f"总共 {len(runs)} 个样本的最新 'full' 配置记录\n")
    
    missing_raw_draft = []
    missing_pre_revision = []
    missing_both = []
    
    for run in runs:
        sample_id = run.sample_id
        created_at = run.created_at
        
        has_raw_draft = run.emr_raw_draft is not None and not is_empty_emr(run.emr_raw_draft)
        has_pre_revision = run.emr_pre_revision is not None and not is_empty_emr(run.emr_pre_revision)
        has_result = run.emr_result is not None and not is_empty_emr(run.emr_result)
        
        if not has_raw_draft and not has_pre_revision:
            missing_both.append({
                "sample_id": sample_id,
                "created_at": created_at,
                "has_result": has_result
            })
        elif not has_raw_draft:
            missing_raw_draft.append({
                "sample_id": sample_id,
                "created_at": created_at,
                "has_pre_revision": has_pre_revision,
                "has_result": has_result
            })
        elif not has_pre_revision:
            missing_pre_revision.append({
                "sample_id": sample_id,
                "created_at": created_at,
                "has_raw_draft": has_raw_draft,
                "has_result": has_result
            })
    
    # 输出结果
    print("=" * 60)
    print(f"缺失 emr_raw_draft 和 emr_pre_revision 的样本: {len(missing_both)} 个")
    print("=" * 60)
    for item in missing_both:
        print(f"  sample_id: {item['sample_id']}, created_at: {item['created_at']}, has_result: {item['has_result']}")
    
    print("\n" + "=" * 60)
    print(f"仅缺失 emr_raw_draft 的样本: {len(missing_raw_draft)} 个")
    print("=" * 60)
    for item in missing_raw_draft:
        print(f"  sample_id: {item['sample_id']}, created_at: {item['created_at']}")
    
    print("\n" + "=" * 60)
    print(f"仅缺失 emr_pre_revision 的样本: {len(missing_pre_revision)} 个")
    print("=" * 60)
    for item in missing_pre_revision:
        print(f"  sample_id: {item['sample_id']}, created_at: {item['created_at']}")
    
    # 汇总需要重新运行的样本ID
    all_missing = set()
    for item in missing_both:
        all_missing.add(item['sample_id'])
    for item in missing_raw_draft:
        all_missing.add(item['sample_id'])
    for item in missing_pre_revision:
        all_missing.add(item['sample_id'])
    
    print("\n" + "=" * 60)
    print(f"汇总：需要重新运行的样本ID ({len(all_missing)} 个)")
    print("=" * 60)
    print(sorted(list(all_missing)))
    
    # 输出JSON格式供后续使用
    if all_missing:
        print("\n" + "=" * 60)
        print("JSON格式样本ID列表（可直接用于 --sample-id 参数）:")
        print("=" * 60)
        print(json.dumps(sorted(list(all_missing)), indent=2))
    
    session.close()
    return all_missing

if __name__ == "__main__":
    check_missing_intermediate()