"""提示词管理器，组合各子模块模板"""
import logging
from typing import Dict, Optional

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

    # 对话标题锚点前缀，用于在标题后插入编码字典说明
    _TRANSCRIPT_TITLE_PREFIXES = (
        "## 原始对话",
        "## 对话片段",
        "## 对话\n",
        "## Original conversation",
        "## Original Conversation",
        "## Conversation snippet",
    )

    def render(self, template_name: str, compression_dict: Optional[str] = None, **kwargs) -> str:
        """渲染模板，可选在对话原文标题后插入压缩编码字典说明。

        Args:
            template_name: 模板名称
            compression_dict: 压缩编码字典文本，为None时不插入
            **kwargs: 模板变量

        Returns:
            渲染后的完整提示词文本
        """
        template = self.get_template(template_name)
        rendered = template.render(**kwargs)

        if compression_dict:
            dict_block = (
                f"\n## 编码说明\n"
                f"以下对话使用了编码缩写，请按此字典解读：\n"
                f"{compression_dict}\n"
            )
            # 查找对话标题行并在其后插入字典说明
            inserted = False
            for prefix in self._TRANSCRIPT_TITLE_PREFIXES:
                idx = rendered.find(prefix)
                if idx != -1:
                    # 找到该标题行的末尾（换行符位置）
                    line_end = rendered.find("\n", idx)
                    if line_end != -1:
                        rendered = rendered[:line_end + 1] + dict_block + rendered[line_end + 1:]
                        logger.debug("在模板 %s 中插入编码字典说明，锚点: %s", template_name, prefix.strip())
                        inserted = True
                    break

            if not inserted:
                logger.warning("模板 %s 中未找到对话标题锚点，无法插入编码字典说明", template_name)

        return rendered
