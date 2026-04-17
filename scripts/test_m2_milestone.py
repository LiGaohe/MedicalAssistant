import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, init_db
from backend.models import Visit, TranscriptTurn, LLMConfig
from backend.services.medical_record_pipeline import MedicalRecordPipeline
from backend.services.llm.llm_service import LLMService


def create_test_data(db):
    visit = Visit(
        visit_id="test_visit_001",
        patient_name="张三",
        visit_date="2026-04-17",
        audio_path="test_audio.wav",
        status="transcribed"
    )
    db.add(visit)
    
    turns_data = [
        {"turn_index": 0, "speaker": "spk0", "text": "你好，请问哪里不舒服？", "start_ms": 0, "end_ms": 2000},
        {"turn_index": 1, "speaker": "spk1", "text": "医生，我这几天一直头疼，特别是早上起来的时候。", "start_ms": 2500, "end_ms": 5500},
        {"turn_index": 2, "speaker": "spk0", "text": "头疼持续多长时间了？", "start_ms": 6000, "end_ms": 7500},
        {"turn_index": 3, "speaker": "spk1", "text": "大概三天了，一开始只是轻微的，现在越来越严重。", "start_ms": 8000, "end_ms": 11000},
        {"turn_index": 4, "speaker": "spk0", "text": "有没有恶心、呕吐的症状？", "start_ms": 11500, "end_ms": 13000},
        {"turn_index": 5, "speaker": "spk1", "text": "有时候会感到恶心，但没有呕吐。", "start_ms": 13500, "end_ms": 15500},
        {"turn_index": 6, "speaker": "spk0", "text": "血压一百四十五九十五，有点偏高。我给你开点降压药，注意休息，少吃咸的食物。", "start_ms": 16000, "end_ms": 20000},
        {"turn_index": 7, "speaker": "spk1", "text": "好的，还需要注意什么吗？", "start_ms": 20500, "end_ms": 21500},
        {"turn_index": 8, "speaker": "spk0", "text": "一周后复查，如果头疼加重及时就诊。", "start_ms": 22000, "end_ms": 24000},
    ]
    
    for turn_data in turns_data:
        turn = TranscriptTurn(
            visit_id="test_visit_001",
            **turn_data
        )
        db.add(turn)
    
    db.commit()
    print("✅ 测试数据创建成功")
    return visit


def test_m2_milestone():
    print("=" * 60)
    print("M2 里程碑测试：文本到病历")
    print("=" * 60)
    
    init_db()
    db = SessionLocal()
    
    try:
        visit = db.query(Visit).filter(Visit.visit_id == "test_visit_001").first()
        if not visit:
            visit = create_test_data(db)
        
        print("\n📋 测试数据:")
        print(f"就诊ID: {visit.visit_id}")
        print(f"患者姓名: {visit.patient_name}")
        print(f"就诊日期: {visit.visit_date}")
        
        turns = db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit.visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        print(f"\n对话轮次: {len(turns)}")
        for turn in turns:
            print(f"  [{turn.turn_index}] {turn.speaker}: {turn.text}")
        
        llm_config = db.query(LLMConfig).filter(LLMConfig.is_active == True).first()
        llm_service = LLMService(db) if llm_config else None
        
        if llm_service:
            print("\n✅ LLM服务已配置")
        else:
            print("\n⚠️  LLM服务未配置，将使用规则方法")
        
        pipeline = MedicalRecordPipeline(db, llm_service)
        
        print("\n" + "=" * 60)
        print("开始处理...")
        print("=" * 60)
        
        result = pipeline.process_visit(
            visit.visit_id,
            use_llm=(llm_service is not None),
            save_intermediate=True
        )
        
        print("\n📊 处理结果:")
        print(f"状态: {result['status']}")
        print(f"证据数量: {result['evidence_count']}")
        print(f"规范化术语数量: {result['normalized_terms_count']}")
        print(f"抽取要素数量: {result['extracted_items_count']}")
        
        if result['errors']:
            print(f"\n❌ 错误: {result['errors']}")
        
        if result['emr_record']:
            print("\n📄 生成的病历:")
            emr = result['emr_record']
            print(f"版本: {emr.get('version', 1)}")
            print(f"类型: {emr.get('record_type', 'system_draft')}")
            
            emr_json = emr.get('emr_json', {})
            
            print("\n【主观数据】")
            subjective = emr_json.get('subjective', {})
            print(subjective.get('text', '无'))
            
            print("\n【客观数据】")
            objective = emr_json.get('objective', {})
            print(objective.get('text', '无'))
            
            print("\n【评估】")
            assessment = emr_json.get('assessment', {})
            print(assessment.get('text', '无'))
            
            print("\n【计划】")
            plan = emr_json.get('plan', {})
            print(plan.get('text', '无'))
        
        print("\n" + "=" * 60)
        print("✅ M2 里程碑测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    test_m2_milestone()
