import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.services.medical_record_pipeline import MedicalRecordPipeline
from backend.services.llm.llm_service import LLMService
from backend.models import Visit, TranscriptTurn
from backend.utils.logger import logger
import uuid

def test_emr_generation_with_logging():
    logger.info("=" * 60)
    logger.info("开始测试病历生成流程（带详细日志）")
    logger.info("=" * 60)
    
    db = SessionLocal()
    
    try:
        visit_id = f"test_visit_{uuid.uuid4().hex[:8]}"
        logger.info(f"创建测试就诊记录: {visit_id}")
        
        visit = Visit(
            visit_id=visit_id,
            patient_name="测试患者",
            visit_date="2026-04-17",
            audio_path="test_audio.wav",
            audio_duration=30.0
        )
        db.add(visit)
        
        test_transcript = [
            {"speaker": "spk0", "text": "您好，请问哪里不舒服？"},
            {"speaker": "spk1", "text": "医生，我这几天一直头疼，特别是早上起来的时候"},
            {"speaker": "spk0", "text": "头疼持续多长时间了？"},
            {"speaker": "spk1", "text": "大概三天了，一开始比较轻，现在越来越重"},
            {"speaker": "spk0", "text": "有没有恶心、呕吐的症状？"},
            {"speaker": "spk1", "text": "没有恶心呕吐，就是头疼"},
            {"speaker": "spk0", "text": "我给您量一下血压，一百四十五九十五，血压偏高"},
            {"speaker": "spk0", "text": "考虑是高血压引起的头疼，我给您开点降压药"},
            {"speaker": "spk0", "text": "注意休息，少吃盐，过一周再来复查"}
        ]
        
        logger.info(f"创建 {len(test_transcript)} 条测试对话")
        for i, turn_data in enumerate(test_transcript):
            turn = TranscriptTurn(
                visit_id=visit_id,
                turn_index=i,
                speaker=turn_data["speaker"],
                text=turn_data["text"],
                original_text=turn_data["text"],
                corrected_text=turn_data["text"],
                start_ms=i * 3000,
                end_ms=(i + 1) * 3000
            )
            db.add(turn)
        
        db.commit()
        logger.info("测试数据创建完成")
        
        logger.info("初始化病历生成流水线")
        llm_service = LLMService(db)
        pipeline = MedicalRecordPipeline(db, llm_service)
        
        logger.info("开始处理就诊记录")
        result = pipeline.process_visit(
            visit_id,
            use_llm=False,
            save_intermediate=True
        )
        
        logger.info("=" * 60)
        logger.info("处理结果:")
        logger.info(f"  状态: {result['status']}")
        logger.info(f"  证据数量: {result['evidence_count']}")
        logger.info(f"  规范化术语数量: {result['normalized_terms_count']}")
        logger.info(f"  抽取字段数量: {result['extracted_items_count']}")
        logger.info(f"  错误: {result['errors']}")
        
        if result['emr_record']:
            emr_json = result['emr_record']['emr_json']
            logger.info("  病历内容:")
            logger.info(f"    主观数据: {emr_json.get('subjective', {}).get('text', '暂无')}")
            logger.info(f"    客观数据: {emr_json.get('objective', {}).get('text', '暂无')}")
            logger.info(f"    评估: {emr_json.get('assessment', {}).get('text', '暂无')}")
            logger.info(f"    计划: {emr_json.get('plan', {}).get('text', '暂无')}")
        
        logger.info("=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)
        
        return result
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    result = test_emr_generation_with_logging()
    print("\n测试结果:")
    print(f"状态: {result['status']}")
    print(f"证据数量: {result['evidence_count']}")
    print(f"术语数量: {result['normalized_terms_count']}")
    print(f"字段数量: {result['extracted_items_count']}")
    if result['emr_record']:
        print("病历生成: 成功")
    else:
        print("病历生成: 失败")
