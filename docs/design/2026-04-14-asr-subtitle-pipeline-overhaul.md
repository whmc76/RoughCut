# ASR 与字幕流水线整体重构方案

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 结论摘要

当前 RoughCut 在“原始内容识别 -> 字幕构造 -> 内容理解 -> 剪辑删减 -> 多版本导出”这条主链路上存在系统性设计错误，不是继续补规则可以解决的问题。

最关键的判断有四条：

1. 当前系统缺的不是“更强的字幕断句补丁”，而是“把原始 ASR 证据作为第一事实层”。
2. 当前 `素板.srt` 不是原片字幕，而是 `edit_plan` 之后 remap 的剪后字幕，名称和实际语义严重不符。
3. 当前 `content_profile`、`glossary_review`、`edit_plan` 等下游阶段仍然主要消费 `subtitle_items`，而不是消费原始 transcript 证据，导致错误被层层放大。
4. 当前 `edit_plan` 会基于已经失真的字幕文本做 `low_signal_subtitle / filler_word / restart_retake` 删减决策，这会直接造成“重要信息被删、口误被保留”。

结论上，当前问题不应再被定义为“字幕截断问题”，而应定义为：

- `ASR 证据层失真`
- `字幕结构层失真`
- `内容理解层证据倒置`
- `剪辑层删减依据失真`
- `导出层命名和版本语义错误`

本方案默认**不考虑兼容旧模型和旧产物语义**，目标是按最优逻辑整体重构。

## 本次排查证据

### 产物层证据

对 `Y:\EDC系列\AI粗剪` 的已产出项目做了全量读取：

- 总目录数：`31`
- 实际产出 `素板.srt` 的目录：`14`
- 已读取 `素板.srt`：`14` 份
- 总字幕条数：`3337`

已确认现象：

- `8/14` 份 `素板.srt` 存在时间乱序或重叠。
- 疑似短语/组合词/句子截断条目至少 `668/3337`，约 `20%`。
- 错词、错品牌、重复词、口误保留广泛存在。
- 大量问题会直接继承到 `成片 / AI特效版 / 数字人版`。

### 数据库层证据

当前 PostgreSQL 中与这批任务对应的数据：

- `jobs`: `13`
- `transcript_segments`: `3912`
- `subtitle_items`: `3457`
- `artifacts`: `224`
- `transcript_evidence`: `13`

关键观察：

1. `transcript_segments` 的时间范围基本覆盖源视频全长。
   这说明当前代码路径不是“先剪再 ASR”，而是“原片提音频 -> 原片 ASR”。

2. `transcript_chars -> subtitle_chars` 的保留率接近 `1.0`。
   这说明 `subtitle_postprocess` 主要是在错误文本上重切分和轻微纠错，不是大规模删字。

3. 当前库里已经有 `transcript_evidence`，包含：
   - `provider`
   - `model`
   - `prompt`
   - `raw_payload`
   - `raw_segments`
   - `segments`
   - 词级 `words`

这意味着系统其实已经具备“以原始 ASR 为主证据”的基础数据条件，只是没有把它放到主链路中心。

### 代码层证据

#### 1. ASR 发生在原片音频上

`src/roughcut/pipeline/steps.py`

- `run_extract_audio()` 调用 `_resolve_source(job, tmpdir)`，从 `job.source_path` 直接提取音频。
- `run_transcribe()` 只消费 `audio_wav` artifact。
- `src/roughcut/media/audio.py` 的 `extract_audio()` 直接对原视频跑 ffmpeg 提音频。

所以当前并不存在“`edit_plan` 先裁内容，再把裁后的音频拿去 ASR”的路径。

#### 2. 内容理解仍以字幕摘要为主，不以 transcript 为主

`src/roughcut/review/content_profile.py`

- `infer_content_profile()` 的入口参数是 `subtitle_items`
- `transcript_excerpt = build_transcript_excerpt(subtitle_items)`

也就是说，所谓 `transcript_excerpt` 实际是从 `subtitle_items` 里截出来的摘要，而不是从原始 `transcript_segments` / `transcript_evidence.raw_segments` 里构建的。

这是当前最根本的证据倒置问题。

#### 3. 剪辑删减依赖字幕文本，而不是原始 transcript 事实

`src/roughcut/edit/decisions.py`

`build_edit_decision()` 会基于 `subtitle_items` 构造切点，包含：

- `silence`
- `filler_word`
- `low_signal_subtitle`
- `restart_retake`

这意味着如果字幕文本本身已经被 ASR 错识、断裂、口误污染，那么剪辑删减逻辑会直接基于坏证据删内容。

这正对应用户反馈：

- 重要信息被删
- 口误被保留

#### 4. `素板.srt` 不是“原片字幕”，而是剪后字幕

`src/roughcut/pipeline/steps.py`

在 `run_render()` 中：

- `keep_segments = editorial_timeline.keep segments`
- `remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)`
- `write_srt_file(remapped_subtitles, local_plain_srt)`

这里的 `local_plain_srt` 最终被命名为 `素板.srt`。

也就是说：

- 当前 `素板.srt` 实际上是**经过剪辑时间线 remap 的剪后字幕**
- 它不是“原片 ASR 字幕”
- 也不是“字幕后处理基线”

这个命名本身会误导所有后续分析、人工审校和用户认知。

#### 5. 导出 SRT 不做时间排序校验

`src/roughcut/media/output.py`

- `write_srt_file()` 直接按传入列表顺序写出
- 不按 `start_time` 排序
- 不校验时间单调递增
- 不校验重叠

同时系统中多个消费点用 `.order_by(SubtitleItem.item_index)` 而不是按时间排序读取。

这就是当前乱序 `SRT` 能落盘成功的直接原因。

## 当前系统的核心问题分类

## 1. 事实层问题

### 1.1 原始 ASR 不是主事实层

症状：

- 下游大量逻辑消费 `subtitle_items`
- `content_profile` 的 transcript excerpt 实际来自 subtitle
- review 看到的是切坏后的文本，不是原始证据

后果：

- 一旦字幕层失真，所有理解、纠错、删减都会同时失真

### 1.2 没有明确区分原始 transcript、修订 transcript、展示 subtitle

当前只存在：

- `TranscriptSegment`
- `SubtitleItem`

缺失：

- 原始 ASR 尝试记录
- 选定的 ASR 基线版本
- 人工/规则修订后的 transcript 版本
- 语义单元
- 展示单元

后果：

- 一个层级的错误会覆盖另一个层级的事实
- 无法回答“到底是 ASR 错了，还是字幕切坏了”

## 2. 字幕结构层问题

### 2.1 语义单元和展示单元混在一起

当前 `SubtitleItem` 同时承担：

- 语义切句
- 展示切条
- 文本纠错后的展示文本

后果：

- 横版、竖版、封装版都只能共用一层脆弱结构
- 不能在不破坏语义的前提下做不同展示投影

### 2.2 字幕切分发生在错误文本之上

如果 ASR 已经误识：

- 品牌错
- 型号错
- 组合词拆裂
- 句法不完整

那后续切分只会继续放大错误。

### 2.3 导出层缺少硬校验

当前允许这些错误直接落盘：

- 时间乱序
- 重叠
- 组合词断开
- 连续残句
- 未闭合句尾被补句号

## 3. 内容理解层问题

### 3.1 证据顺序反了

理想顺序应当是：

- 原始 transcript
- transcript 修订
- OCR / source_name / research 补充
- subtitle 仅作为展示侧证据

当前更接近：

- subtitle excerpt
- subtitle signal blob
- OCR / search

这会导致：

- 已切坏的字幕被当作摘要依据
- 主体识别和视频主题判断被污染

### 3.2 glossary_review 放得太晚、职责太弱

当前术语纠错更多是在字幕层做“局部文本修正”，没有在 transcript 层先把专名拉回正轨。

后果：

- 错品牌、错型号进入 content_profile
- 再反向影响剪辑和包装

## 4. 剪辑层问题

### 4.1 编辑决策基于坏字幕做删减

当前 `edit_plan` 的删减依据中，最危险的是：

- `low_signal_subtitle`
- `filler_word`
- `restart_retake`

这些判断本来就应该建立在**可靠 transcript** 或**音频语义证据**上，而不是建立在已经切坏的 subtitle 上。

### 4.2 “素板”语义错误

用户会自然认为：

- `素板.mp4 / 素板.srt` = 原片或仅加基础字幕的版本

但当前系统实际行为是：

- `素板.mp4` 是 plain render 结果
- `素板.srt` 是 remap 到 keep timeline 的剪后字幕

命名和行为不一致会直接干扰生产判断。

## 5. 版本与产物层问题

### 5.1 artifact 过度依赖 JSON blob

当前大量关键信息塞在 `artifacts.data_json` 中，例如：

- transcript evidence
- content profile
- downstream context
- variant timeline bundle

后果：

- 难以做结构约束和查询
- 难以建立版本关系
- 难以明确“哪个阶段消费哪个版本”

### 5.2 多版本渲染是在继承坏基线

`素板 / 成片 / AI特效版 / 数字人版` 多数是在共享同一批坏字幕或其 remap 结果。

所以：

- 问题不会在下游自然消失
- 只会连带污染所有版本

## 根因链路

当前主链路可以概括成：

`原片音频 -> ASR -> 坏 transcript -> 坏 subtitle -> 坏 content_profile -> 坏 edit_plan -> 错删内容 -> 多版本继承`

其中最根本的设计错误是：

1. 没有把原始 ASR 证据固定为主事实层
2. 没有把 transcript / semantic unit / display subtitle 分层
3. 没有让剪辑只消费修订后的 transcript 事实
4. 没有对导出产物设置结构硬门禁

## 重构目标

## 总目标

建立一条以**原始 ASR 证据为核心**、分层清晰、可审可追溯、能阻断坏产物落盘的主链路。

### 顶层原则

1. 原始证据不可被覆盖
2. transcript 是事实层，subtitle 是展示层
3. 剪辑只能消费修订后的 transcript 事实，不能直接消费脆弱 subtitle
4. 任一版本的字幕导出都必须通过结构校验，否则失败
5. “版本名”必须和“实际含义”一致

## 不考虑兼容的目标架构

建议直接重建为下面的阶段：

```text
ingest_media
-> extract_audio
-> asr_capture
-> asr_selection
-> transcript_reconstruction
-> transcript_review
-> semantic_segmentation
-> subtitle_projection
-> subtitle_polish
-> understanding
-> editorial_plan
-> render_variants
-> final_review
-> packaging
```

## 新阶段职责

### 1. `ingest_media`

输入：

- 原始视频

输出：

- source media record
- probe metadata
- source hash

约束：

- 永不改写

### 2. `extract_audio`

输入：

- source media

输出：

- 原始音轨派生文件

### 3. `asr_capture`

输入：

- 原始音轨

输出：

- 一个或多个 `ASRAttempt`

每个 attempt 必须保存：

- provider
- model
- prompt
- raw payload
- utterances
- words/tokens
- confidence / logprob

这里不做任何术语纠错，不做展示切分。

### 4. `asr_selection`

输入：

- 多个 ASR attempt

输出：

- `ASRBaseline`

职责：

- 选择主 ASR 结果
- 或对多路 ASR 做局部择优融合

### 5. `transcript_reconstruction`

输入：

- `ASRBaseline`

输出：

- 原始 transcript utterances
- token stream

职责：

- 统一词流
- 建立 utterance 和 word 级时间轴
- 保留所有原始证据映射

### 6. `transcript_review`

输入：

- 原始 transcript
- glossary
- review memory
- OCR
- source_name

输出：

- `ReviewedTranscript`

职责：

- 修正品牌、型号、专有名词
- 修正显性 ASR 错词
- 标注不确定片段

约束：

- 不能删减事实
- 不能进行展示级切条

### 7. `semantic_segmentation`

输入：

- `ReviewedTranscript`

输出：

- `SemanticUnit`

职责：

- 只做语义切分
- 保证组合词、短语、句子完整性

### 8. `subtitle_projection`

输入：

- `SemanticUnit`
- variant display profile

输出：

- `DisplaySubtitle`

职责：

- 根据横版/竖版/封装版做展示投影
- 允许不同版本有不同显示切条
- 禁止破坏语义单元

### 9. `subtitle_polish`

输入：

- `DisplaySubtitle`

输出：

- polished display subtitle

职责：

- 只做展示文本修饰
- 不改语义边界
- 不补事实

### 10. `understanding`

输入：

- `ReviewedTranscript`
- transcript evidence
- OCR
- research
- source_name

输出：

- `ContentUnderstanding`
- `ContentProfileFinal`

职责：

- 主体识别
- 主题识别
- 风险判断
- 摘要生成

约束：

- 默认不读取 display subtitle
- subtitle 只作为辅助展示引用，不作为主证据

### 11. `editorial_plan`

输入：

- `ReviewedTranscript`
- `ContentProfileFinal`
- silence / scene / visual evidence

输出：

- `EditorialDecision`

职责：

- 删减依据必须建立在 reviewed transcript 上
- 可删除 filler / retake / invalid gap
- 但不能再直接使用脆弱 subtitle 做低信号判断

### 12. `render_variants`

输入：

- editorial decision
- variant subtitle projections

输出：

- raw review cut
- clean cut
- packaged cut
- ai effect cut
- avatar cut

这里必须重命名版本：

- `原片字幕基线`
- `剪后净版`
- `包装成片`
- `AI特效版`
- `数字人版`

禁止继续使用当前这种会误导人的 `素板` 命名。

## 新数据模型

建议直接废弃当前“`TranscriptSegment + SubtitleItem + 大量 artifact JSON`”的中心设计，改成显式结构。

## 核心实体

### `SourceMedia`

- id
- source_path
- source_hash
- probe metadata

### `AudioDerivative`

- id
- source_media_id
- audio_path
- sample_rate

### `ASRAttempt`

- id
- source_media_id
- provider
- model
- prompt
- raw_payload
- status

### `ASRUtterance`

- id
- asr_attempt_id
- utterance_index
- start_time
- end_time
- text_raw
- confidence

### `ASRToken`

- id
- asr_utterance_id
- token_index
- text_raw
- start_time
- end_time
- confidence

### `ASRBaseline`

- id
- source_media_id
- selected_attempt_id
- selection_reason

### `ReviewedTranscriptVersion`

- id
- source_media_id
- based_on_baseline_id
- status

### `ReviewedUtterance`

- id
- transcript_version_id
- utterance_index
- start_time
- end_time
- text_reviewed
- correction_labels
- unresolved_flags

### `SemanticUnit`

- id
- transcript_version_id
- unit_index
- start_time
- end_time
- text
- closure_state

### `SubtitleProjection`

- id
- semantic_version_id
- variant_name
- display_profile

### `DisplaySubtitle`

- id
- projection_id
- item_index
- start_time
- end_time
- text_display

### `EditorialDecision`

- id
- transcript_version_id
- content_profile_id
- cut_reason_graph

### `RenderVariant`

- id
- editorial_decision_id
- variant_name
- media_path
- srt_path
- validation_status

## 关键设计变化

### 1. transcript 和 subtitle 彻底分家

旧逻辑：

- transcript 很快退场
- subtitle 成为事实代理

新逻辑：

- transcript 是唯一事实层
- subtitle 只是事实投影

### 2. content_profile 只读 reviewed transcript

`infer_content_profile()` 必须改成：

- 主输入：`ReviewedTranscript`
- 辅助输入：OCR / research / source_name / image evidence
- subtitle 默认不参与主体推断

### 3. edit_plan 不再读 `SubtitleItem`

剪辑分析所需的文本输入必须来自：

- `ReviewedTranscript`
- `SemanticUnit`

如果某个删减规则必须感知展示节奏，也只能读 `SemanticUnit`，不能直接读 display subtitle。

### 4. 每个 render variant 用独立 subtitle projection

当前多个版本共享一套坏字幕。

新逻辑必须是：

- `净版字幕`
- `包装版字幕`
- `数字人版字幕`
- `AI特效版字幕`

每个版本都有明确 projection lineage。

### 5. 结构校验前移为强门禁

任何 `DisplaySubtitle` 导出前都必须通过：

- 时间单调递增
- 无重叠
- 语义完整度阈值
- 组合词切裂阈值
- 残句比例阈值

失败则：

- 阻断 render variant
- 标记为 review required

## 需要直接移除的旧设计

以下设计建议直接删除，不保兼容：

1. 把 `subtitle_items` 当 transcript excerpt 来源的逻辑
2. `素板` 这一命名
3. `edit_plan` 基于 `low_signal_subtitle` 直接切内容的逻辑
4. `write_srt_file()` 无排序无校验直接落盘
5. 让 `polish_subtitle_items()` 承担结构补锅职责
6. 继续依赖 artifact JSON 作为核心结构模型

## 重构后的质量门禁

## 阶段门禁

### `asr_capture` 后

- 必须有完整 `raw_segments`
- 必须有词级或 token 级时间信息
- 必须记录 provider / model / prompt

### `transcript_review` 后

- 必须输出 unresolved spans
- 必须可追溯到原始 ASR token

### `semantic_segmentation` 后

- 组合词拆裂率必须低于阈值
- 残句率必须低于阈值

### `subtitle_projection` 后

- 展示时长、阅读速度、闭合状态必须合格

### `render_variants` 前

- 每个 variant 的字幕单独验证
- 任一字幕失败，不得导出正式版本

## 实施顺序

建议按下面顺序重构，且每一步都允许直接替换旧逻辑：

### Phase 1：证据层重建

- 引入 `ASRAttempt / ASRBaseline / ReviewedTranscriptVersion`
- 让 transcript_evidence 成为第一事实层
- 停止让 content_profile 以 subtitle 为主输入

### Phase 2：字幕分层

- 引入 `SemanticUnit / DisplaySubtitle`
- 把 transcript -> semantic -> display 三层分开

### Phase 3：剪辑层重建

- 让 edit_plan 改为消费 reviewed transcript
- 删除对 `low_signal_subtitle` 的核心依赖

### Phase 4：导出层重建

- variant 独立 subtitle projection
- 导出强校验
- 重命名所有版本

### Phase 5：评审界面重建

- summary review 默认展示 transcript evidence
- final review 展示 variant subtitle validation

## 验收标准

重构完成后，必须满足：

1. 任意任务都能回溯：
   - 原片
   - 原始 ASR
   - 修订 transcript
   - semantic units
   - variant subtitles
   - render outputs

2. `content_profile` 的主证据不再来自 subtitle excerpt。

3. `素板` 这类错误命名被移除，所有版本名与行为一致。

4. `SRT` 导出不允许出现乱序和重叠。

5. 剪辑删减不再因为坏字幕文本误删关键信息。

6. 用户可以明确区分：
   - 原始识别错
   - transcript 修订错
   - 字幕投影错
   - 剪辑删减错

## 推荐的第一批落地动作

如果只做最有价值的第一批改造，建议立刻执行：

1. 新建 transcript-first 数据模型，不再把 subtitle 当事实层。
2. 重写 `infer_content_profile()`，主输入切到 `ReviewedTranscript`。
3. 重写 render 导出，`SRT` 必须按时间排序并做硬校验。
4. 把当前 `素板.srt` 改名并拆成：
   - `原始字幕基线`
   - `剪后净版字幕`
5. 重写 edit_plan 的文本输入，禁止直接基于 display subtitle 判低信号删减。

这五步做完，系统的核心误伤会先降一个数量级，后续再做更细的字幕断句和多路 ASR 选择才有意义。
