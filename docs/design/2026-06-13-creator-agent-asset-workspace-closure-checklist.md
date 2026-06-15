# Creator-Agent Asset Workspace Closure Checklist

## Purpose

这份文档不是产品愿景稿，而是当前这轮重构的执行和收口清单。

判断标准只有两个：

- 是否完成了“创作者绑定 + Agent 生成”的新模型落地。
- 是否把旧五入口、旧创建方式、旧包装配置式交互降级到兼容层，而不是继续留在主流程。

配套文档：

- 架构与产品模型：`docs/design/2026-06-13-creator-agent-asset-workspace-execution-plan.md`
- 当前任务状态：`docs/agent-current-state.md`

## Delivery Scope

本轮必须交付的对象：

1. 创作资产四个新页面
2. 创建任务页重构
3. 任务流程页重构
4. 创作者绑定后端模型、API、迁移
5. 旧入口、旧路由、旧配置式主流程的清理或降级
6. 一份最终 closure note

## Workstreams

### A. Domain And Backend

必须完成：

- `creator_cards` 成为创作资产根对象。
- `task strategies / visual plans / publication profiles` 都绑定 `creator_card_id`。
- 任务创建持久化：
  - `creator_card_id`
  - `task_brief`
  - `execution_mode`
  - `platform_targets`
- 任务创建后生成 `job_agent_plan`。
- strategy / visual / publication 的 `generate / refine / activate / versions` 合同可用。
- 所有 refine 写版本，不允许直接覆盖当前版。

收口证据：

- migration 可执行且已通过一次真实升级
- API 单测通过
- 至少一条真实接口请求能返回 creator cards 和 jobs

### B. Frontend Information Architecture

必须完成：

- “创作资产”主导航只保留四个入口：
  - 创作者卡片库
  - 任务策略库
  - 智能视觉方案
  - 智能发布管理
- 四个页面都以“先选创作者，再看方案/规则/物料”为基本上下文。
- 旧五入口不能继续占据主导航。
- 旧页面如暂时保留，只能作为兼容路由存在，不能继续作为主心智入口。

收口证据：

- 浏览器截图或自动化读取到四个导航标签
- `rg` 死路由扫描结果可解释

### C. Create Job Refactor

必须完成：

- 创建任务页主流程只保留四类输入：
  - 创作者
  - 素材
  - 本条想法
  - 执行方式
- 平台目标允许跟随创作者或临时指定，但不能回退成一堆包装参数。
- `ConfigProfileSwitcher` 不再出现在主创建流程。
- 旧剪辑方案列表、风格模板列表、包装参数表不再出现在创建任务第一屏。

收口证据：

- 创建任务弹窗截图
- 前端代码中主创建路径不再引用旧方案管理器

### D. Job Flow Dashboard

必须完成：

- 任务详情第一屏展示：
  - 当前状态
  - 当前阶段
  - execution mode
  - creator / strategy / visual / publication 摘要
- 展示 `job_agent_plan` 阶段轨道和 Agent 决策摘要。
- 提供自然语言调整入口。
- 保留取消、重启、删除、下载、目录、待人工处理等旧操作路径。
- 原步骤日志、诊断、质量报告保留，但降级为折叠详情。

收口证据：

- 任务详情截图
- 至少一次 `refine` 或 `apply` 接口调用记录

### E. Legacy Cleanup

必须完成：

- 旧五入口从主导航移除。
- 旧页面若还有保留，必须明确标记为兼容路由。
- 仅服务旧页面的 CSS、文案、入口映射要清掉。
- 新主流程中不能再出现“包装配置页式”的大表单。

收口证据：

- `rg "StyleLabPage|StyleTemplatesPage|CreativeModesPage|PackagingPage|ConfigProfileSwitcher"` 结果经过审计
- 保留项必须能说明为什么还要留

## Closure Gates

只有同时满足下面 7 个 gate，才允许判定“收口完成”。

### Gate 1: Schema And Migration

- [ ] `0020_creator_agent_assets.py` 可执行
- [ ] 本地 `alembic upgrade head` 成功
- [ ] migration 默认值、约束、外键在当前 DB 上可用

### Gate 2: API Contract

- [ ] `GET /api/v1/creator-cards` 成功
- [ ] `GET /api/v1/jobs` 成功
- [ ] creator strategy / visual / publication API 可用
- [ ] `GET /jobs/{id}/agent-plan` 合同可用
- [ ] refine 接口产生版本记录

### Gate 3: Frontend Compile

- [ ] `cd frontend && pnpm run typecheck`
- [ ] `cd frontend && pnpm run build`

### Gate 4: Backend Verification

- [ ] `python -m compileall src/roughcut/api src/roughcut/db/models.py src/roughcut/db/migrations/versions/0020_creator_agent_assets.py`
- [ ] `PYTHONPATH=src python -m pytest tests/test_creator_cards_api.py tests/test_creator_task_strategies_api.py tests/test_creator_visual_plans_api.py tests/test_creator_publication_profiles_api.py tests/test_job_agent_plan_api.py -q`
- [ ] 兼容回归测试通过：
  - `tests/test_product_controls.py`
  - `tests/test_content_profile_api_payloads.py`

### Gate 5: UX Verification

- [ ] 浏览器可进入四个创作资产新页面
- [ ] 创建任务页显示创作者选择、任务想法、执行方式、平台目标
- [ ] 任务详情页第一屏显示 Agent 决策摘要和阶段轨道
- [ ] 1440px 下无主视图重叠
- [ ] 390px 下无明显文字压叠和横向溢出

### Gate 6: Legacy Audit

- [ ] 主导航无旧五入口
- [ ] 主创建流程无旧包装配置入口
- [ ] 死路由/兼容路由已审计
- [ ] 无明显未引用旧组件残留

### Gate 7: Closure Evidence

- [ ] 四个新页面截图
- [ ] 创建任务页截图
- [ ] 任务流程驾驶舱截图
- [ ] 一条带 `job_agent_plan` 的任务记录
- [ ] 一次自然语言 refine 生成新版本的记录
- [ ] 验证命令摘要
- [ ] 旧代码清理清单

## Mandatory Final Deliverables

收口时必须同时提交：

1. 一份 closure note
2. 一组截图或自动化验证记录
3. 一组前后端验证命令摘要
4. 一份旧代码清理说明

## Closure Note Template

最终 closure note 至少包含以下字段：

```text
标题
日期
范围

1. 已完成页面
- 创作者卡片库
- 任务策略库
- 智能视觉方案
- 智能发布管理
- 创建任务页
- 任务流程页

2. 后端落地
- migration
- models
- APIs
- version semantics

3. 联调结果
- live API checks
- browser checks

4. 验证命令
- frontend
- backend
- tests

5. 旧代码清理
- 删除项
- 保留兼容项
- 后续待删项

6. 未完成项 / 残余风险
```

## Explicit Non-Closure Conditions

出现以下任一情况，都不能算收口：

- 还需要用户在创建任务时手动挑包装模板
- 任务策略、视觉方案、发布管理仍有任何一个不绑定创作者
- refine 会覆盖旧版本
- 新页面只是静态壳，真实 API 不通
- `/api/v1/jobs` 或 `/api/v1/creator-cards` 在当前迁移后的本地库里仍报错
- 旧五入口虽然不在文案上显示，但实际主流程还在偷偷复用
- 任务详情页仍然看不到 Agent 的策略、视觉、发布摘要
