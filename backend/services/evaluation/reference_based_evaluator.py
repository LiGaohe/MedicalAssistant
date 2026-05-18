import logging
from typing import Dict, Any, List, Optional
import jieba
from rouge_score import rouge_scorer
from .evaluation_normalizer import EvaluationNormalizer
from .imcs_adapter import IMCS_FIELDS

logger = logging.getLogger(__name__)

_jieba_initialized = False


def _ensure_jieba():
    global _jieba_initialized
    if not _jieba_initialized:
        jieba.setLogLevel(logging.WARNING)
        _jieba_initialized = True


class JiebaTokenizer:
    def tokenize(self, text: str) -> List[str]:
        _ensure_jieba()
        return jieba.lcut(text)


class ReferenceBasedEvaluator:
    def __init__(self, normalizer: Optional[EvaluationNormalizer] = None):
        self.normalizer = normalizer
        self.rouge_scorer = rouge_scorer.RougeScorer(
            ['rouge1', 'rouge2', 'rougeL'],
            use_stemmer=False,
            tokenizer=JiebaTokenizer()
        )
        logger.info("ReferenceBasedEvaluator initialized")

    def compute_rouge(self, prediction: str, reference: str) -> Dict[str, float]:
        if not prediction.strip() or not reference.strip():
            return {"rouge-1": 0.0, "rouge-2": 0.0, "rouge-l": 0.0}

        try:
            scores = self.rouge_scorer.score(reference, prediction)
            return {
                "rouge-1": round(scores["rouge1"].fmeasure, 4),
                "rouge-2": round(scores["rouge2"].fmeasure, 4),
                "rouge-l": round(scores["rougeL"].fmeasure, 4),
            }
        except Exception as e:
            logger.error(f"ROUGE computation failed: {e}")
            return {"rouge-1": 0.0, "rouge-2": 0.0, "rouge-l": 0.0}

    def compute_bleu(self, prediction: str, reference: str) -> Dict[str, float]:
        try:
            from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
        except ImportError:
            logger.warning("nltk not available, BLEU computation skipped")
            return {"bleu-1": 0.0, "bleu-2": 0.0, "bleu-3": 0.0, "bleu-4": 0.0}

        if not prediction.strip() or not reference.strip():
            return {"bleu-1": 0.0, "bleu-2": 0.0, "bleu-3": 0.0, "bleu-4": 0.0}

        pred_tokens = jieba.lcut(prediction)
        ref_tokens = jieba.lcut(reference)

        smoothing = SmoothingFunction().method1

        try:
            bleu1 = sentence_bleu([ref_tokens], pred_tokens, weights=(1, 0, 0, 0), smoothing_function=smoothing)
            bleu2 = sentence_bleu([ref_tokens], pred_tokens, weights=(0.5, 0.5, 0, 0), smoothing_function=smoothing)
            bleu3 = sentence_bleu([ref_tokens], pred_tokens, weights=(0.33, 0.33, 0.34, 0), smoothing_function=smoothing)
            bleu4 = sentence_bleu([ref_tokens], pred_tokens, weights=(0.25, 0.25, 0.25, 0.25), smoothing_function=smoothing)

            return {
                "bleu-1": round(bleu1, 4),
                "bleu-2": round(bleu2, 4),
                "bleu-3": round(bleu3, 4),
                "bleu-4": round(bleu4, 4),
            }
        except Exception as e:
            logger.error(f"BLEU computation failed: {e}")
            return {"bleu-1": 0.0, "bleu-2": 0.0, "bleu-3": 0.0, "bleu-4": 0.0}

    def compute_bertscore(self, prediction: str, reference: str) -> Dict[str, float]:
        try:
            from bert_score import score as bert_score_fn
        except ImportError:
            logger.warning("bert-score not available, BERTScore computation skipped")
            return {"bertscore_precision": 0.0, "bertscore_recall": 0.0, "bertscore_f1": 0.0}

        if not prediction.strip() or not reference.strip():
            return {"bertscore_precision": 0.0, "bertscore_recall": 0.0, "bertscore_f1": 0.0}

        try:
            P, R, F1 = bert_score_fn(
                [prediction],
                [reference],
                model_type="bert-base-chinese",
                lang="zh",
                verbose=False
            )
            return {
                "bertscore_precision": round(P.item(), 4),
                "bertscore_recall": round(R.item(), 4),
                "bertscore_f1": round(F1.item(), 4),
            }
        except Exception as e:
            logger.error(f"BERTScore computation failed: {e}")
            return {"bertscore_precision": 0.0, "bertscore_recall": 0.0, "bertscore_f1": 0.0}

    def evaluate(
        self,
        prediction: Dict[str, str],
        references: List[Dict[str, str]],
        compute_bertscore: bool = True
    ) -> Dict[str, Any]:
        logger.info(f"Evaluating prediction against {len(references)} reference(s)")

        pred_text = self._report_to_text(prediction)
        ref_texts = [self._report_to_text(ref) for ref in references]

        raw_rouge = self._compute_multi_ref_rouge(pred_text, ref_texts)
        raw_bleu = self._compute_multi_ref_bleu(pred_text, ref_texts)

        normalized_rouge = None
        normalized_bleu = None
        normalization_delta = None

        if self.normalizer:
            norm_pred = self.normalizer.normalize_report(prediction)
            norm_refs = [self.normalizer.normalize_report(ref) for ref in references]

            norm_pred_text = self._report_to_text(norm_pred)
            norm_ref_texts = [self._report_to_text(ref) for ref in norm_refs]

            normalized_rouge = self._compute_multi_ref_rouge(norm_pred_text, norm_ref_texts)
            normalized_bleu = self._compute_multi_ref_bleu(norm_pred_text, norm_ref_texts)

            raw_avg = (raw_rouge["rouge-1"] + raw_rouge["rouge-2"] + raw_rouge["rouge-l"]) / 3
            norm_avg = (normalized_rouge["rouge-1"] + normalized_rouge["rouge-2"] + normalized_rouge["rouge-l"]) / 3
            normalization_delta = round(norm_avg - raw_avg, 4)

        bertscore = None
        if compute_bertscore:
            bertscore = self._compute_multi_ref_bertscore(pred_text, ref_texts)

        field_results = self._evaluate_fields(prediction, references, compute_bertscore)

        raw_avg_rouge = (raw_rouge["rouge-1"] + raw_rouge["rouge-2"] + raw_rouge["rouge-l"]) / 3

        result = {
            "raw_rouge": raw_rouge,
            "avg_rouge": round(raw_avg_rouge, 4),
            "raw_bleu": raw_bleu,
            "normalized_rouge": normalized_rouge,
            "normalized_bleu": normalized_bleu,
            "normalization_delta": normalization_delta,
            "bertscore": bertscore,
            "field_results": field_results,
        }

        if normalized_rouge:
            norm_avg_rouge = (normalized_rouge["rouge-1"] + normalized_rouge["rouge-2"] + normalized_rouge["rouge-l"]) / 3
            result["normalized_avg_rouge"] = round(norm_avg_rouge, 4)

        logger.info(f"Evaluation result: avg_rouge={raw_avg_rouge:.4f}, bertscore_f1={bertscore.get('bertscore_f1', 0) if bertscore else 0:.4f}")
        return result

    def _compute_multi_ref_rouge(self, prediction: str, references: List[str]) -> Dict[str, float]:
        best_scores = {"rouge-1": 0.0, "rouge-2": 0.0, "rouge-l": 0.0}

        for ref in references:
            scores = self.compute_rouge(prediction, ref)
            for key in best_scores:
                best_scores[key] = max(best_scores[key], scores[key])

        return best_scores

    def _compute_multi_ref_bleu(self, prediction: str, references: List[str]) -> Dict[str, float]:
        best_scores = {"bleu-1": 0.0, "bleu-2": 0.0, "bleu-3": 0.0, "bleu-4": 0.0}

        for ref in references:
            scores = self.compute_bleu(prediction, ref)
            for key in best_scores:
                best_scores[key] = max(best_scores[key], scores[key])

        return best_scores

    def _compute_multi_ref_bertscore(self, prediction: str, references: List[str]) -> Dict[str, float]:
        best_scores = {"bertscore_precision": 0.0, "bertscore_recall": 0.0, "bertscore_f1": 0.0}

        for ref in references:
            scores = self.compute_bertscore(prediction, ref)
            for key in best_scores:
                best_scores[key] = max(best_scores[key], scores[key])

        return best_scores

    def _evaluate_fields(
        self,
        prediction: Dict[str, str],
        references: List[Dict[str, str]],
        compute_bertscore: bool = True
    ) -> Dict[str, Dict[str, Any]]:
        field_results = {}

        for field in IMCS_FIELDS:
            pred_value = prediction.get(field, "")
            ref_values = [ref.get(field, "") for ref in references]

            field_raw_rouge = self._compute_multi_ref_rouge(pred_value, ref_values)
            field_raw_bleu = self._compute_multi_ref_bleu(pred_value, ref_values)

            field_result = {
                "raw_rouge": field_raw_rouge,
                "raw_bleu": field_raw_bleu,
            }

            if self.normalizer:
                norm_pred = self.normalizer.normalize_text(pred_value)
                norm_refs = [self.normalizer.normalize_text(rv) for rv in ref_values]
                field_norm_rouge = self._compute_multi_ref_rouge(norm_pred, norm_refs)
                field_result["normalized_rouge"] = field_norm_rouge

            if compute_bertscore and pred_value.strip() and any(rv.strip() for rv in ref_values):
                best_ref = max(ref_values, key=lambda rv: len(rv.strip()))
                if best_ref.strip():
                    field_bertscore = self.compute_bertscore(pred_value, best_ref)
                    field_result["bertscore"] = field_bertscore

            field_results[field] = field_result

        return field_results

    def _report_to_text(self, report: Dict[str, str]) -> str:
        parts = []
        for field in IMCS_FIELDS:
            value = report.get(field, "")
            if value:
                parts.append(f"{field}：{value}")
        return "\n".join(parts)
