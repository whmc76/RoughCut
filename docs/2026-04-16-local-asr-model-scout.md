# 本地 ASR 模型摸排与对比建议（2026-04-16）

这份说明只针对 RoughCut 当前场景：中文口播、开箱、带品牌/型号热词、需要较稳的分段和时间戳，并且优先考虑本地部署与批量跑对比。

## 结论先说

- 第一优先：`Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B`
  - 这是当前最值得作为主力候选的本地方案。
  - 官方模型卡给出的公开与内部 benchmark 里，它在中文普通话、中文方言、粤语、多语、带 BGM 歌曲转写上都明显强于 `Whisper-large-v3`，并且保留了本地部署能力。
  - 如果你关心字幕时间戳质量，强烈建议把 forced aligner 一起测。

- 第二优先：`Qwen3-ASR-0.6B + Qwen3-ForcedAligner-0.6B`
  - 这是更现实的速度/显存折中方案。
  - 官方给出它和 1.7B 同样支持 52 种语言与方言，0.6B 版本强调高吞吐，适合作为“可常驻服务”的对照组。
  - 如果 1.7B 的显存或并发压力太高，先用它做服务化更稳。

- 多语基线：`Whisper large-v3`、`Whisper large-v3-turbo`
  - 适合做英文或广义多语基线，不适合在这个仓库里当中文主力。
  - `large-v3` 仍然值得保留，因为 Qwen 官方 benchmark 直接拿它做了对比。
  - `large-v3-turbo` 更适合测吞吐，不应默认假设它比 `large-v3` 更准。

- 中文延迟基线：`FunASR paraformer-zh`、`SenseVoiceSmall`
  - 这两类更像速度/工程成本基线，而不是“最强精度”。
  - `paraformer-zh` 适合做中文低延迟对照。
  - `SenseVoiceSmall` 更适合看多语、情感标签、轻量部署，但在本项目的品牌/型号识别稳定性上不应默认压过 Qwen3-ASR。

## 不建议现在优先接入的方案

- `distil-whisper/distil-large-v3`
  - 它适合作为英文蒸馏基线，不适合中文主场景主力模型。
  - 可以测，但应单独标记为英文速度基线，不要混在中文主榜里解释。

- NVIDIA NIM / Parakeet / Canary
  - 这类方案更偏 Linux + NVIDIA 生态集成。
  - 对当前 Windows 工作区和本仓库现有 provider 形态来说，接入成本明显高于收益。
  - 如果后面要上统一 Chat API 推理网关，再单独评估更合适。

## 建议的测试分组

### A 组：主力候选

- `qwen3_asr_1_7b`
- `qwen3_asr_1_7b_aligned`
- `qwen3_asr_0_6b`
- `qwen3_asr_0_6b_aligned`

### B 组：多语/英文基线

- `faster_whisper_large_v3`
- `faster_whisper_large_v3_turbo`
- `faster_whisper_distil_large_v3`

### C 组：中文轻量基线

- `funasr_paraformer_zh`
- `funasr_sensevoice_small`

## 本仓库里的落地方式

仓库已经有统一脚本 [scripts/benchmark_local_asr.py](/E:/WorkSpace/RoughCut/scripts/benchmark_local_asr.py)。

默认候选我已经改成更适合当前摸排的组合，直接跑：

```bash
uv run python scripts/benchmark_local_asr.py --limit 5 --sample-seconds 90
```

只测 Qwen 主力组：

```bash
uv run python scripts/benchmark_local_asr.py \
  --limit 5 \
  --sample-seconds 90 \
  --candidates qwen3_asr_1_7b qwen3_asr_1_7b_aligned qwen3_asr_0_6b qwen3_asr_0_6b_aligned
```

只测多语基线：

```bash
uv run python scripts/benchmark_local_asr.py \
  --limit 5 \
  --sample-seconds 90 \
  --candidates faster_whisper_large_v3 faster_whisper_large_v3_turbo faster_whisper_distil_large_v3
```

建议固定三类样本：

- 安静口播
- 带背景音乐的口播
- 品牌/型号密集、容易错专有名词的片段

## 判分建议

当前脚本主要输出速度、文本长度、词级时间戳可用性和转写预览。要做真正决策，建议再人工抽检三类指标：

- 专有名词命中率
- 断句可读性
- 时间戳可编辑性

如果后续要把结果固化成真正可排序的回归基线，下一步应补：

- 参考文本 `reference.txt`
- CER / WER 统计
- 品牌词、型号词的关键词命中率
- “时间戳可用率”单独评分

## 官方资料

- Qwen3-ASR 模型卡：<https://huggingface.co/Qwen/Qwen3-ASR-0.6B>
- Whisper large-v3 模型卡：<https://huggingface.co/openai/whisper-large-v3>
- SenseVoice 仓库：<https://github.com/FunAudioLLM/SenseVoice>
- FunASR paraformer-zh 模型卡：<https://huggingface.co/funasr/paraformer-zh>
