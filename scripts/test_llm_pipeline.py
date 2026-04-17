"""
测试多阶段LLM处理流程
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.services.llm_pipeline_service import LLMPipelineService
from backend.services.llm.llm_service import LLMService
from backend.models import TranscriptTurn, Visit
from backend.config import settings


def create_test_data(db):
    """创建测试数据"""
    existing_visit = db.query(Visit).filter(Visit.visit_id == "test_pipeline_001").first()
    existing_turns = db.query(TranscriptTurn).filter(
        TranscriptTurn.visit_id == "test_pipeline_001"
    ).count()
    
    if existing_visit and existing_turns > 0:
        print(f"测试数据已存在（{existing_turns}条对话），跳过创建")
        return
    
    if not existing_visit:
        visit = Visit(visit_id="test_pipeline_001", audio_path="test_audio.wav")
        db.add(visit)
        db.commit()
    
    turns_data = [
        {"turn_index": 0, "speaker": "spk0", "text": "你好，请问哪里不舒服？", "start_ms": 0, "end_ms": 2000},
        {"turn_index": 1, "speaker": "spk1", "text": "医生，我这几天一直头疼，特别是早上起来的时候。", "start_ms": 2500, "end_ms": 5000},
        {"turn_index": 2, "speaker": "spk0", "text": "头疼持续多长时间了？有没有恶心、呕吐的症状？", "start_ms": 5500, "end_ms": 8000},
        {"turn_index": 3, "speaker": "spk1", "text": "大概三天了，有时候会恶心，但没有呕吐。", "start_ms": 8500, "end_ms": 11000},
        {"turn_index": 4, "speaker": "spk0", "text": "我给您量一下血压。一百四十五九十五，血压偏高。", "start_ms": 11500, "end_ms": 15000},
        {"turn_index": 5, "speaker": "spk1", "text": "血压高会引起头疼吗？", "start_ms": 15500, "end_ms": 17500},
        {"turn_index": 6, "speaker": "spk0", "text": "是的，考虑是高血压引起的头疼。我给您开点降压药，每天一次，早上吃。", "start_ms": 18000, "end_ms": 23000},
        {"turn_index": 7, "speaker": "spk1", "text": "好的，需要注意什么吗？", "start_ms": 23500, "end_ms": 25500},
        {"turn_index": 8, "speaker": "spk0", "text": "注意低盐饮食，避免熬夜，一周后复查。", "start_ms": 26000, "end_ms": 29000},
        {"turn_index": 9, "speaker": "spk1", "text": "好的，谢谢医生。", "start_ms": 29500, "end_ms": 31000},
    ]
    
    for turn_data in turns_data:
        turn = TranscriptTurn(
            visit_id="test_pipeline_001",
            turn_index=turn_data["turn_index"],
            speaker=turn_data["speaker"],
            text=turn_data["text"],
            start_ms=turn_data["start_ms"],
            end_ms=turn_data["end_ms"],
            confidence=0.95
        )
        db.add(turn)
    
    db.commit()
    print(f"创建测试数据完成，共 {len(turns_data)} 条对话")


def test_pipeline():
    """测试多阶段LLM处理"""
    db = SessionLocal()
    
    try:
        existing_turns = db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == "test_pipeline_001"
        ).first()
        
        if not existing_turns:
            create_test_data(db)
        else:
            print("测试数据已存在，跳过创建")
        
        print(f"\n当前配置:")
        print(f"  LLM_DEBUG_MODE: {settings.LLM_DEBUG_MODE}")
        print(f"  LLM_SEGMENT_TURNS: {settings.LLM_SEGMENT_TURNS}")
        
        llm_service = LLMService(db)
        
        if llm_service.adapters:
            print(f"\n可用的LLM适配器: {list(llm_service.adapters.keys())}")
        else:
            print("\n警告: 没有配置LLM适配器")
            print("请先通过前端配置LLM，或开启DEBUG模式手动输入结果")
        
        pipeline = LLMPipelineService(db, llm_service)
        
        print("\n" + "=" * 60)
        print("开始多阶段LLM处理...")
        print("=" * 60)
        
        result = pipeline.process_transcript("test_pipeline_001")
        
        print("\n" + "=" * 60)
        print("处理结果:")
        print("=" * 60)
        print(f"状态: {result['status']}")
        
        if result.get('role_mapping'):
            print(f"\n角色映射:")
            for speaker, role in result['role_mapping'].items():
                print(f"  {speaker}: {role}")
        
        if result.get('emr_result'):
            emr = result['emr_result']
            print(f"\n生成的病历:")
            print(f"  主观数据: {emr.get('subjective', {}).get('text', '')[:100]}...")
            print(f"  客观数据: {emr.get('objective', {}).get('text', '')[:100]}...")
            print(f"  评估: {emr.get('assessment', {}).get('text', '')[:100]}...")
            print(f"  计划: {emr.get('plan', {}).get('text', '')[:100]}...")
        
        return result
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        db.close()


def test_debug_mode():
    """测试调试模式"""
    print("\n" + "=" * 60)
    print("测试调试模式")
    print("=" * 60)
    
    settings.LLM_DEBUG_MODE = True
    print(f"已开启DEBUG模式: LLM_DEBUG_MODE = {settings.LLM_DEBUG_MODE}")
    
    test_pipeline()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试多阶段LLM处理")
    parser.add_argument("--debug", action="store_true", help="开启调试模式")
    args = parser.parse_args()
    
    if args.debug:
        test_debug_mode()
    else:
        test_pipeline()
