# 中文 ASR 路线盘点

##### [**Undermind**](https://undermind.ai)

---

## 中文 ASR 路线盘点

这份盘点面向前端语音转写模块选型。目标不是挑出一个绝对最强模型，而是把几条主流路线在中文公开 benchmark、医疗相关证据、接入成本与工程成熟度上的差异摆清楚。对当前项目来说，ASR 负责输出原始文本，医疗术语规范化和结构化病历由后端大模型完成，所以选型重点应放在原始转写是否稳、长音频和对话是否好处理、以及能否低成本接入现有系统 \[1\], \[2\], \[3\], \[4\], \[5\]。

从现有证据看，中文可落地路线大致分成两类。一类是以 FunASR 与 WeNet 为代表的中文工业化工具链，强项是中文数据、完整流水线、流式能力和部署成熟度 \[1\], \[2\]。另一类是以 Whisper、Qwen3-ASR、Qwen2-Audio 为代表的多语种基础模型或音频大模型路线，强项是跨域泛化、统一建模和更强的开放场景覆盖 \[3\], \[4\], \[5\]。如果只看当前公开证据，前一类更像稳妥主线，后一类更像需要实测验证的增强路线。

## 结论速览

| 路线 | 中文公开证据 | 工程特征 | 主要风险 | 更适合扮演的角色 |
|:---|:---|:---|:---|:---|
| FunASR 与 Paraformer \[1\], \[6\] | 在 AISHELL 和 WenetSpeech 上成绩强，Paraformer large 在 AISHELL test 为 1.95，AISHELL 2 test ios 为 2.85，WenetSpeech meeting 为 6.97 | 自带 VAD、标点、时间戳、热词、量化和多后端，接入链路完整 | 以离线长音频和文件转写见长，原生流式能力不是主卖点 | 中文前端转写默认候选 |
| WeNet \[2\], \[7\] | U2++ 在 AISHELL 1 full 为 4.63，chunk 16 为 5.05，AISHELL 2 full 为 5.39，chunk 16 为 5.78 | 流式与非流式统一，量化、上下文偏置、LM 与 WFST 更成熟 | 公开分数不是最激进，但强项在低延迟工程化 | 实时转写与长期工程主线 |
| Whisper \[3\], \[8\] | 零样本鲁棒性强，但中文公开结果并不占优。Whisper large v2 在 Fleurs zh 为 13.8，在 Common Voice 9 Chinese 为 26.8 | 开源生态成熟，跨语种和长尾场景经验丰富 | 中文不是原生优势，非流式，真正落地常要蒸馏或二次改造 | 强基线与跨域兜底方案 |
| Qwen3 ASR \[4\] | 公共中文结果很强。1.7B 在 AISHELL 2 test 为 2.71，WenetSpeech net 为 4.97，meeting 为 5.88，Fleurs zh 为 2.41 | Apache 2.0，吞吐和首 token 延迟都很好 | 论文很新，部分关键结论依赖内部评测 | 新一代高性能候选，值得做 POC |
| Qwen2 Audio \[5\] | 有中文 ASR 成绩，AISHELL 2 各子集约 2.9 到 3.0，Fleurs zh 为 7.5 | 能统一处理语音、声音、多说话人和交互指令 | 本质是音频语言模型，不是纯前端转写器，模型很大 | 需要音频理解与交互时再考虑 |
| FireRedASR \[9\] | 中文公开成绩目前非常亮眼。LLM 版在四个中文集平均 CER 为 3.05，AED 版为 3.18 | 同时提供高性能 LLM 路线和更省算力的 AED 路线 | 体量仍大，工程生态还在形成 | 高性能参考线和候选增补 |

## 公开分数该怎么读

同样叫“中文 ASR 分数”，背后常常不是同一种任务。AISHELL 1 是干净的朗读语音基准，适合看模型在标准普通话条件下的上限 \[10\]。AISHELL 2 更接近工业训练规模，但仍以干净朗读为主 \[11\]。WenetSpeech 的 Test Net 和 Test Meeting 更接近真实场景，其中 Meeting 明显更难，能更好暴露长音频、口语化和环境失配问题 \[12\]。AISHELL 4 又把多人会议、重叠和说话人切换带进来了，和医疗对话的复杂度更接近一些 \[13\]。

不同论文还会混用 CER、WER、MER，混用零样本、微调后、流式和离线设置。SpeechColab 专门指出，标点、大小写、分词、同义写法和评分流程都会明显影响最终榜单 \[14\]。因此，中文 ASR 选型不能把不同论文里的单个数字直接横比，更可靠的做法是同时看三件事：公开中文 benchmark 是否持续强，证据是否和项目场景匹配，以及论文是否给出可部署的运行时与流水线信息。

| 基准 | 更像在测什么 | 对当前项目的意义 |
|:---|:---|:---|
| AISHELL 1 \[10\] | 干净普通话朗读 | 看中文基础识别上限 |
| AISHELL 2 \[11\] | 更大规模工业化朗读语音 | 看模型在中文公开工业基准上的竞争力 |
| WenetSpeech \[12\] | 多域真实录音，尤其是 Meeting 子集 | 看长音频、真实场景和域外稳健性 |
| AISHELL 4 \[13\] | 多人会议与重叠语音 | 看对复杂对话场景的外推能力 |
| MMedFD \[15\] | 中文医疗全双工真实对话 | 看医疗场景真正的硬点 |

## 几条路线的证据差异

### FunASR 与 Paraformer

FunASR 的优势不只在单个模型，而在成套前端流水线。工具箱把 Paraformer、FSMN VAD、CT Transformer 标点恢复、时间戳预测、热词定制、量化与多后端部署打包成一条完整链路 \[1\]。对研发团队来说，这意味着从音频切分到转写输出，不必先拼很多外部组件。

Paraformer 本身是非自回归模型，核心价值是把中文转写做得足够快。该文在 AISHELL 1 上做到 5.2 CER，与自回归基线基本持平，同时推理速度超过 12 倍 \[6\]。到了 FunASR 的 Paraformer large，公开中文成绩进一步拉高到 AISHELL test 1.95、AISHELL 2 test ios 2.85、WenetSpeech meeting 6.97 \[1\]。这组结果的意义不是“学术上绝对最好”，而是它同时给出了中文 benchmark、部署后端和量化运行时。

更重要的是，这条线对医疗场景最敏感的那类错误有后续抓手。FunASR 里的热词能力在 AISHELL 命名实体子集上把 F1 从 27 提高到 85 \[1\]。如果后端大模型负责术语规范化，那么前端只要尽量把药名、病名、检查名先听对，这种热词与偏置能力就很关键。

### WeNet

WeNet 的路线更偏实时系统。U2 和 U2++ 把流式和非流式放进一套模型里，第一遍用 CTC 先吐结果，第二遍用注意力重排序修正结果 \[2\], \[7\]。这种结构的现实意义很直接：同一套工程既能做低延迟转写，也能做更高精度的最终结果。

在公开中文集上，WeNet 2.0 的 U2++ 在 AISHELL 1 full 为 4.63，chunk 16 为 5.05，在 AISHELL 2 full 为 5.39，chunk 16 为 5.78 \[2\]。这些分数本身未必压过最新大模型路线，但它的强项在于配套能力更完整。该文把 n gram LM、WFST 解码和 contextual biasing 纳入了统一工具链，而且偏置在正样本集上可把 CER 从 14.94 拉到 6.17 \[2\]。对需要持续维护术语表的医疗项目，这类能力很实用。

运行时数据也比较扎实。早期 WeNet 论文在 x86 上给出 int8 量化后 RTF 约 0.072 到 0.134，流式最终延迟约 130 到 142 毫秒 \[7\]。如果团队后面更在意实时交互和低延迟，而不是只做离线录音转写，WeNet 的证据会比 FunASR 更贴场景。

### Whisper

Whisper 的核心证据来自大规模弱监督训练，而不是中文专门优化。它用 68 万小时多语数据做统一训练，主要卖点是零样本泛化和跨域鲁棒性 \[3\]。这解释了为什么 Whisper 在很多开放场景里很好用，也解释了为什么它经常被拿来当强基线。

但把它放到中文前端转写选型里，问题也很明确。该文自己就指出，byte level BPE tokenizer 对中文这类文字系统并不理想，而且中文表现低于按训练数据规模应有的预期 \[3\]。公开中文结果也说明了这一点。Whisper large v2 在 Fleurs zh 为 13.8，在 Common Voice 9 Chinese 为 26.8，优势不在中文专门 benchmark \[3\]。后续 Distil Whisper 的价值主要是把速度和长音频稳定性做得更好，而不是把中文变成原生强项 \[8\]。

这并不意味着 Whisper 不该用。它仍然很适合作为跨域鲁棒基线，尤其适合混合语种、开放口音或数据分布不稳定的场景 \[3\]。但如果目标是中文医疗前端转写，Whisper 更像必须纳入对照实验的一条线，而不是最自然的默认主线。若要做实时系统，还要额外引入两遍解码等适配工作 \[16\], \[17\]。

### Qwen3 ASR 与 Qwen2 Audio

“QwenASR”这几个字在讨论里容易混成一条线，但实际上至少要分开看。Qwen3 ASR 是专门面向 ASR 的模型家族，而 Qwen2 Audio 是更广义的音频语言模型 \[4\], \[5\]。

Qwen3 ASR 的公开中文成绩很有竞争力。1.7B 版本在 AISHELL 2 test 为 2.71，在 WenetSpeech net 和 meeting 为 4.97 与 5.88，在 Fleurs zh 为 2.41 \[4\]。同时，0.6B 版本给出 92 毫秒首 token 延迟和很高吞吐，许可证还是 Apache 2.0。单看论文里的公开分数，它已经进入中文 ASR 第一梯队。

真正需要谨慎的地方在于证据的新鲜度和来源。技术报告明确说，之所以加入大量内部评测，是因为公开 benchmark 已接近标注误差上限 \[4\]。这并非没有道理，但也意味着部分“远超竞品”的结论不是建立在完全可复验的公开榜单上。对于项目选型，这条线很值得做 POC，但还不宜只凭论文直接定为唯一方案。

Qwen2 Audio 则是另一回事。它确实在 AISHELL 2 和 Fleurs zh 上有不错结果，但论文的中心目标是音频理解、语音交互和多模态指令跟随，而不是把自己当作一个纯前端转写器 \[5\]。8.2B 体量也意味着接入成本更高。若项目以后想把“听懂音频并直接执行指令”并进同一模型，这条线才会更有吸引力。若只是想把语音稳定转成文本，它并不是最经济的选项。

### FireRedASR

FireRedASR 不是这次最初点名的路线，但它已经足够强，值得放进对照表。该文给了两条路：一条是 8.3B 的 LLM 版，另一条是 1.1B 的 AED 版 \[9\]。前者在四个中文公开集的平均 CER 为 3.05，后者为 3.18，而且 AED 版已经优于不少更大的模型。

这条路线说明了一个重要趋势：中文公开榜单上，纯中文训练路线和 LLM 融合路线都在快速推进 \[9\]。对当前项目，它更像一个高性能参考线。若团队愿意接受更大的模型规模，FireRedASR 与 Qwen3 ASR 都值得并行做一次小规模实测。

## 医疗场景证据

公开中文医疗 ASR benchmark 仍然很少，MMedFD 的价值就在这里。它是面向真实中文医疗全双工对话的数据集，包含 5805 个标注 session，并给出普通 WER、CER 以及面向医疗概念的 HC WER \[15\]。这个基准的重要性不在于它把某个模型做得很漂亮，而在于它把医疗场景真正难的地方暴露出来了。

在 MMedFD 上，微调后的 Whisper small 平均 WER 为 27.48，CER 为 26.95，HC WER 为 12.59。其中 user 一侧的 WER 高达 53.11，而 agent 一侧只有 1.84 \[15\]。这说明医疗对话的难点不是“模型会不会医学术语”，而是重叠、打断、回声、远场和说话人切换把前端转写变得很难。对当前项目，这个结论很关键，因为后端大模型再强，也不能补回前端根本没听到的词。

另一个医疗启示来自稀有词处理。MED IT 这类医疗访谈数据上，post decoder biasing 对低频词能带来 9.3 和 5.1 的相对改善 \[18\]。在中文端，contextual biasing 研究也给出了类似方向的证据。基于 WenetSpeech 偏置集的工作中，spike triggered deep biasing 对整体 CER 带来 32.0 的相对下降，对偏置短语带来 68.6 的相对下降 \[19\]。另一篇中文偏置综述实验也表明，预识别、模型内、解码和后处理四类方法都能在特定领域词上提升识别效果 \[20\]。

| 医疗前端真正需要的能力 | 证据 |
|:---|:---|
| 长对话与复杂回合处理 | MMedFD 显示全双工和多轮交互显著拉高错误率 \[15\] |
| 重叠语音与回声鲁棒性 | 同一基准里 user 侧远难于 agent 侧，说明部署声学条件是主问题 \[15\] |
| 稀有术语与实体召回 | 医疗访谈偏置和中文 contextual biasing 都证明术语表能显著提升低频词识别 \[18\], \[19\], \[20\] |
| 流水线可控性 | VAD、分段、时间戳、热词和上下文偏置常比单点 CER 更决定可用性 \[1\], \[2\] |

## 面向当前项目的选择框架

如果团队希望先上一个稳定的中文前端转写模块，再把术语规范化和结构化交给后端大模型，那么选型可以按下面的顺序想。

- 批量录音转写优先时，FunASR 与 Paraformer 是最稳的起点 \[1\], \[6\]
- 实时性和低延迟优先时，WeNet 更自然，因为流式和偏置能力更成熟 \[2\], \[7\]
- 需要一个跨域鲁棒强基线时，应纳入 Whisper，但更适合作为对照线 \[3\]
- 团队愿意承担更新模型的验证成本时，Qwen3 ASR 和 FireRedASR 值得做并行 POC \[4\], \[9\]
- 仅在希望把音频理解、语音交互和转写合并到同一大模型时，才优先考虑 Qwen2 Audio \[5\]

从中立盘点的角度，当前证据最清楚的一点不是“某个模型绝对最好”，而是“不同路线解决的是不同问题”。中文工程化、低延迟可控、跨域零样本鲁棒、以及大模型统一建模，这四个目标并没有在同一条路线里同时达到最优。对当前项目，最合理的做法不是先押注单一明星模型，而是用公开中文 benchmark 和一小批真实医疗录音，做一轮面向项目指标的并行实测，再决定主线。

---

## References

\[1\] Z. Gao *et al.*, “FunASR: A Fundamental End-to-End Speech Recognition Toolkit,” *ArXiv*, vol. abs/2305.11013, May 2023, doi: [10.48550/arXiv.2305.11013](https://doi.org/10.48550/arXiv.2305.11013).

\[2\] B. Zhang *et al.*, “WeNet 2.0: More Productive End-to-End Speech Recognition Toolkit,” *Interspeech*, pp. 1661–1665, Mar. 2022, doi: [10.48550/arXiv.2203.15455](https://doi.org/10.48550/arXiv.2203.15455).

\[3\] A. Radford, J. W. Kim, T. Xu, G. Brockman, C. McLeavey, and I. Sutskever, “Robust Speech Recognition via Large-Scale Weak Supervision,” *International Conference on Machine Learning*, pp. 28492–28518, Dec. 2022.

\[4\] Q. Team, “Qwen3-ASR Technical Report,” *ArXiv*, vol. abs/2601.21337, Jan. 2026, doi: [10.48550/arXiv.2601.21337](https://doi.org/10.48550/arXiv.2601.21337).

\[5\] Y. Chu *et al.*, “Qwen2-Audio Technical Report,” *ArXiv*, vol. abs/2407.10759, Jul. 2024, doi: [10.48550/arXiv.2407.10759](https://doi.org/10.48550/arXiv.2407.10759).

\[6\] Z. Gao, S. Zhang, I. Mcloughlin, and Z. Yan, “Paraformer: Fast and Accurate Parallel Transformer for Non-autoregressive End-to-End Speech Recognition,” *Interspeech*, pp. 2063–2067, Jun. 2022, doi: [10.48550/arXiv.2206.08317](https://doi.org/10.48550/arXiv.2206.08317).

\[7\] Z. Yao *et al.*, “WeNet: Production Oriented Streaming and Non-Streaming End-to-End Speech Recognition Toolkit,” *Interspeech*, pp. 4054–4058, Feb. 2021, doi: [10.21437/interspeech.2021-1983](https://doi.org/10.21437/interspeech.2021-1983).

\[8\] S. Gandhi, P. von Platen, and A. M. Rush, “Distil-Whisper: Robust Knowledge Distillation via Large-Scale Pseudo Labelling,” *ArXiv*, vol. abs/2311.00430, Nov. 2023, doi: [10.48550/arXiv.2311.00430](https://doi.org/10.48550/arXiv.2311.00430).

\[9\] K.-T. Xu, F. Xie, X. Tang, and Y. Hu, “FireRedASR: Open-Source Industrial-Grade Mandarin Speech Recognition Models from Encoder-Decoder to LLM Integration,” *ArXiv*, vol. abs/2501.14350, Jan. 2025, doi: [10.48550/arXiv.2501.14350](https://doi.org/10.48550/arXiv.2501.14350).

\[10\] H. Bu, J. Du, X. Na, B. Wu, and H. Zheng, “AISHELL-1: An open-source Mandarin speech corpus and a speech recognition baseline,” *2017 20th Conference of the Oriental Chapter of the International Coordinating Committee on Speech Databases and Speech I/O Systems and Assessment (O-COCOSDA)*, pp. 1–5, Sep. 2017, doi: [10.1109/ICSDA.2017.8384449](https://doi.org/10.1109/ICSDA.2017.8384449).

\[11\] J. Du, X. Na, X. Liu, and H. Bu, “AISHELL-2: Transforming Mandarin ASR Research Into Industrial Scale,” *ArXiv*, vol. abs/1808.10583, Aug. 2018.

\[12\] B. Zhang *et al.*, “WENETSPEECH: A 10000+ Hours Multi-Domain Mandarin Corpus for Speech Recognition,” *ICASSP 2022 - 2022 IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)*, pp. 6182–6186, Oct. 2021, doi: [10.1109/icassp43922.2022.9746682](https://doi.org/10.1109/icassp43922.2022.9746682).

\[13\] Y. Fu *et al.*, “AISHELL-4: An Open Source Dataset for Speech Enhancement, Separation, Recognition and Speaker Diarization in Conference Scenario,” *Interspeech*, pp. 3665–3669, Apr. 2021, doi: [10.21437/interspeech.2021-1397](https://doi.org/10.21437/interspeech.2021-1397).

\[14\] J. Du, J. Li, G. Chen, and W.-Q. Zhang, “SpeechColab Leaderboard: An Open-Source Platform for Automatic Speech Recognition Evaluation,” *Comput. Speech Lang.*, vol. 94, p. 101805, Mar. 2024, doi: [10.1016/j.csl.2025.101805](https://doi.org/10.1016/j.csl.2025.101805).

\[15\] H. Chen *et al.*, “MMedFD: A Real-world Healthcare Benchmark for Multi-turn Full-Duplex Automatic Speech Recognition,” Sep. 24, 2025.

\[16\] H. Zhou *et al.*, “Adapting Whisper for Streaming Speech Recognition via Two-Pass Decoding,” *ArXiv*, vol. abs/2506.12154, Jun. 2025, doi: [10.48550/arXiv.2506.12154](https://doi.org/10.48550/arXiv.2506.12154).

\[17\] R. Wang, Z. Xu, and F. Lin, *WhisperFlow: speech foundation models in real time*. 2024. doi: [10.1145/3711875.3729151](https://doi.org/10.1145/3711875.3729151).

\[18\] H. Liu, Y. Wang, and Y. Wang, “Post-decoder Biasing for End-to-End Speech Recognition of Multi-turn Medical Interview,” *ArXiv*, vol. abs/2403.00370, Mar. 2024, doi: [10.48550/arXiv.2403.00370](https://doi.org/10.48550/arXiv.2403.00370).

\[19\] K. Huang, A. Zhang, B. Zhang, T. Xu, X. Song, and L. Xie, “Spike-Triggered Contextual Biasing for End-to-End Mandarin Speech Recognition,” *2023 IEEE Automatic Speech Recognition and Understanding Workshop (ASRU)*, pp. 1–8, Oct. 2023, doi: [10.1109/ASRU57964.2023.10389631](https://doi.org/10.1109/ASRU57964.2023.10389631).

\[20\] K. Zhang, Q. Zhang, C.-C. Wang, and J.-S. R. Jang, “Contextual Biasing for End-to-End Chinese ASR,” *IEEE Access*, vol. 12, pp. 92960–92975, 2024, doi: [10.1109/ACCESS.2024.3424260](https://doi.org/10.1109/ACCESS.2024.3424260).
