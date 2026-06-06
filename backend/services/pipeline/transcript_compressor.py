"""
对话原文字典编码压缩器

对医患对话原文进行字典编码压缩，减少发送给LLM的token数量。
压缩算法包含两部分：
1. 对话前缀压缩：识别 [#N] [spkX]: 模式，按说话人分配短编码
2. 高频短语压缩：提取出现>=2次且长度>=3字符的子串，分配编码
"""

import re
from collections import Counter
from typing import Dict, Optional, Tuple

from ...utils.logger import logger


class TranscriptCompressor:
    """对话原文字典编码压缩器

    通过字典编码压缩对话原文，减少发送给LLM的token数量。
    编码符号使用Unicode带圈数字，在LLM tokenization中通常只占1个token。

    压缩流程：
    1. 识别对话前缀模式，按说话人分配短编码（①②...）
    2. 提取高频短语，按频率*长度降序排列，分配编码（③④...）
    3. 依次替换前缀和高频短语
    4. 如果压缩后文本长度 > 原文的80%，回退返回原文
    """

    # Unicode带圈数字，用于编码符号
    CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"

    # 对话前缀正则：匹配 [#N] [spkX]: 或 [#N] spkX: 或 [#N] {speaker}:
    # 支持格式：
    #   [#0] [spk0]: text
    #   [#0] spk0: text
    #   [#0] {医生}: text
    PREFIX_PATTERN = re.compile(
        r'^(\[#\d+\]\s*)\[(\w+)\]\s*:\s*'   # [#N] [spkX]:
        r'|'
        r'^(\[#\d+\]\s*)(\w+)\s*:\s*'        # [#N] spkX:
    )

    # 高频短语长度范围
    MIN_PHRASE_LEN = 3
    MAX_PHRASE_LEN = 20

    # 高频短语最小出现次数
    MIN_PHRASE_FREQ = 2

    # 高频短语n-gram范围
    MIN_NGRAM = 2
    MAX_NGRAM = 6

    # 最多编码的高频短语数量
    MAX_PHRASE_CODES = 20

    # 压缩率阈值：压缩后文本长度超过原文的此比例时回退
    COMPRESSION_THRESHOLD = 0.8

    def compress(self, text: str) -> Tuple[str, Optional[str]]:
        """压缩对话原文

        Args:
            text: 原始对话文本

        Returns:
            (compressed_text, dictionary_str):
                compressed_text: 压缩后的文本
                dictionary_str: 编码字典说明文本（LLM可理解），回退时为None
        """
        if not text or not text.strip():
            logger.warning("compress: 输入文本为空，直接返回")
            return text, None

        original_len = len(text)
        logger.info(f"compress: 开始压缩，原文长度={original_len}")

        dictionary: Dict[str, str] = {}

        # 步骤1：对话前缀压缩
        text_after_prefix, prefix_dict = self._compress_prefixes(text)
        dictionary.update(prefix_dict)

        # 步骤2：高频短语压缩
        text_after_phrase, phrase_dict = self._compress_phrases(
            text_after_prefix, start_code_index=len(prefix_dict)
        )
        dictionary.update(phrase_dict)

        compressed_len = len(text_after_phrase)

        # 步骤3：回退机制
        if original_len > 0 and compressed_len > original_len * self.COMPRESSION_THRESHOLD:
            logger.info(
                f"compress: 压缩后长度({compressed_len}) > 原文{int(self.COMPRESSION_THRESHOLD * 100)}%"
                f"({int(original_len * self.COMPRESSION_THRESHOLD)})，回退返回原文"
            )
            return text, None

        compression_ratio = compressed_len / original_len if original_len > 0 else 1.0
        logger.info(
            f"compress: 压缩完成，原文={original_len}字符，压缩后={compressed_len}字符，"
            f"压缩率={compression_ratio:.2%}，编码数量={len(dictionary)}"
        )

        dictionary_str = self.build_dictionary_prompt(dictionary)
        return text_after_phrase, dictionary_str

    def compress_section(self, text: str) -> Tuple[str, Optional[str]]:
        """压缩裁剪后的对话片段（用于幻觉检查等阶段）

        与compress()相同逻辑，但针对较短的裁剪文本优化。
        短文本中高频短语可能较少，主要依赖前缀压缩。

        Args:
            text: 裁剪后的对话片段文本

        Returns:
            (compressed_text, dictionary_str):
                compressed_text: 压缩后的文本
                dictionary_str: 编码字典说明文本（LLM可理解），回退时为None
        """
        if not text or not text.strip():
            logger.warning("compress_section: 输入文本为空，直接返回")
            return text, None

        original_len = len(text)
        logger.info(f"compress_section: 开始压缩片段，原文长度={original_len}")

        dictionary: Dict[str, str] = {}

        # 步骤1：对话前缀压缩
        text_after_prefix, prefix_dict = self._compress_prefixes(text)
        dictionary.update(prefix_dict)

        # 步骤2：高频短语压缩（片段文本可能较短，仍尝试压缩）
        text_after_phrase, phrase_dict = self._compress_phrases(
            text_after_prefix, start_code_index=len(prefix_dict)
        )
        dictionary.update(phrase_dict)

        compressed_len = len(text_after_phrase)

        # 回退机制
        if original_len > 0 and compressed_len > original_len * self.COMPRESSION_THRESHOLD:
            logger.info(
                f"compress_section: 压缩后长度({compressed_len}) > 原文{int(self.COMPRESSION_THRESHOLD * 100)}%"
                f"({int(original_len * self.COMPRESSION_THRESHOLD)})，回退返回原文"
            )
            return text, None

        compression_ratio = compressed_len / original_len if original_len > 0 else 1.0
        logger.info(
            f"compress_section: 压缩完成，原文={original_len}字符，压缩后={compressed_len}字符，"
            f"压缩率={compression_ratio:.2%}，编码数量={len(dictionary)}"
        )

        dictionary_str = self.build_dictionary_prompt(dictionary)
        return text_after_phrase, dictionary_str

    def build_dictionary_prompt(self, dictionary: dict) -> str:
        """生成LLM可理解的字典说明文本

        Args:
            dictionary: 编码映射 {编码符号: 原始文本}

        Returns:
            字典说明文本，格式如：
            "编码字典：①=[spk0]前缀 ②=[spk1]前缀 ③=头痛 ④=阿莫西林 ..."
"
        """
        if not dictionary:
            return ""

        parts = []
        for code, original in dictionary.items():
            parts.append(f"{code}={original}")

        return "编码字典：" + " ".join(parts)

    def _compress_prefixes(self, text: str) -> Tuple[str, Dict[str, str]]:
        """对话前缀压缩

        识别 [#N] [spkX]: 模式，按说话人分配短编码。
        同一说话人的所有前缀都替换为同一个编码符号。

        Args:
            text: 原始对话文本

        Returns:
            (compressed_text, prefix_dict):
                compressed_text: 前缀压缩后的文本
                prefix_dict: 前缀编码映射 {编码符号: 原始文本说明}
        """
        prefix_dict: Dict[str, str] = {}
        speaker_to_code: Dict[str, str] = {}

        lines = text.split('\n')
        compressed_lines = []

        for line in lines:
            match = self.PREFIX_PATTERN.match(line)
            if match:
                # 判断匹配的是哪种格式
                if match.group(2):
                    # [#N] [spkX]: 格式
                    prefix_part = match.group(1)   # [#N] 部分
                    speaker = match.group(2)       # spkX
                    full_prefix = match.group(0)   # 完整前缀
                elif match.group(4):
                    # [#N] spkX: 格式
                    prefix_part = match.group(3)   # [#N] 部分
                    speaker = match.group(4)       # spkX
                    full_prefix = match.group(0)   # 完整前缀
                else:
                    compressed_lines.append(line)
                    continue

                # 为说话人分配编码
                if speaker not in speaker_to_code:
                    code_index = len(speaker_to_code)
                    if code_index < len(self.CIRCLED_NUMBERS):
                        code = self.CIRCLED_NUMBERS[code_index]
                        speaker_to_code[speaker] = code
                        prefix_dict[code] = f"[{speaker}]前缀"
                    else:
                        # 编码符号用完，不再压缩该说话人
                        compressed_lines.append(line)
                        continue

                code = speaker_to_code[speaker]
                # 替换整行前缀为编码符号
                remaining = line[len(full_prefix):]
                compressed_lines.append(f"{code}{remaining}")
            else:
                compressed_lines.append(line)

        compressed_text = '\n'.join(compressed_lines)

        if prefix_dict:
            logger.info(f"_compress_prefixes: 识别 {len(prefix_dict)} 个说话人编码: {prefix_dict}")

        return compressed_text, prefix_dict

    def _compress_phrases(
        self,
        text: str,
        start_code_index: int = 0
    ) -> Tuple[str, Dict[str, str]]:
        """高频短语压缩

        提取出现>=2次且长度>=3字符的子串，按频率*长度降序排列，
        分配编码符号（从start_code_index开始）。

        Args:
            text: 前缀压缩后的文本
            start_code_index: 编码符号起始索引（①②可能已被说话人占用）

        Returns:
            (compressed_text, phrase_dict):
                compressed_text: 短语压缩后的文本
                phrase_dict: 短语编码映射 {编码符号: 原始短语}
        """
        phrase_dict: Dict[str, str] = {}

        # 提取高频短语候选
        candidates = self._extract_phrase_candidates(text)

        if not candidates:
            logger.info("_compress_phrases: 无高频短语候选，跳过短语压缩")
            return text, phrase_dict

        # 按频率*长度降序排列（节省token最多的优先）
        scored_candidates = []
        for phrase, freq in candidates.items():
            score = freq * len(phrase)
            scored_candidates.append((phrase, freq, score))

        scored_candidates.sort(key=lambda x: x[2], reverse=True)

        # 限制编码数量
        available_codes = len(self.CIRCLED_NUMBERS) - start_code_index
        max_codes = min(self.MAX_PHRASE_CODES, available_codes)

        if max_codes <= 0:
            logger.info("_compress_phrases: 无可用编码符号，跳过短语压缩")
            return text, phrase_dict

        # 分配编码并替换
        compressed_text = text
        code_index = start_code_index
        selected_phrases: list = []  # 已选中的短语，用于子串去重

        for phrase, freq, score in scored_candidates:
            if len(phrase_dict) >= max_codes:
                break

            if code_index >= len(self.CIRCLED_NUMBERS):
                break

            # 子串去重：如果当前短语是某个已选中短语的子串，跳过
            # 因为已选中的长短语被替换后，子串已不存在
            is_substring = False
            for selected in selected_phrases:
                if phrase in selected:
                    is_substring = True
                    break
            if is_substring:
                continue

            # 检查短语是否仍存在于当前文本中
            # （之前的替换可能已经消除了该短语的出现）
            if phrase not in compressed_text:
                continue

            code = self.CIRCLED_NUMBERS[code_index]
            code_index += 1

            phrase_dict[code] = phrase
            selected_phrases.append(phrase)

            # 替换文本中的短语（从最高频的开始，避免嵌套替换）
            compressed_text = compressed_text.replace(phrase, code)

        if phrase_dict:
            logger.info(
                f"_compress_phrases: 编码 {len(phrase_dict)} 个高频短语，"
                f"前5个: {dict(list(phrase_dict.items())[:5])}"
            )

        return compressed_text, phrase_dict

    def _extract_phrase_candidates(self, text: str) -> Dict[str, int]:
        """提取高频短语候选

        使用n-gram方法：提取所有2-gram到6-gram，统计频率，
        筛选出现>=2次且长度在3-20字符之间的子串。

        排除包含换行符的子串，避免跨行替换。

        Args:
            text: 待提取的文本

        Returns:
            候选短语及其频率 {phrase: frequency}
        """
        # 移除编码符号行（以①②等开头的行是已压缩的前缀行，其内容仍需分析）
        # 但需要排除编码符号本身作为短语的一部分
        encoded_symbols = set(self.CIRCLED_NUMBERS)

        # 按行分析，避免跨行n-gram
        counter = Counter()

        lines = text.split('\n')
        for line in lines:
            # 跳过空行
            if not line.strip():
                continue

            # 移除行首的编码符号（前缀压缩后的①②等）
            content = line
            if content and content[0] in encoded_symbols:
                content = content[1:]

            content = content.strip()
            if not content:
                continue

            # 提取n-gram
            for n in range(self.MIN_NGRAM, self.MAX_NGRAM + 1):
                for i in range(len(content) - n + 1):
                    ngram = content[i:i + n]

                    # 过滤条件
                    if len(ngram) < self.MIN_PHRASE_LEN:
                        continue
                    if len(ngram) > self.MAX_PHRASE_LEN:
                        continue

                    # 排除包含编码符号的n-gram
                    if any(sym in ngram for sym in encoded_symbols):
                        continue

                    # 排除包含换行符的n-gram
                    if '\n' in ngram:
                        continue

                    # 排除纯空白或纯标点的n-gram
                    stripped = ngram.strip()
                    if not stripped:
                        continue

                    # 排除只包含标点符号的n-gram
                    if all(c in '，。、；：！？,.:;!? ' for c in stripped):
                        continue

                    # 排除以标点开头或结尾的n-gram（避免"头痛，"、"，但是"等）
                    if stripped[0] in '，。、；：！？,.:;!? ':
                        continue
                    if stripped[-1] in '，。、；：！？,.:;!? ':
                        continue

                    # 排除中间全是标点的n-gram（如"好，谢"）
                    inner_chars = stripped[1:-1]
                    if inner_chars and all(c in '，。、；：！？,.:;!? ' for c in inner_chars):
                        continue

                    counter[ngram] += 1

        # 筛选出现>=2次的短语
        candidates = {
            phrase: freq
            for phrase, freq in counter.items()
            if freq >= self.MIN_PHRASE_FREQ
        }

        logger.info(
            f"_extract_phrase_candidates: 提取到 {len(candidates)} 个候选短语"
        )

        return candidates
