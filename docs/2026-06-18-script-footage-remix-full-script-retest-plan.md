# 文案保真版影视二创链路改造与重测方案

## 背景

本方案覆盖“文案引用原片型”影视动画二创剪辑链路的纠偏改造和重新测试。

旧版 Bluey 批量验证曾跑通 10 集，但默认使用了 `condense_script_for_sample(...)` 压缩文案，把 4-5 分钟文案整理到约 2-3 分钟。这与当前业务合同冲突：用户给定文案已经是打磨后的成稿，不允许为了时长自动删句、摘要、压缩或截断。

因此，旧的 10 集 `gate_passed=true` 只能证明 TTS、ASR、渲染、报告等工程链路可运行，不能作为最终编辑质量收口证据。新一轮重测必须基于完整文案。

## 新合同

### 硬合同

- 原始文案是成稿事实源。
- 默认完整文案进入 TTS。
- 不自动删句。
- 不自动摘要。
- 不自动压缩。
- 不自动截断字符。
- 不为了 2-3 分钟目标改写文案。
- 字幕显示文本来自原始文案，不来自 ASR 幻听文本。

### 允许处理

- MOSS TTS 生成旁白。
- TTS 分段拼接。
- 句首/句尾气口裁剪。
- 内部长静音压缩。
- Qwen3 TTS-ASR/ForcedAligner 只提供字幕时间戳。
- Source-ASR 只用于原片剧情/主题定位。
- 原片画面按主题级连续段落引用。
- 画面裁切/放大以处理平台 logo 和原片字幕。
- 字幕包装、主题条、关键词贴纸、重点字特效。

### 时长策略

- `120-180s` 是发布目标区间，不是硬剪文案规则。
- 超过 180 秒：QA 记 `remix_output_duration_out_of_range` warning。
- 低于 120 秒：QA 也记 warning，优先检查是否过度裁剪气口或 TTS 异常。
- 只有无效时长、无音频、ASR 失败、证据缺失、字幕来源错误等才算 hard fail。

## 已完成代码改造

### 文案入口

文件：`scripts/build_script_footage_remix_samples.py`

- 默认不再调用 `condense_script_for_sample(...)`。
- 新增 `resolve_script_text_for_tts(...)` 作为唯一 TTS 文案入口。
- 默认返回完整 `script.body.strip()`。
- `--max-script-chars` 直接报错，防止截断。
- `--condense-script` 保留为显式实验开关，不属于正式链路。
- `--final-target-duration-sec` 默认改为 `0.0`，不再默认把音频适配到 148 秒。

### QA 质量门

文件：`src/roughcut/remix/qa.py`

- `output_duration_sec <= 0` 仍然 fail。
- 超出 `120-180s` 改为 warn。
- ASR、字幕来源、Source-ASR、scene index、caption package、review frames 仍按原质量门执行。

### 批量报告

文件：`src/roughcut/remix/batch_report.py`

- `pass_rate` 改为按 `pass + warn` 计算可交付通过率。
- `fail` 和 required evidence missing 仍然阻断 `gate_passed`。
- 正式批量报告会验证必需证据文件真实存在，不能只靠路径字段非空过门。
- 方法论报告明确写入：时长超目标不能通过自动压缩文案解决。

### 回归测试

文件：`tests/test_remix_quality_contracts.py`

新增覆盖：

- 默认完整保留文案。
- `--max-script-chars` 被拒绝。
- 只有显式 `--condense-script` 才会压缩。
- 完整文案导致超时长时 QA 是 warn，不是 fail。
- batch 接受 warn 作为可交付集。

## 旧证据处理

以下目录只能作为旧策略工程证据，不再作为最终编辑收口证据：

```text
output/bluey-remix-samples-final
output/bluey-remix-batch-10
```

原因：

- 这些样片和报告来自旧的默认文案压缩策略。
- 成片时长符合 2-3 分钟，但不是完整文案成片。
- 后续报告必须明确标注为 `condensed-script legacy evidence`。

## 新重测输出目录

建议使用全新目录，避免旧缓存和旧报告混淆：

```text
output/bluey-remix-full-script-samples
output/bluey-remix-full-script-batch-10   # 可选 10 集压力测试
```

每集目录仍应包含：

```text
bluey_s02eXX_<title>_parenting_remix.mp4
s02eXX_narration.wav
s02eXX_narration_clean.wav
s02eXX_narration.ass
s02eXX_topic_plan.json
s02eXX_edit_plan.json
s02eXX_qa_report.json
s02eXX_caption_package.json
s02eXX_scene_index.json
s02eXX_review_frames.json
review_frames/
_work/s02eXX_tts_qwen3_asr_alignment.json
_work/s02eXX_source_qwen3_asr_index.json
```

批量目录必须包含：

```text
script_footage_remix_sample_report.json
script_footage_remix_sample_report.md
batch_report.json
batch_report.md
methodology_report.md
```

## 重测阶段

### P0：代码回归

目的：证明新合同已被单元测试锁住。

命令：

```powershell
$env:PYTHONPATH='src'
python -m py_compile `
  scripts\build_script_footage_remix_samples.py `
  src\roughcut\remix\qa.py `
  src\roughcut\remix\batch_report.py `
  tests\test_remix_quality_contracts.py `
  tests\test_remix_cli.py
```

```powershell
$env:PYTHONPATH='src'
python -m pytest `
  tests\test_remix_quality_contracts.py `
  tests\test_remix_cli.py `
  -q --basetemp .tmp\pytest-full-script-retest
```

通过条件：

- `resolve_script_text_for_tts` 默认完整返回原文。
- 截断参数失败。
- duration warning 不导致 QA fail。
- batch 可接受 warn 作为可交付集。

### P1：单集冒烟

目的：先用 1 集完整文案跑通 TTS、TTS-ASR、Source-ASR、渲染和报告。

建议先跑第 1 集：

```powershell
$env:PYTHONPATH='src'
python -m roughcut.cli remix script-footage `
  --source-root "F:\布鲁伊育儿节目" `
  --episodes 1 `
  --output-dir output\bluey-remix-full-script-samples `
  --qwen3-asr-base http://127.0.0.1:30230 `
  --force
```

检查点：

- `s02e01_narration.wav` 是完整文案 TTS。
- `s02e01_narration_clean.wav` 只处理气口，不删内容。
- `_work/s02e01_tts_qwen3_asr_alignment.json` 存在且 `status=done`。
- `s02e01_qa_report.json` 不因时长超 180 秒 fail。
- 如时长超目标，QA issues 应包含 duration warning。
- 如重复使用已有输出目录，使用 `--force` 或 `--force-tts` 确保不会复用旧压缩文案 TTS。

### P2：单集样片

目的：生成可试看样片，重点观察完整文案下的节奏、字幕密度、主题级连续选段是否仍成立。

命令：

```powershell
$env:PYTHONPATH='src'
python -m roughcut.cli remix script-footage `
  --source-root "F:\布鲁伊育儿节目" `
  --episodes 1 `
  --output-dir output\bluey-remix-full-script-samples `
  --qwen3-asr-base http://127.0.0.1:30230
```

检查点：

- 每集有 TTS 配音主体。
- 字幕时间戳来自 Qwen3 TTS-ASR。
- 原片定位来自 Source-ASR。
- 画面仍按主题块连续播放，不逐句跳切。
- 画面 crop 后输出 `1920x1080`。
- 原片底部字幕和平台 logo 不主导画面。
- 长气口被压缩，但文案句子没有消失。

人工试看重点：

- 完整文案是否导致信息过密。
- 字幕是否需要更大分段或更强包装。
- 超 3 分钟是否仍可作为长版成片接受。
- 如果需要短版，必须作为单独人工批准的“二次改稿任务”，不能自动做。

### P3：可选十集批量

目的：在用户明确要求压测时，证明完整文案策略下链路仍可批量稳定运行。默认收口不需要跑这一步。

命令：

```powershell
$env:PYTHONPATH='src'
python -m roughcut.cli remix script-footage `
  --source-root "F:\布鲁伊育儿节目" `
  --episodes 1,2,3,4,5,6,7,8,9,10 `
  --output-dir output\bluey-remix-full-script-batch-10 `
  --qwen3-asr-base http://127.0.0.1:30230
```

通过条件：

- `batch_report.json` 中 `sample_count >= 10`。
- `gate_passed=true`。
- `pass_rate >= 0.90`。
- `required_evidence_failures=[]`。
- `qa_fail_count=0`。
- duration warning 可以存在，但不能来自文案压缩缺失。

### P4：证据审计

目的：确认不是“看起来跑通”，而是证据链真实可用。

建议执行检查脚本：

```powershell
$env:PYTHONPATH='src'
@'
from pathlib import Path
import json

root = Path("output/bluey-remix-full-script-samples")
batch = json.loads((root / "batch_report.json").read_text(encoding="utf-8"))
sample = json.loads((root / "script_footage_remix_sample_report.json").read_text(encoding="utf-8"))
print({
    "sample_count": batch.get("sample_count"),
    "qa_pass_count": batch.get("qa_pass_count"),
    "qa_warn_count": batch.get("qa_warn_count"),
    "qa_fail_count": batch.get("qa_fail_count"),
    "pass_rate": batch.get("pass_rate"),
    "gate_passed": batch.get("gate_passed"),
    "gate_reason": batch.get("gate_reason"),
})
for row in batch.get("episodes_detail", []):
    print(row["episode"], row["title"], row["qa_status"], row["output_duration_sec"], row["tts_asr_coverage"], row["source_asr_anchor_count"], row["missing_required_evidence"])
reports = sample.get("reports") or []
path_fields = [
    "output_path",
    "narration_path",
    "render_narration_path",
    "subtitle_path",
    "caption_package_path",
    "topic_plan_path",
    "edit_plan_path",
    "qa_report_path",
    "review_frames_manifest_path",
    "scene_index_path",
    "tts_asr_evidence_path",
    "source_asr_index_path",
]
for report in reports:
    missing = [field for field in path_fields if not Path(str(report.get(field) or "")).exists()]
    if missing:
        raise SystemExit(f"episode {report.get('episode')} missing evidence files: {missing}")
    topic = json.loads(Path(report["topic_plan_path"]).read_text(encoding="utf-8"))
    tts_asr = json.loads(Path(report["tts_asr_evidence_path"]).read_text(encoding="utf-8"))
    caption = json.loads(Path(report["caption_package_path"]).read_text(encoding="utf-8"))
    print(
        "evidence",
        report["episode"],
        "script_chars=", topic.get("script_chars"),
        "canonical_char_count=", tts_asr.get("canonical_char_count"),
        "subtitle_event_count=", caption.get("subtitle_event_count"),
    )
'@ | python -
```

必须抽查每集：

- `topic_plan.json` 中 `script_chars` 接近原文案原始字符串长度。
- `tts_asr_alignment.json` 中 `canonical_char_count` 接近完整文案规范化后的字符数。
- `caption_package.json` 的 `subtitle_event_count` 与完整文案分段量匹配。
- `qa_report.json` 的 failure 不被 duration warning 误伤。

## 失败处理矩阵

| 现象 | 判定 | 修复方向 |
| --- | --- | --- |
| 成片超过 180 秒 | warning | 接受长版；或人工发起短版改稿，不自动压缩 |
| TTS-ASR coverage < 0.90 | hard fail | 检查 TTS 音频、ASR chunk、ForcedAligner、文本归一化 |
| Source-ASR anchors < 3 | hard fail | 增加候选窗口、检查原片音轨和 Qwen3 服务 |
| 字幕漂移 | hard fail 或人工阻断 | 修复 TTS-ASR token 时间轴，不回退 MOSS live segment |
| 画面仍有原字幕/logo | hard fail 或人工阻断 | 调整 crop/scale，重抽 review frames |
| 气口过长 | hard fail 或 warn，视长度 | 修复 silence trim，不删文案 |
| 字幕太密 | warn | 调整分屏和包装，不删文案 |
| TTS 生成耗时很长 | operational warn | 使用 TTS run 历史复用、分批预热，不换 TTS 默认 |

## 收口判定

新策略收口只能基于完整文案输出，不能引用旧压缩文案目录。

最终收口需要同时满足：

- 代码回归通过。
- 1 集完整文案样片可播放。
- `batch_report.json` 达到 `sample_count>=1`、`pass_rate>=0.90`、`gate_passed=true`。
- `batch_report.json` 达到 `qa_fail_count=0`、`required_evidence_failures=[]`。
- 每个通过集有 TTS、TTS-ASR、Source-ASR、scene index、topic plan、edit plan、caption package、QA、review frames。
- 所有 duration warning 明确标为“目标区间 warning”，不是 hard fail。
- 报告中不再出现“已将原始文案整理为约 148 秒”这类压缩口径。

## 下一步执行顺序

1. 跑 P0 回归。
2. 跑 P1 单集完整文案冒烟。
3. 人工试看 P1 成片，确认完整文案下节奏可接受。
4. 跑 P2 单集样片。
5. 复盘字幕密度、气口、画面连续性。
6. 仅在明确需要压测时跑 P3 十集批量。
7. 做 P4 证据审计。
8. 只有新目录通过后，才能重新标记最终收口。


