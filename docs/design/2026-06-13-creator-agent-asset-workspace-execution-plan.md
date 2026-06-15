# Creator-Agent Asset Workspace Execution Plan

## Objective

把当前“创作资产”从五个并列配置入口重构为以创作者卡片为中心的 Agent 资产工作台，并同步改造创建任务页与任务流程监看页。

目标不是给旧页面换皮，而是完成产品模型迁移：

```text
旧模型：用户选择模板 / 方案 / 参数 -> 系统套用配置
新模型：创作者卡片 + 自然语言想法 + 素材理解 -> Agent 生成策略、视觉、发布方案
```

## Product Principles

- 创作者卡片是唯一根资产。任务策略、智能视觉方案、智能发布管理都必须绑定创作者。
- 用户用自然语言描述定位、偏好、禁忌和本条任务想法，不直接选择底层包装模板或调低层参数。
- 模板、案例、包装素材、发布配置都降级为 Agent 的参考资产和约束来源，不再作为创建任务主流程的一层选择。
- 创建任务页只收集创作者、素材、本条想法和执行方式。
- 任务流程页展示 Agent 为什么这样剪、这样包装、这样发布，并允许自然语言调整。

## Target Navigation

把“创作资产”下现有五入口收敛为四入口：

```text
01 创作者卡片库
02 任务策略库
03 智能视觉方案
04 智能发布管理
```

旧入口迁移：

```text
创作者档案 -> 创作者卡片库
创作模式   -> 任务策略库
风格模板   -> 智能视觉方案
风格实验   -> 智能视觉方案的生成、对比、调试工作区
包装素材   -> 创作者卡片库的素材资产 + 智能视觉方案的视觉参考 + 智能发布管理的平台物料
包装配置   -> 智能视觉方案 + 智能发布管理；低层参数进入高级兼容区
```

## Scope

### In Scope

- 新增四个创作资产页面的信息架构、路由、前端页面壳、核心交互。
- 新增创作者绑定的数据模型和 API。
- 新增 Agent 生成 / refine / activate 的后端合同。
- 创建任务页改为创作者驱动。
- 任务流程页改为 Agent 执行驾驶舱。
- 旧页面迁移、降级、清理计划。
- 现有 `workflow_mode / enhancement_modes / product_controls / packaging config` 的兼容映射。

### Out of Scope

- 不重开自动剪辑主链路架构。
- 不引入外部素材采购或供应商下载链路。
- 不在第一阶段删除可运行的旧后端合同。
- 不把自然语言 refine 做成不受控直接覆盖；所有 refine 必须产生版本记录。

## New Domain Model

### Creator Card

创作者卡片是根对象。

建议表：

```text
creator_cards
creator_assets
creator_preferences
creator_memory_entries
creator_reference_works
```

最小字段：

```text
creator_cards:
- id
- name
- positioning
- content_domains
- audience
- default_platforms
- natural_language_profile
- status
- created_at
- updated_at

creator_assets:
- id
- creator_card_id
- asset_type
- original_name
- stored_path
- metadata_json
- created_at

creator_preferences:
- id
- creator_card_id
- preference_type
- natural_language_rule
- structured_payload
- source
- version
- created_at
```

### Task Strategy

任务策略回答“这个创作者的视频应该怎么剪”。

建议表：

```text
creator_task_strategy_sets
creator_task_strategies
task_strategy_versions
task_strategy_generation_runs
```

策略 payload 示例：

```json
{
  "name": "专业测评标准成片",
  "strategy_type": "product_review",
  "intent": "先给结论，再展开依据",
  "automation_level": "balanced",
  "material_usage": "all_uploaded",
  "risk_gate": "manual_confirm_for_high_risk",
  "rules": [
    "产品测评前 8 秒必须出现核心判断",
    "教程类内容不得剪掉关键操作步骤"
  ],
  "fallback_mapping": {
    "workflow_mode": "standard_edit",
    "job_flow_mode": "auto",
    "enhancement_modes": ["auto_review"]
  }
}
```

### Visual Plan

智能视觉方案回答“这个创作者的视频应该长什么样”。

建议表：

```text
creator_visual_plan_sets
creator_visual_plans
visual_plan_versions
visual_plan_references
visual_plan_generation_runs
```

视觉 payload 示例：

```json
{
  "name": "专业测评型",
  "cover_direction": "产品特写 + 结论式短标题",
  "subtitle_direction": "中等密度，型号和参数高亮",
  "title_tone": "直接判断，不使用悬念党",
  "color_direction": "低饱和、干净、可信",
  "copy_tone": "事实判断优先",
  "platform_variants": {
    "bilibili": "信息密度更高，保留完整型号",
    "douyin": "前三秒结论更直接"
  },
  "reference_asset_ids": []
}
```

### Publication Management

智能发布管理回答“这个创作者的视频应该怎么发”。

建议表：

```text
creator_publication_profiles
creator_platform_bindings
creator_platform_material_rules
publication_credential_refs
publication_plan_versions
```

发布 payload 示例：

```json
{
  "default_platforms": ["bilibili", "douyin"],
  "publication_mode": "material_only",
  "platform_rules": {
    "bilibili": {
      "title_rule": "保留型号和完整结论",
      "tag_rules": ["汽车电子", "改装", "测评"],
      "category": "汽车"
    },
    "douyin": {
      "title_rule": "短句直接给结论",
      "intro_rule": "前三秒突出升级点"
    }
  },
  "credential_refs": {
    "bilibili": "encrypted_secret_ref"
  }
}
```

## Backend API Plan

### Creator Cards

```text
GET    /creator-cards
POST   /creator-cards
GET    /creator-cards/{creator_id}
PATCH  /creator-cards/{creator_id}
POST   /creator-cards/{creator_id}/assets
DELETE /creator-cards/{creator_id}/assets/{asset_id}
GET    /creator-cards/{creator_id}/memory
POST   /creator-cards/{creator_id}/refine
```

### Task Strategies

```text
GET  /creator-cards/{creator_id}/task-strategies
POST /creator-cards/{creator_id}/task-strategies/generate
POST /task-strategies/{strategy_id}/refine
POST /task-strategies/{strategy_id}/activate
GET  /task-strategies/{strategy_id}/versions
```

### Visual Plans

```text
GET  /creator-cards/{creator_id}/visual-plans
POST /creator-cards/{creator_id}/visual-plans/generate
POST /visual-plans/{visual_plan_id}/refine
POST /visual-plans/{visual_plan_id}/activate
GET  /visual-plans/{visual_plan_id}/versions
```

### Publication Management

```text
GET    /creator-cards/{creator_id}/publication-profile
PATCH  /creator-cards/{creator_id}/publication-profile
POST   /creator-cards/{creator_id}/publication-profile/refine
POST   /creator-cards/{creator_id}/platform-bindings
DELETE /creator-cards/{creator_id}/platform-bindings/{platform}
```

### Job Agent Plan

创建任务后，后端需要产生任务级 Agent 执行计划。

```text
GET  /jobs/{job_id}/agent-plan
POST /jobs/{job_id}/agent-plan/refine
POST /jobs/{job_id}/agent-plan/apply
GET  /jobs/{job_id}/agent-decisions
```

建议表：

```text
job_agent_plans
job_strategy_decisions
job_visual_decisions
job_publication_decisions
job_agent_messages
```

所有 refine 必须产生新版本，不允许静默覆盖上一版。

## Frontend Page Plan

### 1. 创作者卡片库

页面目标：创建和维护创作者根资产。

布局：

```text
左侧：创作者卡片列表
右侧：选中创作者详情
顶部：新建创作者 / 上传资产 / Agent 调整
```

模块：

- 基础信息
- 自然语言定位
- 素材资产
- 参考作品
- 禁忌和偏好
- Agent 记忆
- 关联策略入口

主要交互：

- 新建创作者
- 上传素材资产
- 用自然语言调整创作者定位
- 查看已绑定的任务策略、视觉方案、发布管理状态

### 2. 任务策略库

页面目标：为选中创作者生成和维护剪辑策略。

布局：

```text
顶部：创作者选择器 + 当前默认策略集
中部：策略卡片列表
右侧或下方：自然语言生成 / 修改面板
```

模块：

- 自动判断
- 标准成片
- 教程讲解
- 高光提炼
- 多素材组装
- 产品测评
- 长视频切片

每张策略卡展示：

- 策略名称
- 适用场景
- 自动化边界
- 素材使用策略
- 人工确认条件
- 最近应用任务

### 3. 智能视觉方案

页面目标：为选中创作者生成和维护视觉、封面、字幕、标题、文案风格。

布局：

```text
顶部：创作者选择器 + 生成视觉方案按钮
中部：候选方案对比
右侧：自然语言调整面板
底部：参考案例 / 禁用风格 / 应用记录
```

每套视觉方案展示：

- 封面方向
- 标题气质
- 字幕方向
- 色彩 / 字体倾向
- 文案风格
- 平台差异
- Agent 采用理由

### 4. 智能发布管理

页面目标：为选中创作者管理平台发布、物料规则和凭证绑定。

布局：

```text
顶部：创作者选择器 + 发布模式
中部：平台绑定和状态
下方：平台物料规则
右侧：自然语言调整面板
```

模块：

- 平台账号绑定状态
- 发布权限边界
- 默认发布平台
- 栏目 / 分区 / 合集
- 标题、简介、标签规则
- 发布时间策略
- 自动发布 / 只生成物料 / 手动交接

## Create Job Page Refactor

### New Job Creation Surface

创建任务页只保留高层输入：

```text
1. 选择创作者
2. 上传素材
3. 描述本条想法
4. 选择执行方式
```

推荐布局：

```text
顶部状态条：
创作者 / 素材数量 / 执行方式 / 创建按钮

左侧：
素材上传、排序、预览

右侧：
创作者摘要
本条任务想法
执行方式：全自动 / 先生成方案 / 智能辅助
平台目标：跟随创作者 / 临时指定

底部：
Agent 将自动应用的任务策略、智能视觉方案、发布管理配置摘要
```

需要移除或折叠：

- 完整 `ConfigProfileSwitcher`
- 旧剪辑方案列表
- 旧包装参数表
- 风格模板选择器
- 大量增强开关
- 低层阈值差异

### Job Create Payload

建议扩展：

```json
{
  "creator_card_id": "creator-id",
  "task_brief": "这条是新品开箱和老款对比，突出升级点和适合谁",
  "execution_mode": "auto",
  "platform_targets": ["bilibili", "douyin"],
  "files": []
}
```

兼容映射：

```text
creator_card_id + task_brief
-> task_strategy
-> visual_plan
-> publication_profile
-> product_controls / workflow_mode / enhancement_modes
-> existing pipeline
```

## Job Flow Page Refactor

任务详情页改为 Agent 执行驾驶舱。

布局：

```text
顶部驾驶舱：
任务状态 / 当前阶段 / 进度 / 人工介入状态 / 操作按钮

Agent 决策摘要：
创作者卡片 / 任务策略 / 智能视觉方案 / 发布管理方案

流程轨道：
素材理解 -> 内容分析 -> 任务策略 -> 剪辑决策 -> 视觉包装 -> 渲染 -> 发布物料 -> 质量门

当前阶段解释：
正在做什么 / 为什么这么做 / 下一步是什么 / 是否需要确认

候选方案：
标题 / 封面 / 字幕 / 文案 / 平台物料候选

自然语言调整：
用户输入“标题更克制”“封面不要像广告”“抖音前三秒更直接”

折叠详情：
步骤日志 / Token 使用 / 字幕诊断 / 质量报告
```

必须保留：

- 现有取消、重启、删除、打开目录、下载行为。
- 现有步骤日志和诊断能力。
- 现有 `needs_review`、`awaiting_manual_edit`、失败任务的操作路径。

## Implementation Phases

### Phase 0: Contract Freeze and UX Skeleton

目标：先固定新产品模型，不破坏旧功能。

任务：

- 新增本文档到设计索引。
- 新增前端路由和四个页面壳。
- 导航从五入口改为四入口，但旧入口代码暂不删除。
- 创建任务页先增加创作者选择位和本条想法位，不接 Agent 生成。
- 任务详情页先增加 Agent 决策摘要占位。

验收：

- 前端可进入四个新页面。
- 旧任务创建、旧任务列表、旧详情页仍可用。
- `pnpm run typecheck` 通过。

### Phase 1: Creator Card Backend

目标：让创作者卡片成为真实后端资产。

任务：

- 新增 DB migration。
- 新增 creator card CRUD。
- 新增 creator assets 上传和列表。
- 新增 creator natural-language profile 字段。
- 新增基础前端数据接入。

验收：

- 可创建、编辑、删除、查看创作者卡片。
- 可上传并列出创作者资产。
- API 单测覆盖 CRUD 和资产绑定。
- 前端类型检查通过。

### Phase 2: Strategy / Visual / Publication Contracts

目标：建立三个创作者绑定方案的版本化合同。

任务：

- 新增 task strategy 数据模型和 API。
- 新增 visual plan 数据模型和 API。
- 新增 publication profile 数据模型和 API。
- 所有方案支持 generate/refine/activate 的空实现或规则实现。
- 每次 refine 写版本记录。

验收：

- 一个创作者可拥有策略、视觉、发布三类资产。
- 每类资产都能生成候选、激活默认、保留版本。
- refine 不覆盖旧版本。
- 后端测试覆盖版本语义。

### Phase 3: Agent Generation

目标：让自然语言输入能生成可解释方案。

任务：

- 接入现有 reasoning provider。
- 为三类方案分别建立 prompt 和结构化输出 schema。
- Agent 输出必须包含：方案内容、采用理由、风险、可调整项。
- 失败时回退到规则生成，不阻塞页面。

验收：

- 给定创作者定位和自然语言想法，可生成 2-4 套视觉方案。
- 可生成任务策略集。
- 可生成发布管理规则。
- 输出结构可解析、可保存、可再次 refine。
- 测试覆盖成功、失败、fallback。

### Phase 4: Create Job Integration

目标：创建任务改为创作者驱动。

任务：

- 创建任务 payload 支持 `creator_card_id / task_brief / execution_mode / platform_targets`。
- 后端创建任务时生成 `job_agent_plan`。
- 将新策略映射到现有 `workflow_mode / job_flow_mode / enhancement_modes / product_controls`。
- 前端移除创建弹窗里的完整旧方案选择器。

验收：

- 选择创作者、上传素材、输入想法即可创建任务。
- 没有创作者时仍有兼容默认路径。
- 创建后任务记录能看到使用的创作者、策略、视觉、发布配置。
- 旧任务创建 API 兼容不破坏。

### Phase 5: Job Flow Dashboard

目标：任务流程页展示 Agent 决策和可调整入口。

任务：

- 新增 `GET /jobs/{id}/agent-plan`。
- 详情页展示 Agent 决策摘要和流程轨道。
- 增加自然语言调整入口。
- 调整后写新版本并提示是否应用。
- 原步骤日志改为折叠区。

验收：

- 任务详情第一屏能看出：当前状态、当前阶段、使用策略、视觉方向、发布方向。
- 用户能用自然语言调整视觉或发布物料。
- 调整不会破坏当前任务状态机。
- 失败、待核对、待手动调整任务路径仍可操作。

### Phase 6: Old Code Cleanup

目标：下线旧五入口和低层配置式创建流程。

任务：

- 旧 `CreatorProfilesPage` 升级或替换为新创作者卡片库。
- 旧 `CreativeModesPage` 迁移到任务策略库。
- 旧 `StyleTemplatesPage`、`StyleLabPage` 迁移到智能视觉方案。
- 旧 `PackagingPage` 拆分迁移。
- 删除旧路由、旧导航、旧无用 CSS。
- 保留高级兼容入口给底层参数。

验收：

- 导航只剩四个新入口。
- 创建任务页不再出现完整旧配置方案或包装参数表。
- 旧组件无未引用代码，`rg` 检查无死路由。
- 全量前端 typecheck 通过。

## Closure Acceptance Criteria

本重构只有满足以下条件才算收口。

### Product Acceptance

- “创作资产”导航只保留四入口：创作者卡片库、任务策略库、智能视觉方案、智能发布管理。
- 任务策略、智能视觉方案、智能发布管理都必须先选择创作者卡片。
- 创建任务页不要求用户选择旧剪辑方案、风格模板或包装模板。
- 创建任务页主流程只包含：创作者、素材、本条想法、执行方式。
- 包装方案不再由用户手动选择模板；必须由智能视觉方案根据创作者和任务生成。
- 发布物料和平台配置由智能发布管理按创作者绑定管理。
- 用户可以用自然语言调整创作者、任务策略、视觉方案、发布管理和单个任务的 Agent 计划。

### Backend Acceptance

- 数据库中存在创作者卡片和三类创作者绑定方案的持久化模型。
- 三类方案都支持版本记录。
- 所有 refine 操作都写新版本，不静默覆盖。
- 创建任务能持久化 `creator_card_id` 和 `job_agent_plan`。
- 新策略能映射到现有 pipeline 所需合同，不引入第二条剪辑管线。
- 旧创建任务 API 或兼容入口不被破坏。
- 凭证类字段只保存安全引用，不向前端返回明文。

### Frontend Acceptance

- 四个新页面可从导航进入，并有清晰的创作者选择上下文。
- 创建任务弹窗在 1440px 桌面和 390px 移动宽度下不出现文字重叠或横向溢出。
- 任务详情页第一屏展示状态、阶段、策略、视觉、发布摘要。
- 步骤日志、Token 使用、字幕诊断、质量报告保留但降级为折叠详情。
- 旧五入口从主导航移除。
- `ConfigProfileSwitcher` 不再作为创建任务主流程组件出现。

### Verification Acceptance

必须至少通过：

```text
cd frontend
pnpm run typecheck
pnpm run build
```

后端必须至少通过：

```text
python -m py_compile src/roughcut/api/*.py src/roughcut/db/models.py
PYTHONPATH=src python -m pytest tests/test_product_controls.py tests/test_content_profile_api_payloads.py -q
```

新增后端 API 后必须补充对应单测：

```text
tests/test_creator_cards_api.py
tests/test_creator_task_strategies_api.py
tests/test_creator_visual_plans_api.py
tests/test_creator_publication_profiles_api.py
tests/test_job_agent_plan_api.py
```

### Migration Acceptance

- 旧创作者档案数据能迁移到创作者卡片。
- 旧创作模式能作为任务策略种子导入。
- 旧风格模板和风格实验结果能作为视觉参考导入。
- 旧包装素材能归入创作者资产或全局兼容素材池。
- 旧发布配置能归入创作者发布管理。
- 迁移脚本可重复运行，不重复插入同一源数据。

### Cleanup Acceptance

- 主导航不再引用旧五入口。
- 旧页面组件如果未被兼容入口使用，必须删除。
- 旧 CSS 中只服务于已删除页面的选择器必须删除。
- `rg "StyleLabPage|StyleTemplatesPage|CreativeModesPage|PackagingPage"` 只允许出现在迁移说明或兼容路由中。
- 不存在创建任务页仍嵌完整包装配置或方案管理器的路径。

## Final Closure Evidence

最终收口需要提交一份 closure note，至少包含：

- 四个新页面截图或浏览器验证记录。
- 创建任务页新流程截图。
- 任务流程页新驾驶舱截图。
- 一条真实或种子任务从创作者卡片创建并生成 `job_agent_plan` 的记录。
- 一次自然语言 refine 产生新版本的记录。
- 前后端验证命令输出摘要。
- 旧入口清理清单。
