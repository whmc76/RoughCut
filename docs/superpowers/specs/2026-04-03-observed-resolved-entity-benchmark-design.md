# Observed/Resolved Entity Benchmark Design

## Goal

把当前内容理解链升级成通用的双层实体框架，并且用一组固定的小样商品视频 benchmark 约束后续优化，避免围绕单条视频做特化。

## Constraints

- 最终 `subject_type / video_theme / summary / search_queries / primary_subject` 只能由 LLM 产出。
- 规则层只能提供 evidence、normalization、retrieval input、conflict detection，不能手写最终主题。
- 联网搜索和数据库检索只作为弱佐证，但允许 LLM 在证据充分时把 `observed` 消歧到更准确的 `resolved`。
- 如果 `observed` 和 `resolved` 不一致，系统必须保留映射关系和证据链，不能静默覆盖。

## Current Problem

现有 `content_understanding` 只有一层 `subject_entities / primary_subject`。

这会导致两个问题：

1. 视频里原始称呼和检索归一化实体混在一起，审核时看不出模型到底“听到了什么”。
2. 对比测试容易被单条视频带偏，无法判断本次升级是在提升通用理解，还是只修了某个案例。

## Proposed Design

### 1. Dual-Layer Entity Model

在 `content_understanding` 里新增两层实体：

- `observed_entities`
  直接来自视频证据的原始实体候选。
- `resolved_entities`
  由 LLM 结合混合检索后输出的归一化实体。

同时新增：

- `entity_resolution_map`
  每个 `observed` 映射到哪个 `resolved`，以及原因和证据。
- `resolved_primary_subject`
  如果检索消歧后有更精确主体，作为最终主题的优先来源。
- `resolution_conflicts`
  当视频原始称呼和检索归一化不一致时，记录冲突点。

### 2. Multi-Stage Understanding Flow

#### Stage A: Observed Fact Extraction

输入：字幕、ASR、OCR、画面、文件名、已有 hints。

输出：

- `observed_entities`
- `observed_aliases`
- `observed_product_names`
- `observed_relations`
- `phonetic_candidates`
- `search_expansions`

要求：

- 保留视频原始叫法，哪怕可能是别名、近音词、错字。
- 不在这个阶段做最终归一化。

#### Stage B: Hybrid Resolution

输入：`observed` 候选和扩展检索词。

检索来源：

- 在线搜索结果
- 内部已确认实体库

输出：

- `resolved_entities`
- `entity_resolution_map`
- `resolved_primary_subject`
- `resolution_conflicts`
- `resolution_evidence`

要求：

- 当检索强支持某个归一化实体时，允许把 `船长 -> BOLTBOAT`、`音近产品名 -> 正确产品名` 这类关系写入 `resolved`。
- 当检索不足时，保持 `resolved` 空或接近 `observed`，并 `needs_review=true`。

#### Stage C: Final Understanding

最终字段读取顺序：

1. 优先 `resolved_primary_subject / resolved_entities`
2. 若 `resolved` 弱，则回落到 `observed`
3. 任何冲突都写入 `uncertainties / review_reasons`

Legacy 兼容层继续输出：

- `subject_brand`
- `subject_model`
- `subject_type`
- `video_theme`
- `summary`

但默认来自 `resolved` 层，不再直接来自 `observed`。

### 3. Benchmark-First Validation

建立固定商品小样 benchmark，不允许只看单条视频。

首批基准样本来自 `Y:\EDC系列\未剪辑视频`，先选 5 到 6 条代表性商品：

- `IMG_0041.MOV`
  机能双肩包联名开箱
- `20260209-124735.mp4`
  Olight 便携设备 / 手电类
- `20260211-123939.mp4`
  美工刀/折叠刀类
- `20260212-141536.mp4`
  折刀/挂扣工具类
- `20260211-120605.mp4`
  防水盒/收纳盒类
- `20260213-133009.mp4`
  EDC 配件/材料类

### 4. Benchmark Output Contract

每条 benchmark 样本至少产出：

- `source_name`
- `expected_product_family`
- `observed_entities`
- `resolved_entities`
- `resolved_primary_subject`
- `video_theme`
- `needs_review`
- `review_reasons`

回归时重点看：

- 是否从错误具体品类回退到中性或正确品类
- 是否能从脏 ASR 提取有效 `observed`
- 是否能在证据足够时将 `observed` 消歧为更准 `resolved`
- 是否在证据不足时保持待审，而不是擅自改判

## Files To Change

- `src/roughcut/review/content_understanding_schema.py`
  扩 schema 与 legacy mapping。
- `src/roughcut/review/content_understanding_infer.py`
  增加 observed 层输出。
- `src/roughcut/review/content_understanding_verify.py`
  增加 resolved 层和 resolution map。
- `src/roughcut/review/content_profile.py`
  调整最终映射优先级和 cache version。
- `tests/test_content_understanding_infer.py`
- `tests/test_content_understanding_verify.py`
- `tests/test_content_profile.py`
- `tests/test_pipeline_steps.py`
- `tests/` 下新增 benchmark 测试文件

## Risks

- 检索结果可能把 `resolved` 过度外推，所以必须保留 `observed -> resolved` 映射和 review reasons。
- benchmark 如果只覆盖 EDC 子类，仍可能带偏，所以测试重点应是“消歧能力”和“保守边界”，不是只看某个品牌。
- 如果 cache version 不升级，自动链可能继续命中旧结果，导致 live 误判修复无效。
