import json
import re
from typing import Dict, Any, Optional, List
from ...utils.logger import logger


class JSONParseError(Exception):
    def __init__(self, stage_name: str, response_text: str, error_msg: str = ""):
        self.stage_name = stage_name
        self.response_text = response_text
        self.error_msg = error_msg
        super().__init__(f"JSON解析失败 [{stage_name}]: {error_msg}")

    def get_full_response(self) -> str:
        return self.response_text


def parse_json_response(response_text: str, stage_name: str = "", raise_on_error: bool = False) -> Optional[Dict[str, Any]]:
    logger.info(f"开始解析JSON响应, 阶段: {stage_name}, 响应长度: {len(response_text)} 字符")
    logger.debug(f"原始响应内容:\n{response_text}")

    response_text = response_text.strip()

    response_text = _remove_markdown_code_block(response_text)

    response_text = _remove_control_characters(response_text)

    json_start = response_text.find("{")
    json_end = response_text.rfind("}")

    if json_start != -1 and json_end > json_start:
        json_str = response_text[json_start:json_end + 1]
        try:
            result = json.loads(json_str)
            logger.info(f"JSON解析成功, 阶段: {stage_name}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"标准JSON解析失败, 阶段: {stage_name}, 错误: {e}")
            logger.debug(f"尝试解析的JSON字符串:\n{json_str}")

            fixed_json = _try_fix_json(json_str)
            if fixed_json:
                logger.info(f"JSON修复成功, 阶段: {stage_name}")
                return fixed_json
            else:
                logger.warning(f"JSON修复失败, 阶段: {stage_name}")

    all_jsons = _extract_all_json_objects(response_text)
    if all_jsons:
        logger.info(f"从响应中提取到 {len(all_jsons)} 个JSON对象，使用第一个, 阶段: {stage_name}")
        return all_jsons[0]

    if json_end != -1:
        potential_json = response_text[:json_end + 1]
    else:
        potential_json = response_text

    if potential_json.startswith('"'):
        json_str = "{" + potential_json
        try:
            result = json.loads(json_str)
            logger.info(f"补全开头大括号后解析成功, 阶段: {stage_name}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"补全开头大括号后解析失败, 阶段: {stage_name}, 错误: {e}")

    if potential_json and potential_json[0].isalpha():
        colon_pos = potential_json.find('":')
        if colon_pos != -1:
            key = potential_json[:colon_pos]
            rest = potential_json[colon_pos + 1:]
            json_str = '{"' + key + '"' + rest
            try:
                result = json.loads(json_str)
                logger.info(f"补全开头引号和大括号后解析成功, 阶段: {stage_name}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"补全开头引号和大括号后解析失败, 阶段: {stage_name}, 错误: {e}")

    if potential_json and potential_json[0].isalpha():
        json_str = "{" + potential_json
        try:
            result = json.loads(json_str)
            logger.info(f"仅补全大括号后解析成功, 阶段: {stage_name}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"仅补全大括号后解析失败, 阶段: {stage_name}, 错误: {e}")

    logger.error(f"无法从响应中提取有效JSON, 阶段: {stage_name}")
    logger.error(f"响应内容前500字符: {response_text[:500]}")
    logger.debug(f"完整响应内容:\n{response_text}")
    
    if raise_on_error:
        raise JSONParseError(stage_name, response_text, "无法从响应中提取有效JSON")
    
    return None


def _remove_markdown_code_block(text: str) -> str:
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def _remove_control_characters(text: str) -> str:
    result = []
    in_string = False
    escape_next = False

    for char in text:
        if escape_next:
            result.append(char)
            escape_next = False
            continue

        if char == '\\' and in_string:
            result.append(char)
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            result.append(char)
            continue

        if in_string:
            if ord(char) < 32 and char not in '\n\r\t':
                continue
            result.append(char)
        else:
            result.append(char)

    return ''.join(result)


def _try_fix_json(json_str: str) -> Optional[Dict[str, Any]]:
    fixed = json_str

    fixed = re.sub(r',\s*}', '}', fixed)
    fixed = re.sub(r',\s*]', ']', fixed)

    fixed = re.sub(r',\s*\n\s*"', ',', fixed)
    fixed = re.sub(r',\s*\n\s*}', '}', fixed)

    fixed = re.sub(r':\s*,', ': null,', fixed)
    fixed = re.sub(r':\s*}', ': null}', fixed)

    fixed = re.sub(r'"\s*,\s*,', '",', fixed)
    fixed = re.sub(r',\s*,', ',', fixed)

    fixed = re.sub(r'"\s*:\s*"', '": "', fixed)
    fixed = re.sub(r'"\s*:\s*\[', '": [', fixed)
    fixed = re.sub(r'"\s*:\s*\{', '": {', fixed)

    fixed = re.sub(r'(?<!\\)"(?=[a-zA-Z0-9_\u4e00-\u9fff])', '"', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    brace_count = fixed.count('{') - fixed.count('}')
    bracket_count = fixed.count('[') - fixed.count(']')

    if brace_count > 0:
        fixed += '}' * brace_count
    if bracket_count > 0:
        fixed += ']' * bracket_count

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def _extract_all_json_objects(text: str) -> List[Dict[str, Any]]:
    results = []
    depth = 0
    start = -1

    for i, char in enumerate(text):
        if char == '{':
            if depth == 0:
                start = i
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start != -1:
                json_str = text[start:i+1]
                try:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict):
                        results.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1

    return results