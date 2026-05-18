import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.database import SessionLocal
from backend.models import Visit, TranscriptTurn
from backend.services.llm.llm_service import LLMService
from backend.services.llm_pipeline_service import LLMPipelineService
from backend.services.evaluation.benchmark_pipeline import BenchmarkPipeline
from backend.services.evaluation.evaluation_normalizer import EvaluationNormalizer
from backend.services.evaluation.imcs_adapter import IMCSAdapter, IMCS_FIELDS

DATASET_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'text', 'imcs21-dataset', 'test.json')


def create_visit_from_imcs(db, sample_id: str, sample: dict) -> str:
    visit_id = f"benchmark_{sample_id}"
    
    existing = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if existing:
        db.query(TranscriptTurn).filter(TranscriptTurn.visit_id == visit_id).delete()
        db.delete(existing)
        db.commit()
    
    visit = Visit(
        visit_id=visit_id,
        patient_name=f"患者_{sample_id}",
        audio_path=f"benchmark/{sample_id}",
        status="pending",
        language="zh"
    )
    db.add(visit)
    db.commit()
    
    turn_index = 0
    
    if sample.get("self_report"):
        turn = TranscriptTurn(
            visit_id=visit_id,
            turn_index=turn_index,
            speaker="患者",
            text=sample["self_report"],
            original_text=sample["self_report"],
            corrected_text=sample["self_report"],
            start_ms=turn_index * 3000,
            end_ms=(turn_index + 1) * 3000
        )
        db.add(turn)
        turn_index += 1
    
    for dialogue_turn in sample.get("dialogue", []):
        speaker = dialogue_turn.get("speaker", "")
        sentence = dialogue_turn.get("sentence", "")
        
        if speaker and sentence:
            turn = TranscriptTurn(
                visit_id=visit_id,
                turn_index=turn_index,
                speaker=speaker,
                text=sentence,
                original_text=sentence,
                corrected_text=sentence,
                start_ms=turn_index * 3000,
                end_ms=(turn_index + 1) * 3000
            )
            db.add(turn)
            turn_index += 1
    
    db.commit()
    print(f"  创建就诊记录: {visit_id}, 共 {turn_index} 条对话")
    return visit_id


def convert_soap_to_imcs(emr_result: dict) -> dict:
    imcs_report = {}
    
    subjective = emr_result.get("subjective", {})
    if isinstance(subjective, dict):
        imcs_report["主诉"] = subjective.get("chief_complaint", "")
        if isinstance(imcs_report["主诉"], dict):
            imcs_report["主诉"] = imcs_report["主诉"].get("value", "")
        
        imcs_report["现病史"] = subjective.get("history_present_illness", "")
        if isinstance(imcs_report["现病史"], dict):
            imcs_report["现病史"] = imcs_report["现病史"].get("value", "")
        
        imcs_report["既往史"] = subjective.get("past_history", "")
        if isinstance(imcs_report["既往史"], dict):
            imcs_report["既往史"] = imcs_report["既往史"].get("value", "")
    
    objective = emr_result.get("objective", {})
    if isinstance(objective, dict):
        imcs_report["辅助检查"] = objective.get("auxiliary_examination", "")
        if isinstance(imcs_report["辅助检查"], dict):
            imcs_report["辅助检查"] = imcs_report["辅助检查"].get("value", "")
    
    assessment = emr_result.get("assessment", {})
    if isinstance(assessment, dict):
        imcs_report["诊断"] = assessment.get("diagnosis", "")
        if isinstance(imcs_report["诊断"], dict):
            imcs_report["诊断"] = imcs_report["诊断"].get("value", "")
    
    plan = emr_result.get("plan", {})
    if isinstance(plan, dict):
        imcs_report["建议"] = plan.get("advice", "")
        if isinstance(imcs_report["建议"], dict):
            imcs_report["建议"] = imcs_report["建议"].get("value", "")
    
    for field in IMCS_FIELDS:
        if field not in imcs_report:
            imcs_report[field] = ""
        elif imcs_report[field] is None:
            imcs_report[field] = ""
    
    return imcs_report


def main():
    print("\n" + "=" * 70)
    print("  基准评估测试 - 使用项目完整流程生成病历")
    print("=" * 70)
    
    adapter = IMCSAdapter(DATASET_PATH)
    sample_ids = adapter.get_sample_ids()
    test_id = sample_ids[0]
    
    print(f"\n测试样本ID: {test_id}")
    
    sample = adapter.dataset.get(test_id)
    if not sample:
        print(f"错误: 样本 {test_id} 不存在")
        return
    
    references = adapter.get_reference_reports(test_id)
    print(f"\n── 参考报告 1 ──")
    for field, value in references[0].items():
        print(f"  {field}：{value}")
    
    db = SessionLocal()
    
    try:
        print(f"\n>>> 步骤1: 创建就诊记录和对话数据")
        visit_id = create_visit_from_imcs(db, test_id, sample)
        
        print(f"\n>>> 步骤2: 调用项目LLM流水线生成病历")
        llm_service = LLMService(db)
        pipeline = LLMPipelineService(db, llm_service, language="zh")
        
        start_time = time.time()
        result = pipeline.process_transcript(visit_id, save_evidence=False)
        elapsed = time.time() - start_time
        
        print(f"  处理状态: {result.get('status')}")
        print(f"  处理耗时: {elapsed:.2f}秒")
        
        if result.get("status") != "completed":
            print(f"  错误: {result.get('error', '未知错误')}")
            return
        
        emr_result = result.get("emr_result", {})
        if not emr_result:
            print("  错误: 未生成病历")
            return
        
        print(f"\n>>> 步骤3: 转换病历格式 (SOAP → IMCS)")
        prediction = convert_soap_to_imcs(emr_result)
        
        print(f"\n── 项目生成的病历 ──")
        for field, value in prediction.items():
            print(f"  {field}：{value}")
        
        print(f"\n>>> 步骤4: 运行三层评估")
        normalizer = EvaluationNormalizer()
        benchmark = BenchmarkPipeline(normalizer=normalizer, compute_bertscore=True)
        
        eval_result = benchmark.run_single_sample(
            sample_id=test_id,
            dataset_path=DATASET_PATH,
            prediction=prediction
        )
        
        dialogue_text = adapter.get_dialogue_text(test_id)
        eval_result["input_dialogue"] = dialogue_text
        eval_result["self_report"] = sample.get("self_report", "")
        eval_result["dialogue_turns"] = sample.get("dialogue", [])
        
        output_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'logs', 'benchmark_full_result.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(eval_result, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n详细结果已保存到: {output_path}")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
