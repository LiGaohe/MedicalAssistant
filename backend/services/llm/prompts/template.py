"""提示词模板基类"""
from string import Template


class PromptTemplate:
    """提示词模板，支持变量校验和安全渲染"""

    def __init__(self, template: str, required_vars: list):
        self.template = Template(template)
        self.required_vars = required_vars

    def render(self, **kwargs) -> str:
        missing_vars = set(self.required_vars) - set(kwargs.keys())
        if missing_vars:
            raise ValueError(f"Missing required variables: {missing_vars}")
        return self.template.safe_substitute(**kwargs)
