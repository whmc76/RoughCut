# 文案引用原片型影视二创剪辑链路优化目标与收口条件

## 目标定义

完成一条可复用、可批量、可验收的“文案引用原片型”影视动画二创剪辑链路。

这条链路的输入是成稿解说文案和对应原片，输出是解说主导成片。成片必须以新 TTS 旁白、新字幕包装和新叙事结构为主体，原片只作为剧情/主题画面证据使用。2-3 分钟是发布目标区间，不是改写或压缩成稿文案的理由。

本轮目标不是“做出几个能播放的视频”，而是把这类任务沉淀成稳定生产能力：同一套 CLI、模块合同、质量门和报告证据，能够在 1 集 Bluey 样本上重建完整样片。10 集批量运行保留为可选压力测试，不再作为默认收口条件。

## 目标合同

### 业务目标

- 把“育儿观点文案 + 对应原片”转成解说主导二创成片。
- 完整保留用户给定的成稿文案进入 TTS，不自动删句、摘要、压缩或截断。
- 画面围绕文案主题和剧情重点引用原片，不逐句硬配镜头。
- 最终成片参考已发布样片形态：TTS 旁白主导、原片画面作证据、底部字幕清晰、主题/重点包装可见、原片 logo 和底部原字幕被裁切或弱化。

### 工程目标

- 从样片脚本升级为可复用模块和正式 CLI。
- TTS、TTS-ASR、Source-ASR、主题拆解、选段、字幕包装、QA 都必须有稳定文件合同。
- 任何失败都必须落到明确质量门，不能只表现为“没生成 mp4”“ASR 失败后继续做假报告”。
- 批量任务必须能复用已完成 TTS 历史，避免换输出目录就重复生成同一文案的 MOSS 音频。

### 验收目标

- 1 集完整样片：证明单集成片质量和报告证据可复核。
- 可选 10 集批量验证：证明链路稳定性，不少于 90% 自动通过硬质量门；只有用户明确要求压测时才运行。
- 最终报告必须同时回答：怎么做、做出了什么、每集为什么通过或失败、失败该修哪里。

## 收口原则

- 以证据文件为准，不以聊天描述或主观承诺为准。
- 以正式 CLI 结果为准，不以手工临时命令或半成品目录为准。
- 以最终成片和 QA 报告共同通过为准，不以单个模块测试通过为准。
- ASR 是决定性能力：TTS-ASR 或 Source-ASR 缺失时，相关集数不能算完整样片。
- 如果 ASR/TTS/字幕/选段证据缺失，报告必须判失败，不能降级成“残余风险”继续收口。

## 适用类型

- 动画、影视、综艺、纪录片等已有原片素材。
- 已有二创文案，文案按集数、片段或主题对应原片。
- 成片形态是解说、观点、育儿分析、剧情拆解、知识化复盘，而不是原片搬运。
- 画面不要求逐句匹配，但必须按文案主题或剧情重点选择连续片段。

## 非目标

- 不做原片完整搬运。
- 不做逐句硬匹配镜头。
- 不把原片 ASR 当字幕时间戳来源。
- 不把 TTS ASR 当剧情定位来源。
- 不切换到 FunASR 作为默认或自动 fallback。
- 不把静音占位、无 TTS、无 ASR 证据的输出算作完整样片。

## 标准生产链路

```text
输入检查
-> 文案主题拆解
-> MOSS TTS 生成旁白
-> TTS 分段拼接与气口压缩
-> Qwen3 TTS-ASR/ForcedAligner 字幕对齐
-> 原片镜头边界检测
-> 原片 Qwen3 ASR 剧情索引
-> 主题级连续选段
-> 画面裁切/放大/去原字幕区
-> 剪映式字幕与关键词包装
-> MP4 渲染
-> 自动质量验收
-> 人工抽帧/试看复核
```

## 双 ASR 职责

### TTS-ASR

目的：给最终 TTS 配音生成字幕时间戳。

规则：

- 输入是最终用于成片的 TTS 音频，不是原片音频。
- 显示文本以原文案为准。
- ASR/ForcedAligner 只提供字/词时间戳。
- 覆盖率、时间线单调性和无声间隙是硬质量门。

### Source-ASR

目的：建立原片剧情/主题定位索引。

规则：

- 输入是原片音频或原片候选窗口音频。
- 输出用于匹配文案主题、剧情节点、角色和关键词。
- 不参与成片字幕时间戳。
- 与镜头边界、视觉关键帧一起决定画面段落。

## 必须产物

每集必须输出以下文件：

```text
final.mp4
narration_raw.wav
narration_clean.wav
tts_metadata.json
subtitle.ass
topic_plan.json
tts_asr_alignment.json
source_asr_index.json
scene_index.json
edit_plan.json
caption_package.json
qa_report.json
review_frames/
```

批量任务必须输出：

```text
batch_report.md
batch_report.json
methodology_report.md
```

## 质量门

### 输入门

- 文案和原片必须能按集数或任务 ID 对应。
- 文案必须能拆出不少于 5 个主题/剧情块。
- 文案是输入事实源，默认不得改写；只有用户显式要求“压缩/改写文案”时才可进入独立文案改写流程。
- 原片可读，时长、分辨率、音轨可探测。

### TTS 门

- 默认使用 MOSS TTS。
- 允许显式切 CosyVoice3 做 AB，但不能悄悄替换默认链路。
- TTS 输出必须非静音，RMS 不低于 `-45 dBFS`。
- 原始 TTS、清理后 TTS、TTS metadata 必须落盘。

### 气口门

- 句首/句尾无声压到 `0.05-0.10s`。
- 内部长气口超过 `0.35s` 必须压缩。
- 成片内部连续无声不得超过 `0.60s`。
- 气口压缩秒数和最大移除间隙必须写入报告。

### TTS-ASR 字幕门

- 字幕对齐来源必须是 `qwen3_asr_forced_aligner_on_tts`。
- TTS-ASR 覆盖率：
  - `>= 0.90`：通过。
  - `0.80-0.90`：允许生成，但必须进入人工抽检。
  - `< 0.80`：失败。
- 字幕事件必须单调，无负时长、无明显重叠。
- 字幕文本必须来自原文案，不得直接展示 ASR 幻听文本。

### 原片 ASR 定位门

- 每集至少生成 10 个候选 ASR 锚点。
- 可用 ASR 锚点少于 3 个直接失败。
- 每个主题块必须至少有 1 个候选画面段落。
- 原片 ASR 索引必须记录窗口起止、识别文本、关键词命中和分数。

### 选段门

- 每个主题块对应一段连续画面，不逐句跳切。
- 单段最短 `8s`，最长 `24s`。
- 相邻段起点间隔至少 `12s`。
- 视频轨总时长必须覆盖完整旁白音频，不得因选段过近导致成片截断文案。
- 原片片头、片尾、纯标题卡优先排除。

### 画面门

- 交付分辨率默认 `1920x1080`。
- Bluey bilibili 1080p 源默认使用 `crop=1440:810:180:50` 后放大。
- 原片右上角平台 logo 区和底部原字幕区必须被裁掉或弱化到不可主导。
- 成片不得保留原片音频作为主体。

### 包装门

- 必须包含底部主字幕。
- 必须包含常驻自有水印。
- 每集至少 3 个主题条/蓝条。
- 每集至少 3 个关键词贴纸或重点字特效。
- 关键词贴纸应使用气泡、贴纸、描边、弹跳等包装样式，不能只是素文字叠加。
- 字幕重点词必须有明显颜色、描边、缩放或高亮变化，不能整屏只有大片白字。
- 每集至少 6 个可听见的包装提示音 cue，用于主题条、关键词气泡或重点 chip。
- 字幕每屏最多两行，单屏建议 8-18 个汉字。

### 原片情景桥门

- 原片情景桥必须由 LLM 理解完整文案脚本后触发，不能用关键词规则乱加。
- 当文案明确要求“听原片/播放原声/听角色怎么说”，或正在描述原片里的具体场景、连续对话、角色动作、声音线索、关键剧情证据时，应该插入原片声画情景桥。
- 原片情景桥不是 2-3 秒碎片；单段目标 6-12 秒，由 LLM 基于 Source-ASR 判断 source_start_sec 和 duration，让它形成一个完整小对话或小情景。
- 插入点必须在 TTS 生成并完成 TTS-ASR 后，根据文案依据落到对应字幕 cue 后面，不能只按文案比例粗略估算。
- 只是泛泛提到原片、这一集、角色名、抽象观点或“看这里”，不触发原片情景桥。
- 检测到原片情景桥意图时，必须写入 `original_audio_insertions.json`，并实际混入最终音轨且替换对应时段画面；未插入则 QA 失败。

### 成片门

- 时长：目标区间 `120-180s`；超出区间记 warning，不得通过自动删改文案解决。
- 视频：`1920x1080`，`28fps` 或项目配置帧率。
- 音频：存在、可播放、音画同长。
- 编码：H.264/AAC MP4。
- 最终报告必须能追溯 TTS、TTS-ASR、Source-ASR、选段和包装证据。

## 阶段性里程碑

### M1：样片链路产品化

当前 `scripts/build_script_footage_remix_samples.py` 的能力迁移为可复用模块：

```text
src/roughcut/remix/script_topics.py
src/roughcut/remix/alignment.py
src/roughcut/remix/source_selection.py
src/roughcut/remix/scene_index.py
src/roughcut/remix/edit_plan.py
src/roughcut/remix/caption_packager.py
src/roughcut/remix/review_frames.py
src/roughcut/remix/batch_report.py
src/roughcut/remix/qa.py
```

收口：1 集 Bluey 可通过模块化 CLI 重建，产物和当前样片等价或更好。

### M2：证据链稳定

TTS-ASR、Source-ASR、topic plan、edit plan、qa report 都变成稳定 JSON 合同。

收口：任意失败都能定位到具体质量门，而不是只看到 mp4 缺失或渲染失败。

### M3：剪辑质量提升

引入镜头边界检测和主题级检索，减少固定时间点依赖。

收口：单集样片的选段来自 Source-ASR + 镜头边界联合评分，不再依赖手写锚点作为主路径。

### M4：字幕包装升级

字幕包装从脚本内 ASS 拼接升级成模板化配置。

收口：同一套 caption style 可复用于不同影视二创任务，支持重点字、主题条、贴纸、进出场动画。

### M5：可选批量压测

用户明确要求时，用不少于 10 集跑批量验证。

收口：10 集中至少 9 集自动通过硬质量门，失败集能给出明确失败质量门和可操作修复建议。该项不阻塞默认 1 集样片验收。

## 分阶段收口矩阵

| 阶段 | 必须证明 | 证据文件/命令 | 失败时处理 |
| --- | --- | --- | --- |
| M1 样片链路 | 正式 CLI 能重建 1 集样片 | `roughcut remix script-footage --episodes 1`；单集 `final.mp4` | 不能用手工拼接目录替代，先修 CLI 或脚本入口 |
| M2 证据链 | 每集有 TTS、TTS-ASR、Source-ASR、topic、edit、QA 合同 | 每集 JSON + `qa_report.json` | 缺任一关键合同，该集失败 |
| M3 选段质量 | 画面按主题级连续片段引用原片 | `topic_plan.json`、`source_asr_index.json`、`scene_index.json`、`edit_plan.json` | 如果只是均匀抽样或逐句跳切，不得收口 |
| M4 包装质量 | 字幕、主题条、关键词、重点字、水印可见 | `caption_package.json`、`subtitle.ass`、`review_frames/` | 包装计数不足或抽帧不可见，该集失败 |
| M5 可选批量稳定 | 显式压测时 10 集至少 9 集通过硬质量门 | `batch_report.json`、`batch_report.md`、`methodology_report.md` | 低于 90% 通过率，说明批量稳定性未收口，但不阻塞默认单集样片 |

## 硬阻断条件

出现以下任一情况，本轮不能声明完成：

- 任一最终样片没有使用 TTS 旁白，或旁白不是成片主体。
- TTS-ASR 未对最终 TTS 音频做字幕对齐，却生成了“已对齐”报告。
- Source-ASR 未生成或锚点不足，却继续声称画面是按剧情/主题定位。
- 原片右上角平台 logo 或底部原字幕仍作为显著画面元素保留，且没有裁切/放大/弱化证据。
- 成片分辨率低于 `1920x1080`，除非任务显式配置了其他交付规格。
- 成片存在超过 `0.60s` 的连续无声段，且未被气口门捕获。
- 字幕时间戳明显漂移，仍被 QA 判定为通过。
- 显式要求 10 集压测时没有完成批量验证。
- 报告只描述“残余风险”，没有给出对应质量门、证据文件和修复动作。

## 最终执行命令形态

最终验收必须能用正式 CLI 复现：

```powershell
$env:PYTHONPATH='src'
python -m roughcut.cli remix script-footage `
  --source-root "F:\布鲁伊育儿节目" `
  --episodes 1 `
  --output-dir output\bluey-remix-full-script-samples
```

可选 10 集压力测试命令：

```powershell
$env:PYTHONPATH='src'
python -m roughcut.cli remix script-footage `
  --source-root "F:\布鲁伊育儿节目" `
  --episodes 1,2,3,4,5,6,7,8,9,10 `
  --output-dir output\bluey-remix-full-script-batch-10
```

最终代码验证至少包含：

```powershell
$env:PYTHONPATH='src'
python -m pytest tests\test_remix_quality_contracts.py tests\test_remix_cli.py tests\test_scene_detection.py -q
```

## 最终收口条件

满足以下全部条件，才算这次链路优化完成：

1. 1 集 Bluey 样片可由正式 CLI 一键重建，不依赖手工操作。
2. 每集都生成完整必需产物：TTS、TTS-ASR、Source-ASR、topic plan、edit plan、subtitle、qa report、review frames、final mp4。
3. 单集成片通过硬质量门：完整文案进入 TTS、1920x1080、有音频、字幕来源为 Qwen3 TTS-ASR、Source-ASR 锚点充足；2-3 分钟只作为 warning 目标区间。
4. 选段策略是主题级连续片段，不是逐句跳切，也不是纯均匀抽样。
5. 原片 logo/底部字幕处理有可复核抽帧证据。
6. 字幕包装具备剪映式基础体验：底部字幕、重点字、主题条、关键词气泡/贴纸、水印和可听见的提示音 cue。
7. 失败处理可解释：任一失败必须落到具体质量门和证据文件。
8. 默认只要求 1 集完整样片报告；10 集批量验证报告为显式压测产物。
9. 文档包含方法论、命令、产物结构、质量门和人工复核流程。
10. 不再存在报告声称已完成但缺少 ASR/TTS/字幕/选段证据的情况。

## 完成判定

最终只能在以下结果同时成立时标记完成：

- `output/bluey-remix-full-script-samples` 中 1 集 `qa_report.json` 为 `pass` 或仅包含 duration warning。
- `output/bluey-remix-full-script-samples` 中 1 集 `final.mp4` 为 `1920x1080`、有音频、可播放；如超出 `120-180s`，报告必须标出 duration warning，但不得压缩文案。
- `output/bluey-remix-full-script-samples/batch_report.json` 中 `sample_count >= 1`、`pass_rate >= 0.90`、`qa_fail_count=0`、`required_evidence_failures=[]`、`gate_passed=true`。
- 每个通过集都有完整 per-episode 证据：TTS、TTS-ASR、Source-ASR、scene index、topic plan、edit plan、caption package、QA、review frames。
- `methodology_report.md` 说明双 ASR 职责、选段策略、包装策略、质量门和人工复核流程。
- 相关自动测试通过，且测试覆盖质量门退化场景：缺 ASR、缺包装、缺 review frames、显式压测样本数不足。

## 旧版压缩文案工程证据（不作为最终收口）

截至 2026-06-18，旧版 Bluey 验证集曾满足当时的完成判定；但旧版默认使用了文案压缩策略。该证据在“完整保留成稿文案”的新合同下只能作为工程链路参考，不能作为最终成片收口证据。

- 正式 10 集 CLI 已跑通：
  - `$env:PYTHONPATH='src'; python -m roughcut.cli remix script-footage --source-root "F:\布鲁伊育儿节目" --episodes 1,2,3,4,5,6,7,8,9,10 --output-dir output\bluey-remix-batch-10`
  - stdout：`sample_count=10`、`success_count=10`、`total_output_duration_sec=1286.443`。
- `output/bluey-remix-batch-10/batch_report.json`：
  - `sample_count=10`
  - `qa_pass_count=10`
  - `qa_warn_count=0`
  - `qa_fail_count=0`
  - `pass_rate=1.0`
  - `gate_passed=true`
  - `gate_reason=passed`
- 每集均保留完整证据文件：TTS 清理音频、TTS-ASR 对齐、Source-ASR 索引、scene index、topic plan、edit plan、caption package、QA、review frames、最终 mp4。
- E09/E10 的边界时长问题已修复并通过硬门：
  - S02E09：`120.5s`，TTS-ASR coverage `0.988`，Source-ASR anchors `14`，scene index `detected` / `69` scenes，packaging events `15`。
  - S02E10：`120.486s`，TTS-ASR coverage `0.9801`，Source-ASR anchors `14`，scene index `detected` / `93` scenes，packaging events `15`。
- 相关回归通过：
  - `python -m py_compile scripts\build_script_footage_remix_samples.py src\roughcut\api\tools.py src\roughcut\remix\scene_index.py src\roughcut\remix\caption_packager.py tests\test_remix_quality_contracts.py tests\test_tools_tts_text_resolution.py tests\test_remix_cli.py tests\test_scene_detection.py`
  - `$env:PYTHONPATH='src'; python -m pytest tests\test_remix_quality_contracts.py tests\test_remix_cli.py tests\test_tools_tts_text_resolution.py tests\test_scene_detection.py -q --basetemp .tmp\pytest-run`：`47 passed`。

## 不再继续打磨的边界

达到最终收口条件后，本轮优化结束。以下内容进入下一轮，不阻塞本轮收口：

- 逐字 karaoke 级字幕。
- 自动版权合规判断。
- 多平台封面和发布策略。
- 角色识别/视觉问答级剧情理解。
- 非 Bluey 数据集的大规模泛化评测。


