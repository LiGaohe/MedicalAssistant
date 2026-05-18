import json
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from .reference_based_evaluator import ReferenceBasedEvaluator
from .evaluation_normalizer import EvaluationNormalizer
from .imcs_adapter import IMCSAdapter

logger = logging.getLogger(__name__)


class BenchmarkPipeline:
    def __init__(
        self,
        normalizer: Optional[EvaluationNormalizer] = None,
        compute_bertscore: bool = True
    ):
        self.normalizer = normalizer or EvaluationNormalizer()
        self.evaluator = ReferenceBasedEvaluator(normalizer=self.normalizer)
        self.compute_bertscore = compute_bertscore
        logger.info(f"BenchmarkPipeline initialized (bertscore={'enabled' if compute_bertscore else 'disabled'})")

    def run_single_sample(
        self,
        sample_id: str,
        dataset_path: str,
        prediction: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        logger.info(f"Running benchmark for sample: {sample_id}")

        adapter = IMCSAdapter(dataset_path)
        if sample_id not in adapter.dataset:
            logger.error(f"Sample {sample_id} not found in dataset")
            return {"sample_id": sample_id, "error": "Sample not found"}

        references = adapter.get_reference_reports(sample_id)
        if not references:
            logger.error(f"No reference reports found for sample {sample_id}")
            return {"sample_id": sample_id, "error": "No reference reports"}

        if prediction is None:
            prediction = self._generate_prediction(adapter, sample_id)
            if prediction is None:
                return {"sample_id": sample_id, "error": "Failed to generate prediction"}

        evaluation = self.evaluator.evaluate(
            prediction=prediction,
            references=references,
            compute_bertscore=self.compute_bertscore
        )

        result = {
            "sample_id": sample_id,
            "diagnosis": adapter.get_diagnosis(sample_id),
            "prediction": prediction,
            "references": references,
            "evaluation": evaluation,
        }

        logger.info(f"Benchmark completed for sample {sample_id}")
        self._print_sample_result(result)

        return result

    def _generate_prediction(self, adapter: IMCSAdapter, sample_id: str) -> Optional[Dict[str, str]]:
        logger.info(f"Generating prediction for sample {sample_id} via LLM pipeline")
        return None

    def _print_sample_result(self, result: Dict[str, Any]):
        evaluation = result.get("evaluation", {})

        print("\n" + "=" * 70)
        print(f"  基准评估结果 - 样本 {result['sample_id']}")
        print("=" * 70)

        if result.get("diagnosis"):
            print(f"  诊断: {result['diagnosis']}")

        print("\n── 第一层：字面匹配 ──")
        raw_rouge = evaluation.get("raw_rouge", {})
        raw_bleu = evaluation.get("raw_bleu", {})
        avg_rouge = evaluation.get("avg_rouge", 0)
        print(f"  ROUGE-1: {raw_rouge.get('rouge-1', 0):.4f}")
        print(f"  ROUGE-2: {raw_rouge.get('rouge-2', 0):.4f}")
        print(f"  ROUGE-L: {raw_rouge.get('rouge-l', 0):.4f}")
        print(f"  平均ROUGE: {avg_rouge:.4f}")
        print(f"  BLEU-4: {raw_bleu.get('bleu-4', 0):.4f}")

        norm_rouge = evaluation.get("normalized_rouge")
        if norm_rouge:
            norm_avg = evaluation.get("normalized_avg_rouge", 0)
            delta = evaluation.get("normalization_delta", 0)
            print("\n── 第二层：术语归一化匹配 ──")
            print(f"  归一化 ROUGE-1: {norm_rouge.get('rouge-1', 0):.4f}")
            print(f"  归一化 ROUGE-2: {norm_rouge.get('rouge-2', 0):.4f}")
            print(f"  归一化 ROUGE-L: {norm_rouge.get('rouge-l', 0):.4f}")
            print(f"  归一化平均ROUGE: {norm_avg:.4f}")
            print(f"  归一化提升量: {delta:+.4f}")

        bertscore = evaluation.get("bertscore")
        if bertscore:
            print("\n── 第三层：语义匹配 ──")
            print(f"  BERTScore Precision: {bertscore.get('bertscore_precision', 0):.4f}")
            print(f"  BERTScore Recall: {bertscore.get('bertscore_recall', 0):.4f}")
            print(f"  BERTScore F1: {bertscore.get('bertscore_f1', 0):.4f}")

        field_results = evaluation.get("field_results", {})
        if field_results:
            print("\n── 字段级评估 ──")
            print(f"  {'字段':<8} {'ROUGE-L':>8} {'归一R-L':>8} {'BERT-F1':>8}")
            print(f"  {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
            for field, fr in field_results.items():
                raw_rl = fr.get("raw_rouge", {}).get("rouge-l", 0)
                norm_rl = fr.get("normalized_rouge", {}).get("rouge-l", "-")
                bert_f1 = fr.get("bertscore", {}).get("bertscore_f1", "-")

                norm_str = f"{norm_rl:.4f}" if isinstance(norm_rl, float) else str(norm_rl)
                bert_str = f"{bert_f1:.4f}" if isinstance(bert_f1, float) else str(bert_f1)

                print(f"  {field:<8} {raw_rl:>8.4f} {norm_str:>8} {bert_str:>8}")

        print("\n" + "=" * 70)
