"""
病历验证服务

在病历生成后自动验证：
1. 必填字段完整性
2. 医学术语正确性（字典+UMLS）
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
from sqlalchemy.orm import Session

from ..utils.logger import logger


@dataclass
class FieldValidation:
    field_name: str
    field_name_cn: str
    is_valid: bool
    is_required: bool
    value: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class TermValidation:
    original_term: str
    normalized_term: Optional[str]
    is_valid: bool
    confidence: float
    source: str
    cui: Optional[str] = None
    code: Optional[str] = None
    code_system: Optional[str] = None


@dataclass
class ValidationResult:
    is_valid: bool
    score: float
    field_validations: Dict[str, FieldValidation]
    term_validations: List[TermValidation]
    errors: List[str]
    warnings: List[str]
    summary: Dict[str, Any]


SOAP_REQUIRED_FIELDS = {
    "subjective": {
        "chief_complaint": {"name_cn": "主诉", "required": True, "min_length": 2},
        "history_present_illness": {"name_cn": "现病史", "required": True, "min_length": 10},
        "past_history": {"name_cn": "既往史", "required": False, "min_length": 0},
    },
    "objective": {
        "physical_examination": {"name_cn": "体格检查", "required": False, "min_length": 0},
        "auxiliary_examination": {"name_cn": "辅助检查", "required": False, "min_length": 0},
    },
    "assessment": {
        "diagnosis": {"name_cn": "诊断", "required": True, "min_length": 2},
        "differential_diagnosis": {"name_cn": "鉴别诊断", "required": False, "min_length": 0},
    },
    "plan": {
        "treatment": {"name_cn": "治疗方案", "required": True, "min_length": 2},
        "advice": {"name_cn": "医嘱", "required": False, "min_length": 0},
    }
}


class ValidationService:
    def __init__(
        self,
        db: Optional[Session] = None,
        terminology_service=None,
        umls_client=None
    ):
        self.db = db
        self.terminology_service = terminology_service
        self.umls_client = umls_client
        self.term_dict = self._load_term_dict()
        logger.info(f"ValidationService initialized with {len(self.term_dict)} term types")
    
    def _load_term_dict(self) -> Dict[str, Any]:
        try:
            config_path = Path(__file__).parent.parent.parent / "config" / "medical_terms.json"
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("medical_terms.json not found")
            return {}
    
    def validate(
        self,
        emr_result: Dict[str, Any],
        check_terms: bool = True
    ) -> ValidationResult:
        logger.info("开始病历验证...")
        
        field_validations = self._validate_fields(emr_result)
        
        term_validations = []
        if check_terms:
            term_validations = self._validate_terms(emr_result)
        
        errors = []
        warnings = []
        
        for field_key, field_val in field_validations.items():
            if field_val.is_required and not field_val.is_valid:
                errors.extend([f"[{field_val.field_name_cn}] {e}" for e in field_val.errors])
            warnings.extend([f"[{field_val.field_name_cn}] {w}" for w in field_val.warnings])
        
        invalid_terms = [t for t in term_validations if not t.is_valid and t.confidence < 0.5]
        for term in invalid_terms:
            warnings.append(f"术语 '{term.original_term}' 未能规范化 (置信度: {term.confidence:.2f})")
        
        score = self._calculate_score(field_validations, term_validations)
        is_valid = len(errors) == 0 and score >= 0.6
        
        summary = self._build_summary(field_validations, term_validations, score)
        
        result = ValidationResult(
            is_valid=is_valid,
            score=score,
            field_validations=field_validations,
            term_validations=term_validations,
            errors=errors,
            warnings=warnings,
            summary=summary
        )
        
        self._log_result(result)
        
        return result
    
    def _validate_fields(self, emr_result: Dict[str, Any]) -> Dict[str, FieldValidation]:
        validations = {}
        
        for section, fields in SOAP_REQUIRED_FIELDS.items():
            section_data = emr_result.get(section, {})
            if not isinstance(section_data, dict):
                section_data = {}
            
            for field_name, field_config in fields.items():
                field_key = f"{section}.{field_name}"
                field_data = section_data.get(field_name, {})
                
                if isinstance(field_data, dict):
                    value = field_data.get("value", "")
                elif isinstance(field_data, str):
                    value = field_data
                else:
                    value = ""
                
                validation = self._validate_single_field(
                    field_key=field_key,
                    field_name=field_name,
                    field_name_cn=field_config["name_cn"],
                    value=value,
                    is_required=field_config["required"],
                    min_length=field_config["min_length"]
                )
                validations[field_key] = validation
        
        return validations
    
    def _validate_single_field(
        self,
        field_key: str,
        field_name: str,
        field_name_cn: str,
        value: str,
        is_required: bool,
        min_length: int
    ) -> FieldValidation:
        errors = []
        warnings = []
        
        value = value.strip() if value else ""
        
        is_valid = True
        
        if not value:
            if is_required:
                errors.append("必填字段为空")
                is_valid = False
            else:
                warnings.append("可选字段为空")
        elif len(value) < min_length:
            if is_required:
                errors.append(f"内容过短，最少需要{min_length}个字符")
                is_valid = False
            else:
                warnings.append(f"内容较短，建议至少{min_length}个字符")
        
        if field_name == "chief_complaint" and value:
            if not re.search(r'[\u4e00-\u9fa5]', value):
                errors.append("主诉应包含中文描述")
                is_valid = False
            elif len(value) > 100:
                warnings.append("主诉过长，建议精简")
        
        if field_name == "diagnosis" and value:
            if not re.search(r'[\u4e00-\u9fa5]', value):
                errors.append("诊断应包含中文描述")
                is_valid = False
        
        return FieldValidation(
            field_name=field_name,
            field_name_cn=field_name_cn,
            is_valid=is_valid,
            is_required=is_required,
            value=value,
            errors=errors,
            warnings=warnings
        )
    
    def _validate_terms(self, emr_result: Dict[str, Any]) -> List[TermValidation]:
        validations = []
        
        text_to_validate = self._extract_text_for_term_validation(emr_result)
        
        found_terms = self._extract_terms_from_text(text_to_validate)
        
        for term_info in found_terms:
            term = term_info["term"]
            term_type = term_info["type"]
            context = term_info["context"]
            
            validation = self._validate_single_term(term, term_type, context)
            validations.append(validation)
        
        return validations
    
    def _extract_text_for_term_validation(self, emr_result: Dict[str, Any]) -> str:
        texts = []
        
        for section in ["subjective", "objective", "assessment", "plan"]:
            section_data = emr_result.get(section, {})
            if not isinstance(section_data, dict):
                continue
            
            for field_name, field_data in section_data.items():
                if isinstance(field_data, dict):
                    value = field_data.get("value", "")
                elif isinstance(field_data, str):
                    value = field_data
                else:
                    continue
                
                if value:
                    texts.append(value)
        
        return " ".join(texts)
    
    def _extract_terms_from_text(self, text: str) -> List[Dict[str, str]]:
        found_terms = []
        seen_terms = set()
        
        for term_type, type_dict in self.term_dict.items():
            for standard_term, aliases in type_dict.items():
                all_terms = [standard_term] + aliases
                
                for term in all_terms:
                    if term in text and term not in seen_terms:
                        seen_terms.add(term)
                        
                        context_start = max(0, text.find(term) - 20)
                        context_end = min(len(text), text.find(term) + len(term) + 20)
                        context = text[context_start:context_end]
                        
                        found_terms.append({
                            "term": term,
                            "standard": standard_term,
                            "type": term_type,
                            "context": context
                        })
        
        return found_terms
    
    def _validate_single_term(
        self,
        term: str,
        term_type: str,
        context: str
    ) -> TermValidation:
        is_valid = True
        normalized_term = None
        confidence = 0.0
        source = "none"
        cui = None
        code = None
        code_system = None
        
        if self.terminology_service:
            try:
                result = self.terminology_service.normalize_term(term, context, term_type)
                normalized_term = result.normalized_term
                confidence = result.confidence
                source = result.source or "none"
                cui = result.cui
                code = result.code
                code_system = result.code_system
                is_valid = confidence >= 0.5
            except Exception as e:
                logger.warning(f"术语规范化失败 '{term}': {e}")
                is_valid = False
                confidence = 0.0
        else:
            type_dict = self.term_dict.get(term_type, {})
            for standard, aliases in type_dict.items():
                if term == standard:
                    normalized_term = standard
                    confidence = 1.0
                    source = "dict_exact"
                    is_valid = True
                    break
                elif term in aliases:
                    normalized_term = standard
                    confidence = 0.95
                    source = "dict_alias"
                    is_valid = True
                    break
        
        return TermValidation(
            original_term=term,
            normalized_term=normalized_term,
            is_valid=is_valid,
            confidence=confidence,
            source=source,
            cui=cui,
            code=code,
            code_system=code_system
        )
    
    def _calculate_score(
        self,
        field_validations: Dict[str, FieldValidation],
        term_validations: List[TermValidation]
    ) -> float:
        if not field_validations:
            return 0.0
        
        required_fields = [v for v in field_validations.values() if v.is_required]
        if not required_fields:
            field_score = 1.0
        else:
            valid_required = sum(1 for v in required_fields if v.is_valid)
            field_score = valid_required / len(required_fields)
        
        if term_validations:
            valid_terms = sum(1 for t in term_validations if t.is_valid)
            term_score = valid_terms / len(term_validations)
        else:
            term_score = 1.0
        
        score = field_score * 0.7 + term_score * 0.3
        
        return round(score, 4)
    
    def _build_summary(
        self,
        field_validations: Dict[str, FieldValidation],
        term_validations: List[TermValidation],
        score: float
    ) -> Dict[str, Any]:
        required_fields = [v for v in field_validations.values() if v.is_required]
        valid_required = sum(1 for v in required_fields if v.is_valid)
        
        optional_fields = [v for v in field_validations.values() if not v.is_required]
        valid_optional = sum(1 for v in optional_fields if v.is_valid or not v.value)
        
        valid_terms = sum(1 for t in term_validations if t.is_valid)
        
        return {
            "total_score": score,
            "field_completeness": {
                "required_total": len(required_fields),
                "required_valid": valid_required,
                "required_ratio": valid_required / len(required_fields) if required_fields else 1.0,
                "optional_total": len(optional_fields),
                "optional_valid": valid_optional,
            },
            "term_validation": {
                "total_terms": len(term_validations),
                "valid_terms": valid_terms,
                "invalid_terms": len(term_validations) - valid_terms,
            },
            "quality_level": self._get_quality_level(score)
        }
    
    def _get_quality_level(self, score: float) -> str:
        if score >= 0.9:
            return "优秀"
        elif score >= 0.8:
            return "良好"
        elif score >= 0.6:
            return "合格"
        elif score >= 0.4:
            return "需改进"
        else:
            return "不合格"
    
    def _log_result(self, result: ValidationResult):
        logger.info("=" * 60)
        logger.info("病历验证结果")
        logger.info("=" * 60)
        
        logger.info(f"【总体评分】{result.score:.2%} ({result.summary['quality_level']})")
        logger.info(f"【验证状态】{'✓ 通过' if result.is_valid else '✗ 未通过'}")
        
        logger.info("【字段完整性】")
        for field_key, field_val in result.field_validations.items():
            if field_val.is_required:
                status = "✓" if field_val.is_valid else "✗"
                logger.info(f"  {status} {field_val.field_name_cn}: {'完整' if field_val.is_valid else '缺失'}")
        
        if result.term_validations:
            logger.info("【术语验证】")
            for term_val in result.term_validations:
                status = "✓" if term_val.is_valid else "△"
                norm = term_val.normalized_term or "未规范化"
                logger.info(f"  {status} {term_val.original_term} -> {norm} (置信度: {term_val.confidence:.2f})")
        
        if result.errors:
            logger.info("【错误】")
            for error in result.errors:
                logger.warning(f"  ✗ {error}")
        
        if result.warnings:
            logger.info("【警告】")
            for warning in result.warnings:
                logger.info(f"  △ {warning}")
        
        logger.info("=" * 60)
    
    def to_dict(self, result: ValidationResult) -> Dict[str, Any]:
        return {
            "is_valid": result.is_valid,
            "score": result.score,
            "errors": result.errors,
            "warnings": result.warnings,
            "summary": result.summary,
            "field_validations": {
                k: {
                    "field_name": v.field_name,
                    "field_name_cn": v.field_name_cn,
                    "is_valid": v.is_valid,
                    "is_required": v.is_required,
                    "errors": v.errors,
                    "warnings": v.warnings
                }
                for k, v in result.field_validations.items()
            },
            "term_validations": [
                {
                    "original_term": t.original_term,
                    "normalized_term": t.normalized_term,
                    "is_valid": t.is_valid,
                    "confidence": t.confidence,
                    "source": t.source,
                    "cui": t.cui,
                    "code": t.code,
                    "code_system": t.code_system
                }
                for t in result.term_validations
            ]
        }
