# 剪辑校对流程

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

本文是 RoughCut 当前实现对应的统一流程说明。目标不是描述理想状态，而是给出一条可以直接执行、可以验收、可以对齐代码和前端文案的主线。

## 总原则

1. 先冻结事实，再做剪辑，再做发布。
2. 人工关口只负责确认，不负责隐式改写下游事实。
3. 每个阶段只读自己应该消费的输入，不回头重新推翻前一阶段的已确认结果。
4. 任何会进入后续阶段的人工结果，都必须落成明确的最终 artifact。

## 统一主线

```text
probe → extract_audio → transcribe → subtitle_postprocess
      → glossary_review → subtitle_translation → content_profile
      → summary_review → ai_director → avatar_commentary
      → edit_plan → render → final_review → platform_package
```

说明：

- `subtitle_postprocess` 之后得到第一版可审校字幕。
- `glossary_review` 和 `content_profile` 负责把口播事实、术语纠错和主体判断收敛到可确认状态。
- `summary_review` 是摘要与主体的关键人工冻结点。
- `final_review` 是成片级人工冻结点。
- `platform_package` 只生成发布文案，不再反向影响视频主体与剪辑事实。

## 冻结规则

### 1. 原始素材冻结

输入视频、音频提取结果和探测结果一旦生成，不再被后续步骤改写。

- `probe` 产出媒体元数据。
- `extract_audio` 产出派生音频文件。
- 后续步骤只能读取这些派生结果，不能回写原始素材。

### 2. 字幕事实冻结

`subtitle_postprocess` 产出的字幕基线是后续所有审校、纠错和剪辑决策的共同起点。

- 术语纠错、摘要确认、剪辑计划都必须引用同一份字幕事实。
- 后续阶段可以派生新的展示版本，但不能悄悄修改已经冻结的基础字幕。

### 3. 内容画像冻结

`content_profile` 进入人工确认后，确认结果必须固化成 `content_profile_final`。

- 下游只读 `content_profile_final`。
- `draft`、临时推断、未确认摘要不允许再作为下游依据。
- 人工确认的结果要同时成为后续 `edit_plan`、`render` 和 `platform_package` 的输入。

### 4. 成片冻结

`render` 产出成片后，`final_review` 只负责判定通过或退回，不负责继续重算前面的事实。

- 通过后，成片进入发布候选态。
- `platform_package` 只能基于已通过的成片生成平台文案和发布素材。

## 阶段说明

| 阶段 | 主要输入 | 主要输出 | 责任边界 | 是否人工关口 |
|---|---|---|---|---|
| `probe` | 原始视频 | 分辨率、时长、流信息、旋转信息 | 只负责识别媒体属性 | 否 |
| `extract_audio` | 原始视频、探测结果 | 音频文件 | 只负责抽取音轨 | 否 |
| `transcribe` | 音频文件 | 原始转写、词级时间戳、分段结果 | 只负责语音识别 | 否 |
| `subtitle_postprocess` | 转写结果 | 首版字幕、基础断句、标准化文本 | 只做基础字幕构造 | 否 |
| `glossary_review` | 首版字幕、术语表、记忆库 | 术语纠错结果、纠错理由、待确认问题 | 只处理术语和明显事实冲突 | 视阈值而定 |
| `subtitle_translation` | 冻结后的字幕事实 | 翻译字幕或双语字幕 | 只负责翻译派生，不改字幕事实 | 否 |
| `content_profile` | 字幕事实、术语纠错结果、上下文证据 | 内容画像草稿、主体判断、风险信号 | 只负责主体与摘要层判断 | 视阈值而定 |
| `summary_review` | `content_profile` 草稿 | `content_profile_final` | 人工确认摘要、主体、风险判断 | 是 |
| `ai_director` | `content_profile_final`、媒体元数据 | 剪辑意图、镜头策略、节奏建议 | 只根据确认后的画像做导演层决策 | 否 |
| `avatar_commentary` | `ai_director` 输出、成片策略 | 数字人口播/旁白相关产物 | 只负责 avatar 分支资产 | 否 |
| `edit_plan` | 冻结字幕事实、`content_profile_final`、媒体元数据 | 剪辑决策、时间线、渲染计划 | 只生成剪辑与渲染计划，不回写字幕事实 | 否 |
| `render` | 剪辑计划、视频/音频/字幕资产 | 成片、字幕文件、封面、调试产物 | 只负责物理渲染 | 否 |
| `final_review` | 成片、字幕、封面、调试产物 | 通过 / 退回 | 只做成片级验收，不改前序事实 | 是 |
| `platform_package` | 已通过成片、确认后的内容画像 | 标题、简介、标签、发布包 | 只生成平台发布材料 | 否 |

## 人工关口

### `summary_review`

这是最重要的冻结点。

人工只确认以下内容：

- 这条任务的主体是谁。
- 内容画像是否正确。
- 纠错和摘要是否可以作为后续剪辑依据。

确认后的结果必须进入 `content_profile_final`，供后续阶段统一读取。

### `final_review`

这是成片验收关口。

人工只判断：

- 成片是否可以交付。
- 剪辑是否存在明显错误。
- 字幕、封面、封装结果是否满足发布要求。

这里不再回头重算摘要、主体或者术语归属。

## 输入输出约束

### `probe`

- 输入：原始视频
- 输出：媒体元数据、流信息、旋转/比例线索

### `extract_audio`

- 输入：原始视频、`probe` 结果
- 输出：可被转写使用的音频文件

### `transcribe`

- 输入：音频文件
- 输出：带时间戳的原始转写

### `subtitle_postprocess`

- 输入：原始转写
- 输出：首版字幕

### `glossary_review`

- 输入：首版字幕、术语表、记忆、上下文
- 输出：纠错后的字幕、纠错理由、是否需要人工确认

### `subtitle_translation`

- 输入：冻结后的字幕事实
- 输出：翻译字幕或双语字幕

### `content_profile`

- 输入：字幕事实、纠错结果、上下文证据
- 输出：内容画像草稿、主体判断、摘要候选

### `summary_review`

- 输入：内容画像草稿
- 输出：确认后的 `content_profile_final`

### `ai_director`

- 输入：`content_profile_final`
- 输出：剪辑策略、节奏策略、导演建议

### `avatar_commentary`

- 输入：导演策略、头像/人声相关配置
- 输出：avatar 分支素材

### `edit_plan`

- 输入：冻结字幕事实、`content_profile_final`、媒体元数据
- 输出：剪辑时间线、段落选择、渲染指令

### `render`

- 输入：渲染指令、媒体与字幕资产
- 输出：成片、字幕文件、封面、调试记录

### `final_review`

- 输入：成片、字幕、封面、调试记录
- 输出：通过或退回

### `platform_package`

- 输入：已通过成片、确认后的内容画像
- 输出：平台标题、简介、标签、发布包

## 执行准则

- 只有 `summary_review` 和 `final_review` 是强人工关口。
- 其它阶段即使触发 review，也只是在当前阶段内做收敛，不允许跨阶段改写已冻结事实。
- 任何“临时修正”都必须归属到明确 artifact，不能藏在流程副作用里。
- 如果某阶段产物会影响后续阶段，就必须先写入最终版，再推进下一阶段。

## API 对齐

前后端通信也按这套关口收口，不再让前端自己猜。

- `JobOut.review_step` 只会返回 `summary_review` / `final_review` / `null`。
- `JobOut.review_detail` 返回当前人工关口的统一等待文案。
- `JobActivityOut.review_step` 与 `JobActivityOut.review_detail` 复用同一套判断。
- `JobActivityOut.decisions[*].step_name` 与 `events[*].step_name` 直接标明归属步骤，详情面板按结构归组，不再从中文标题反推阶段。
- `JobActivityOut.current_step.detail` 对 `summary_review`、`final_review`、`platform_package` 使用固定文案，不再依赖零散 metadata 拼接。

## 读者使用方式

- 排查任务卡住时，先看当前 job 停在哪个阶段。
- 找流程歧义时，先看本文件的冻结规则，再看对应阶段的输入输出。
- 如果代码和文档不一致，以状态机和最终 artifact 为准，再同步修正文档。
