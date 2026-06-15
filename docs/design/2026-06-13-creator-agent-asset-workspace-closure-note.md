# Creator-Agent Asset Workspace Closure Note

日期：2026-06-13

范围：创作资产四入口重构、创建任务页重构、任务流程驾驶舱重构、创作者绑定后端合同、联调与收口核验。

状态：`验证已完成；Gate 6 旧代码清理已收口`

## 1. 已完成页面

- 创作者卡片库
- 任务策略库
- 智能视觉方案
- 智能发布管理
- 创建任务弹窗
- 任务流程驾驶舱

浏览器截图：

- 创作者卡片库：`C:\Users\28687\AppData\Local\Temp\asset-creator-cards.png`
- 任务策略库：`C:\Users\28687\AppData\Local\Temp\asset-task-strategies.png`
- 智能视觉方案：`C:\Users\28687\AppData\Local\Temp\asset-visual-plans.png`
- 智能发布管理：`C:\Users\28687\AppData\Local\Temp\asset-publication-management.png`
- 创建任务桌面：`C:\Users\28687\AppData\Local\Temp\create-job-desktop-final.png`
- 创建任务移动：`C:\Users\28687\AppData\Local\Temp\create-job-mobile-final.png`
- 任务驾驶舱：`C:\Users\28687\AppData\Local\Temp\job-detail-desktop-final.png`

## 2. 后端落地

已落地：

- 新 migration：`src/roughcut/db/migrations/versions/0020_creator_agent_assets.py`
- 新模型：
  - `CreatorCard`
  - `CreatorAsset`
  - `CreatorPreference`
  - `CreatorTaskStrategy`
  - `TaskStrategyVersion`
  - `CreatorVisualPlan`
  - `VisualPlanVersion`
  - `CreatorPublicationProfile`
  - `CreatorPlatformBinding`
  - `PublicationProfileVersion`
  - `JobAgentPlan`
- `Job` 已扩展：
  - `creator_card_id`
  - `task_brief`
  - `execution_mode`
  - `platform_targets_json`
- 新 API：
  - creator cards / task strategies / visual plans / publication profile
  - `GET /jobs/{id}/agent-plan`
  - `POST /jobs/{id}/agent-plan/refine`
  - `POST /jobs/{id}/agent-plan/apply`
  - `GET /jobs/{id}/agent-decisions`

版本语义：

- refine 通过 `Artifact` 写 `job_agent_plan_revision`
- creator strategy / visual / publication 通过各自 version 表保留版本

## 3. 本轮联调修复

### 修复 A：migration 默认值兼容 PostgreSQL

- 现象：`alembic upgrade head` 失败
- 第一坏层：`0020_creator_agent_assets.py`
- 根因：布尔默认值写成 `sa.text(\"0\")`，PostgreSQL 不能作为 boolean 默认值
- 修复：改为 `sa.text(\"false\")`

### 修复 B：历史任务读取 agent-plan 时 500

- 现象：`GET /api/v1/jobs/{id}/agent-plan` 对旧任务返回 500
- 第一坏层：`src/roughcut/api/jobs.py::_build_job_agent_plan_payload(...)`
- 根因：兼容分支直接读取 `job.video_description`，但 `Job` ORM 没有这个字段；历史任务也没有 `task_brief`
- 为什么现在暴露：新 agent-plan 接口开始给历史任务回填 plan，单测主要覆盖新任务路径
- 修复：改为安全读取 `task_brief or getattr(job, \"video_description\", \"\")`
- 回归：`tests/test_job_agent_plan_api.py::test_job_agent_plan_generates_for_legacy_job_without_creator_or_video_description`

## 4. 联调结果

### Live API checks

服务：

- `http://127.0.0.1:8012`

通过：

- `GET /api/v1/creator-cards`
- `GET /api/v1/jobs?limit=5&offset=0`
- `GET /api/v1/jobs/ee571a8a-d27b-40ca-b9e5-0c12b2ce2a70/agent-plan`
- `POST /api/v1/jobs/ee571a8a-d27b-40ca-b9e5-0c12b2ce2a70/agent-plan/refine`

live refine 证据：

- job id：`ee571a8a-d27b-40ca-b9e5-0c12b2ce2a70`
- refine target：`visual`
- prompt：`标题更克制一点，封面更像测评结论，不要广告感。`
- 返回：`status=refined`

revision 落库证据：

- 查询结果：`{'total': 2, 'operation': 'refine:visual', ...}`

说明：

- `total=2` 表示该任务当前至少已有一次 generate + 一次 refine revision artifact

### Browser checks

桌面 1440px：

- 四个新入口可达
- 创建任务弹窗显示：
  - 创作者卡片
  - 执行方式
  - 本条任务想法
  - 平台目标
- 任务详情第一屏显示：
  - 当前阶段
  - 计划状态
  - 执行方式
  - 人工介入
  - 创作者卡片 / 任务策略 / 智能视觉方案 / 智能发布管理摘要

移动 390px：

- 创建任务弹窗首屏未出现明显文字压叠
- 未观察到首屏横向溢出

## 5. 验证命令

前端：

```text
cd frontend
pnpm run typecheck
pnpm run build
```

结果：

- `typecheck` 通过
- `build` 通过

后端：

```text
python -m compileall src/roughcut/api src/roughcut/db/models.py src/roughcut/db/migrations/versions/0020_creator_agent_assets.py
$env:PYTHONPATH='src'; python -m pytest tests/test_creator_cards_api.py tests/test_creator_task_strategies_api.py tests/test_creator_visual_plans_api.py tests/test_creator_publication_profiles_api.py tests/test_job_agent_plan_api.py tests/test_product_controls.py tests/test_content_profile_api_payloads.py -q
```

结果：

- `compileall` 通过
- pytest：`20 passed`

新增回归：

```text
$env:PYTHONPATH='src'; python -m pytest tests/test_job_agent_plan_api.py -q
```

结果：

- `2 passed`

## 6. 旧代码清理审计

已满足：

- 主导航只保留四个新入口
- 创建任务主流程不再使用 `ConfigProfileSwitcher`
- 创建任务第一屏不再显示旧方案表和包装参数表

本轮删除项：

- `frontend/src/App.tsx` 移除兼容路由：
  - `/packaging`
  - `/style-lab`
  - `/style-templates`
  - `/creative-modes`
  - `/creator-profiles`
- 删除旧页面：
  - `frontend/src/pages/PackagingPage.tsx`
  - `frontend/src/pages/StyleLabPage.tsx`
  - `frontend/src/pages/StyleTemplatesPage.tsx`
  - `frontend/src/pages/CreativeModesPage.tsx`
  - `frontend/src/pages/CreatorProfilesPage.tsx`
- 删除旧组件：
  - `frontend/src/features/configProfiles/ConfigProfileSwitcher.tsx`
- `frontend/src/features/jobs/JobReviewConfigSection.tsx` 已改为直接跳转：
  - 任务策略库
  - 智能视觉方案
  - 智能发布管理

审计命令：

```text
rg "StyleLabPage|StyleTemplatesPage|CreativeModesPage|PackagingPage|ConfigProfileSwitcher" frontend/src -n
rg "style-lab|config-profile-switcher" frontend/src/styles.css -n
rg "style-lab|ConfigProfileSwitcher|CreatorProfilesPage|CreativeModesPage|StyleTemplatesPage|StyleLabPage|PackagingPage|config-profile-switcher" frontend/dist -n
```

审计结论：

- 源码搜索已归零
- `vite build` 产物不再包含旧页面 chunk
- `dist` 搜索已归零，旧入口对应样式和构建残留已退出当前产物

## 7. Gate 状态

### Gate 1: Schema And Migration

- 通过

### Gate 2: API Contract

- 通过

### Gate 3: Frontend Compile

- 通过

### Gate 4: Backend Verification

- 通过

### Gate 5: UX Verification

- 通过

### Gate 6: Legacy Audit

- 通过

### Gate 7: Closure Evidence

- 通过

## 8. 结论

本轮“前后端重构验证”已完成，且联调中暴露的 `agent-plan` 历史任务兼容问题已修复。

当前状态可以明确判断为：

- 新模型、新 API、新页面、新创建流程、新任务驾驶舱均已可验证
- 前后端主合同已经跑通
- 旧兼容路由、旧页面、旧方案切换组件和对应构建残留已清退完成

因此本轮可以定义为：

- “创作者绑定 + Agent 生成”的新资产工作区重构，已经完成完整收口
