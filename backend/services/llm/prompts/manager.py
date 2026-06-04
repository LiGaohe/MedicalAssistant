"""提示词管理器，组合各子模块模板"""
import logging
from typing import Dict

from .template import PromptTemplate
from .preprocessing import get_preprocessing_templates_zh, get_preprocessing_templates_en
from .soap_generation import get_soap_generation_templates_zh, get_soap_generation_templates_en
from .quality_check import get_quality_check_templates_zh, get_quality_check_templates_en
from .evaluation import get_evaluation_templates_zh, get_evaluation_templates_en
from .terminology import get_terminology_templates_zh, get_terminology_templates_en
from .deprecated import get_deprecated_templates_zh, get_deprecated_templates_en

logger = logging.getLogger(__name__)


class PromptManager:
    """提示词管理器，按语言加载各阶段模板"""

    def __init__(self, language: str = "zh"):
        self.templates: Dict[str, PromptTemplate] = {}
        self.language = language
        self._load_default_templates()
        logger.info("PromptManager初始化完成，语言=%s，模板数量=%d", language, len(self.templates))

    def _load_default_templates(self):
        if self.language == "en":
            self._load_english_templates()
        else:
            self._load_chinese_templates()

    def _load_chinese_templates(self):
        self.templates.update(get_preprocessing_templates_zh())
        self.templates.update(get_soap_generation_templates_zh())
        self.templates.update(get_quality_check_templates_zh())
        self.templates.update(get_evaluation_templates_zh())
        self.templates.update(get_terminology_templates_zh())
        self.templates.update(get_deprecated_templates_zh())

    def _load_english_templates(self):
        self.templates.update(get_preprocessing_templates_en())
        self.templates.update(get_soap_generation_templates_en())
        self.templates.update(get_quality_check_templates_en())
        self.templates.update(get_evaluation_templates_en())
        self.templates.update(get_terminology_templates_en())
        self.templates.update(get_deprecated_templates_en())

        # 英文模板中缺失的模板，使用中文版本补充
        en_missing_keys = set(get_preprocessing_templates_zh().keys()) \
            | set(get_soap_generation_templates_zh().keys()) \
            | set(get_quality_check_templates_zh().keys()) \
            | set(get_evaluation_templates_zh().keys()) \
            | set(get_terminology_templates_zh().keys()) \
            | set(get_deprecated_templates_zh().keys())
        for key in en_missing_keys:
            if key not in self.templates:
                logger.warning("英文模板缺失，使用中文模板补充: %s", key)

        zh_templates = {}
        zh_templates.update(get_preprocessing_templates_zh())
        zh_templates.update(get_soap_generation_templates_zh())
        zh_templates.update(get_quality_check_templates_zh())
        zh_templates.update(get_evaluation_templates_zh())
        zh_templates.update(get_terminology_templates_zh())
        zh_templates.update(get_deprecated_templates_zh())
        for key in en_missing_keys:
            if key not in self.templates and key in zh_templates:
                self.templates[key] = zh_templates[key]

    def get_template(self, name: str) -> PromptTemplate:
        if name not in self.templates:
            raise ValueError(f"Template '{name}' not found")
        return self.templates[name]

    def add_template(self, name: str, template: str, required_vars: list):
        self.templates[name] = PromptTemplate(template, required_vars)
        logger.info("添加自定义模板: %s", name)

    def render(self, template_name: str, **kwargs) -> str:
        template = self.get_template(template_name)
        return template.render(**kwargs)
