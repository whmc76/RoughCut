# RoughCut Content Profile Correction Refactor Design

## Goal

重构 RoughCut 的内容识别与矫正链路，让自动识别继续作为默认流程，但最终识别结果只能建立在当前视频证据之上。历史测试词、跨视频记忆、领域词包和模板提示不得再直接改写当前任务的主体品牌、型号、类型和主题。

## Problem Statement

当前 `content_profile` 链路把四类能力耦合在了一起：

1. 当前视频证据识别
2. 历史人工修正记忆
3. 领域词表与别名归一化
4. 工作流模板与主题兜底

这导致系统表现为“自动识别覆盖率高”，但本质上存在跨视频污染风险：

- 历史测试词可能进入生产主体推断
- 词表既做纠错又做主体生成
- 工作流模板和领域包会隐式注入具体候选
- 识别失败时系统倾向于“猜一个像的”，而不是保守留空

结果是单条视频的真实内容，可能被旧测试样例、别名库或历史记忆篡改。

## Product Decision

本次重构遵循以下产品约束：

- 自动识别流程保留，并继续作为主路径
- 当当前视频证据不足时，系统必须保守留空并进入待审
- 历史记忆、词表和模板只能辅助规范化与审核提示，不能跨视频生成主体
- 自动识别成功不等于自动确认成功

## Design Principles

### 1. Current-Video Evidence Only

只有当前任务的字幕、抽帧、当前文件名、当前画面 OCR 才能创建主体候选。

### 2. Normalization Is Not Inference

别名纠错只允许对当前视频中已经命中的 token 做归一化，不允许凭词表直接创造品牌、型号或主题。

### 3. Memory Can Assist Review, Not Identity Creation

历史记忆只能在当前视频已出现相同 token 时帮助选规范写法，或作为审核提示展示，不能创建新的主体字段。

### 4. Conservative Failure Mode

当证据冲突、证据不足或只能靠历史记忆支撑时，系统必须输出空值并要求人工确认，而不是继续猜测。

### 5. One Responsibility Per Stage

证据采集、候选提取、打分、决策、增强、审核门控必须拆分为独立阶段，禁止跨阶段回写主体身份。

## New Pipeline

### Stage 1: Evidence Collection

输入：

- 当前 job 字幕
- 当前 job 抽帧
- 当前 job 文件名
- 当前 job OCR / visible text

输出：

- `EvidenceBundle`

职责：

- 收集原始证据
- 统一清洗与标准化
- 保留来源信息与定位信息
- 不生成任何主体结论

### Stage 2: Candidate Extraction

从 `EvidenceBundle` 提取候选：

- `brand_candidates`
- `model_candidates`
- `subject_type_candidates`
- `theme_candidates`

职责：

- 只从当前证据中提取候选
- 可以使用 normalization glossary 做命中后归一化
- 不读取历史记忆生成新候选
- 不根据模板或领域直接注入候选

### Stage 3: Candidate Scoring

对候选进行证据评分，核心维度：

- 字幕命中强度
- 视觉命中强度
- OCR / visible text 命中强度
- 文件名命中强度
- 多来源一致性
- 是否仅由单一弱证据支撑
- 是否与其他候选冲突

硬规则：

- 只有历史记忆支持的候选分数直接为 0
- 只靠领域包、模板或全局映射得到的候选分数直接为 0
- 来源冲突时不做补猜，只做降级

### Stage 4: Profile Resolution

从打分结果中生成最终主体字段：

- `subject_brand`
- `subject_model`
- `subject_type`
- `video_theme`

职责：

- 仅从当前证据评分结果中选定最终值
- 品牌、型号、类型之间若存在冲突，直接留空
- 不能从摘要、搜索词、模板或历史记忆逆向改写主体

### Stage 5: Profile Enrichment

只有主体身份稳定后，才允许生成：

- `summary`
- `hook_line`
- `engagement_question`
- `search_queries`
- `cover_title`

约束：

- enrichment 只能消费已定主体
- enrichment 不能回写 `subject_brand / subject_model / subject_type / video_theme`
- 若主体为空，增强结果必须使用保守模板，避免伪具体化

### Stage 6: Review Gate

将“识别成功”和“自动确认成功”明确分离。

规则：

- 识别出候选但证据不足：进入待审
- 主体字段为空但摘要可生成：仍进入待审
- 只有当主体字段由多源当前证据支撑且无冲突时，才允许进入自动确认评估

## Information Authority Model

为避免跨视频污染，信息源分为四层，权限递减：

### Level A: Current Video Strong Evidence

来源：

- 当前字幕
- 当前抽帧视觉
- 当前 OCR / visible text
- 当前文件名

权限：

- 可以创建主体候选
- 可以参与最终身份判定

### Level B: Current Video Weak Evidence

来源：

- 当前工作流模板
- 当前任务领域
- 当前任务已有草稿

权限：

- 只能帮助排序、决定保守与否
- 不能创建具体品牌型号

### Level C: Correction Knowledge

来源：

- normalization glossary
- ASR 常见错写别名

权限：

- 只能在当前 token 已命中时做规范化
- 不能直接创建主体字段

### Level D: Historical Memory

来源：

- recent corrections
- field preferences
- phrase preferences
- keyword preferences

权限：

- 只能在当前视频已有 token 命中时辅助选规范写法
- 或生成 review hints
- 不能参与主体创建、主题创建、搜索词创建、模板选择

## Correction Logic Refactor

### Normalization Glossary

保留用途：

- 当前证据 token 命中后的规范化
- 当前字幕与 OCR 的别名统一

移除用途：

- 直接生成主体品牌
- 直接生成主体型号
- 通过领域包注入具体视频主题

### Review Glossary

单独服务于：

- 人工审核提示
- 字幕纠错建议
- 审核页解释信息

禁止：

- 参与主体创建与评分

### Historical Memory

重构后仅允许：

- 当前 token 已出现时帮助选 canonical form
- 为审核页提供“你以前改过什么”的提示

明确禁止：

- 生成 `subject_brand`
- 生成 `subject_model`
- 生成 `subject_type`
- 生成 `video_theme`
- 生成 `search_queries`
- 影响 `workflow_template`

## Template and Domain Behavior

`workflow_template`、`subject_domain` 和 domain detection 以后只能决定：

- 使用哪套提示词
- 采用哪种摘要风格
- 是否更保守待审

不得再决定：

- 具体品牌
- 具体型号
- 具体主体类型
- 具体视频主题

即：

- `edc_tactical` 不能再隐式代表某些既有品牌或型号
- `tutorial_standard` 不能再因为出现少量 tech 词就强行把主体改成软件工具

## Hard Failure Rules

出现以下任一情况时，主体字段直接留空并待审：

1. 当前证据源之间互相冲突
2. 只有单一弱证据命中
3. 只有历史记忆支撑，没有当前视频证据
4. 候选只能靠领域词包或模板推出
5. 当前证据不足以同时解释品牌、型号、类型的一致关系

## Proposed Module Decomposition

当前 [content_profile.py](/E:/WorkSpace/RoughCut/src/roughcut/review/content_profile.py) 过于臃肿，重构后拆为：

- `src/roughcut/review/content_profile/evidence.py`
  - Evidence bundle 定义、原始证据采集、标准化
- `src/roughcut/review/content_profile/candidates.py`
  - 从当前证据提取 brand/model/type/theme 候选
- `src/roughcut/review/content_profile/scoring.py`
  - 候选评分、冲突检测、来源一致性判定
- `src/roughcut/review/content_profile/resolve.py`
  - 将候选解析为最终主体字段
- `src/roughcut/review/content_profile/enrich.py`
  - 基于已定主体生成摘要、互动问题、封面标题和搜索词
- `src/roughcut/review/content_profile/memory.py`
  - 仅保留命中后规范化和审核提示，不再生成主体
- `src/roughcut/review/content_profile_legacy.py`
  - 兼容旧入口，承接迁移过程

## Data Contracts

### EvidenceBundle

至少包含：

- `transcript_lines`
- `frame_hints`
- `ocr_texts`
- `source_name_tokens`
- `visible_text`
- `source_spans`

要求：

- 每个候选都能回溯到原始证据位置
- 评分器能知道候选来自哪一类来源

### Candidate

至少包含：

- `value`
- `field_name`
- `source_type`
- `source_excerpt`
- `normalized_value`
- `confidence`
- `normalization_applied`

### ReviewHints

至少包含：

- `memory_matches`
- `prior_corrections`
- `canonicalization_notes`

`ReviewHints` 仅用于审核解释，不能反向写回最终主体。

## Migration Strategy

### Phase 1: Extract Interfaces

- 定义 `EvidenceBundle` / `Candidate` / `ReviewHints`
- 在旧链路外包一层新接口
- 保证现有 API 入参出参不变

### Phase 2: Move Identity Resolution Out of Legacy Heuristics

- 先替换主体识别主链
- 保留摘要、标题、互动问题等增强逻辑在旧实现中运行
- 切断历史记忆和领域词包对主体字段的写权限

### Phase 3: Rebuild Enrichment on Top of Resolved Profile

- 把摘要、hook、query 生成迁移到新模块
- 禁止 enrichment 回写主体身份

### Phase 4: Delete Legacy Injection Paths

删除或禁用以下能力：

- 通过历史记忆创建主体字段
- 通过 domain pack 直接注入 tech / gear 品牌
- 通过全局品牌映射在无当前证据时回填主体
- 通过 tech subject fallback 覆盖已识别的实体产品主体

## Testing Strategy

### Unit Tests

新增测试覆盖：

- 当前视频出现错写品牌时，normalization 生效
- 当前视频没出现目标词时，历史记忆不得注入主体
- 领域词包存在相关品牌时，不得跨视频注入主体
- tech 词仅出现在背景弱证据中时，不能覆盖手持实体产品主体
- 证据冲突时，主体字段留空
- enrichment 不得反向修改主体字段

### Regression Tests

必须补齐以下回归场景：

1. 用户历史上测试过的品牌/型号，不得污染一个完全无关的新视频
2. EDC 视频不得因为 tech 词或旧测试词变成软件类主体
3. 软件教程视频不得因为 gear 词包或旧品牌映射变成产品开箱
4. 当前视频证据不足时，必须输出空主体并待审，而不是猜测

### Integration Tests

验证 `run_content_profile` 全链路：

- 自动识别路径仍能正常运行
- review gate 与主体识别解耦
- content profile draft API 输出字段兼容
- 审核页仍能展示 review hints，但不会把 hints 当成主体事实

## Non-Goals

本次重构不解决：

- 所有 LLM 识别准确率问题
- UI 文案整体重做
- 搜索 provider 全面替换
- 包装策略和封面风格策略重构

这些内容只有在它们直接依赖旧主体注入逻辑时，才进行必要调整。

## Expected Outcome

重构完成后，RoughCut 的自动识别链应具备以下行为：

- 默认仍自动识别
- 识别结果只来自当前视频证据
- 历史词、测试词、跨视频记忆不能再改写当前主体
- 证据不足时保守留空并待审
- 自动化覆盖率可能短期下降，但错误跨视频污染应显著收敛
- 每个最终主体字段都能回溯到当前任务中的证据来源
