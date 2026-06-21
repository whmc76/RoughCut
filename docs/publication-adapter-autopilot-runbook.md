# 发布链路自愈手册（多适配器）

本文档用于统一 RoughCut 的发布链路运行方式：同一份发布素材与发布物料，在多个适配器/执行模式下做可复用校验、真实执行与自动恢复探索，最终沉淀可复用 playbook。

## 目标

- 先判断可执行性（环境、agent、profile、page tab）。
- 先判断当前平台是否已有旧草稿或脏上下文，再决定是否清理。
- 再校验后端发布合同链路（不触发真实发布）。
- 再做发布前字段/素材就绪校验。
- 最后走真实发布闭环（可选只走草稿/私域）。
- 真实点击发布后，必须区分“待平台回执”与“草稿污染/发布失败”。
- 在失败时自动提取根因线索，给出“下一步最可能有效动作”。
- 将建议与失败特征沉淀到 `publication-autopilot-knowledge.json`，用于后续自动化迭代。

## 严格状态机原则

推荐固定成如下顺序，不要跳步：

1. 草稿探测：先确认平台当前 tab 是否已有旧草稿、旧素材、脏字段、错误路由。
2. 草稿决策：只有确认存在旧草稿污染、脏页面或失败残留时，才执行 `clear_draft_context`。
3. 发布前校验：素材上传、字段写入、计划签名、字段快照、声明/合集/可见性等必须先过。
4. 真正发布：执行最终 `发布/提交/预约` 点击，并等待平台回执窗口。
5. 发布后核验：优先看最终链接、平台管理页、审核态/预约态，不要只看提交后表单是否被清空。
6. 已发布收口：只有终态为 `published / scheduled_pending`，且公开链接/回执与计划字段可对账，才算闭环。

特别注意：

- `submitted` / `processing` 且签名匹配时，优先视为“待平台回执”，不要直接当作草稿污染。
- 只有确认未发布、未进入审核、未进入预约，且页面仍残留旧草稿时，才进入清稿恢复。

## 适配器模型

当前可编排链路支持下列适配器：

| 平台 | 默认适配器 | 可选执行模式 |
|------|------------|--------------|
| `douyin` / `xiaohongshu` / `bilibili` / `kuaishou` / `toutiao` / `youtube` / `wechat-channels` | `browser_agent` | `browser_agent` |
| `x` | `x_link_share`（默认） | `link_share`（默认）、`video` |

说明：

- `platform-adapter` 用于显式指定适配器，示例：`x=x_link_share`、`x=browser_agent`。
- `platform-execution-mode` 用于显式指定执行模式，示例：`x=link_share`、`x=video`。
- `x-mode` 决定 `x` 的默认行为：`link_share` 默认走转链，`video` 则走长视频发布流程。

## 命令链路（推荐顺序）

### 0. 启动 browser-agent 与 profile

## 浏览器权威合同（必须遵守）

发布链路唯一允许的浏览器执行面如下：

- 浏览器/profile 必须由当前任务绑定的创作者卡片 / publication credential 决定，不能写死系统默认浏览器，也不能写死某个全局 profile。
- 对本地测试任务，这个绑定应从创作者卡片 / publication credential 解析，例如：
  - 浏览器：`Google Chrome`
  - 用户数据目录：`<your Chrome User Data directory>`
  - Profile：`<your Chrome profile directory>`
  - RoughCut 复用 profile id：`browser-profile:chrome:<local-profile-id>`
- browser-agent 入口：`http://127.0.0.1:49310`
- browser transport：`bridge://chrome-extension`
- 执行扩展：`RoughCut Publication Bridge`
- 扩展实现方式：Chrome extension `background.js` 通过 `chrome.debugger` 暴露真实已登录 Chrome 会话给 `publication-browser-agent`

发布链路只允许通过下面这条调用链触发页面操作：

1. `scripts/start_publication_browser_session.ps1`
2. `pnpm dev:publication-browser-agent`
3. `scripts/run_publication_preflight.py`
4. `scripts/run_publication_release_gate.py`
5. `scripts/run_publication_real_release_gate.py`
6. `publication-browser-agent -> /tasks | /probes -> bridge://chrome-extension -> creator-card-bound Chrome profile`

明确禁止：

- 使用 Codex 的 Chrome 插件直接 `openTabs/new/goto` 来做发布摸底
- 使用 in-app Browser / Edge / 默认系统浏览器做发布页摸底
- 把 Edge 中打开的页面、无授权页面、未绑定当前任务创作者卡片浏览器 binding 的页面当成发布链路证据
- 在没有 `attached_profile_binding` 匹配当前任务创作者卡片绑定的情况下继续跑发布测试

判定标准：

- `GET /healthz` 必须显示：
  - `attached_profile_binding.browser = chrome`
  - `attached_profile_binding` 与当前任务创作者卡片解析出的 browser binding 一致
  - `browser_transport.transport = chrome_extension_bridge`
- 不满足上述条件时，整次发布摸底/测试结果无效，必须直接停止，不得写入平台结论。

先启动 CDP + `publication-browser-agent` 并固定 profile（请按你本地真实 profile 替换路径）。

发布链路不要再手写一整条 Chrome 启动命令。`User Data`、`Profile 2` 这类带空格参数如果拆开，Chrome 会把多出来的 `Data`、`2` 当成 URL，直接多开 `data/`、`0.0.0.2` 之类的废标签页，既污染会话也浪费资源。统一改用：

```powershell
powershell -File .\scripts\start_publication_browser_session.ps1 `
  -UserDataDir "<your Chrome User Data directory>" `
  -ProfileDirectory "<your Chrome profile directory>"
```

默认会同时通过 `--load-extension` 自动加载 repo 内的 `browser/publication-bridge-extension`。只有在明确做无桥调试时，才允许额外传 `-DisableBridgeExtension`。

```bash
pnpm dev:publication-browser-agent
```

发布页需要提前打开（除非开启 `--allow-anonymous-profile` 做临时调试）。

### 1) preflight（能力与环境可复用性）

```bash
pnpm run publication:preflight --platform douyin --platform x --target-profile-id <profile-id>
```

通过标准：

- `agent_ready.ready=true`
- `cdp_connected=true`
- `--require-tabs` 下各平台 tab 为 `found`

失败时会直接返回可复用 code，例如：

- `browser_agent_unavailable`
- `browser_agent_cdp_unavailable`
- `browser_agent_profile_reuse_unverified`
- `platform_tab_autocreate_disabled`（发布任务层面）

### 2) release-gate（发布前置静态验收）

```bash
pnpm run publication:release-gate --platform douyin --platform x --target-profile-id <profile-id>
pnpm run publication:release-gate:dry --platform douyin --platform x --target-profile-id <profile-id>
```

用于检查：

- preflight 同步能力；
- 后端合同烟测（fake browser-agent）是否能生成并推进到预期终态；
- `created_attempts` 与目标平台数是否匹配。

### 3) real-release-gate（真实执行闭环验收）

```bash
pnpm run publication:release-gate:real \
  --media-path ./assets/sample.mp4 \
  --platform-packaging ./artifacts/publication-packaging.json \
  --target-profile-id <profile-id> \
  --platform x \
  --platform-adapter x=x_link_share \
  --platform-execution-mode x=link_share
```

`--visibility-mode draft` 可用于只做流程验证，避免公开发布。

### 4) autopilot（连续闭环 + 自愈探索）

```bash
pnpm run publication:autopilot \
  --media-path ./assets/sample.mp4 \
  --platform-packaging ./artifacts/publication-packaging.json \
  --material-json ./smart-copy/smart-copy.json \
  --target-profile-id <profile-id> \
  --platform douyin --platform x \
  --platform-adapter x=x_link_share \
  --platform-execution-mode x=link_share \
  --expected-status published,scheduled_pending \
  --auto-retry --retry-cycles 2
```

Autopilot 的动作：

- 先执行 `material_gate`：要求存在可机读的 `smart-copy.json/material_contract`，并且目标平台 `one_click_publish_ready=true`；否则直接在物料层失败，不进入真实发布。
- `stable-primary` 阶段先跑稳定平台（默认 douyin/xiaohongshu...）。
- `x-post` 阶段根据 `x-mode` 处理 x 平台。
- 每轮执行 preflight → release-gate（可跳过）→ real-release-gate。
- 失败会输出：
  - `execution[*].report`：每阶段原始诊断。
  - `execution[*].mitigation.steps`：基于失败文本提炼的处理清单。
  - `execution[*].mitigation.playbook`：可直接下发给下一轮重试/修复的执行项。
- 关键产物：`artifacts/publication-autopilot/run-<time>/autopilot_report.json`。

物料层最新约束：

- `smart-copy.json` 现在会输出 `material_contract`，区分：
  - `basic_publish_ready`
  - `one_click_publish_ready`
- autopilot 现在会在正式发布前额外执行 `duplicate_history_gate`：
  - 按 `当前 media_path + 当前平台 + 当前 profile` 审计历史重复发布风险
  - 命中 `multiple_successful_publications / multiple_active_attempts / multiple_schedule_variants_same_live_content` 时，默认阻断 live
  - 只有显式传 `--allow-republish` 才允许带 warning 继续
- `platform-packaging.json` 现在会和 `platform-packaging.md` 一起落盘，保留标题、正文、标签之外的发布字段：
  - `cover_path`
  - `copy_material`
  - `declaration`
  - `category`
  - `collection / collection_name`
  - `visibility_or_publish_mode`
  - `scheduled_publish_at`
- 如果 `--material-json` 省略，autopilot 会先尝试从 `platform-packaging.json` 同目录自动探测 `smart-copy.json`。

## 失效信号与固定化建议

| 失效信号 | 优先处理 |
|---------|----------|
| profile 不可复用（`target_profiles_not_declared` / `profile_binding_not_declared`） | 对齐 `publication_browser_agent` 的 `reusable_profile_ids`、`profile_id` 映射和 profile 绑定策略 |
| tab 丢失（`platform_tab_autocreate_disabled`） | 按固定 profile 打开对应平台发布页并保持会话稳定，确认 `--require-tabs` |
| 草稿残留（`draft`/`草稿` 相关） | 执行草稿清理后重试（`--platform-execution-mode` 不变，尽量保留材料签名） |
| 重复发布阻断（`duplicate`） | 检查去重策略与 `--allow-republish` 使用边界，避免重复试跑 |
| 历史重复风险阻断（`duplicate_history_gate`） | 先跑历史重复审计，清理多成功/多 active/多定时变体；未清理前不要继续 live |
| 字段或签名不一致 | 重点核对 packaging 物料、`platform` 下的文案/标签/可见性参数是否与运行时快照一致 |

## 固化与改进闭环

- 对每次失败的核心信息会写入：
  - `artifacts/publication-autopilot/publication-autopilot-knowledge.json`
- 建议按失败 class 归档到团队约定文件（例如 `knowledge/publication-playbook.md`），形成：
  - 失败类目
  - 首选处理顺序
  - 参数修复模板
  - 复发阈值与回归测试命令

下次升级时新增自动修复策略优先从以下文件/入口开始：

- `scripts/run_publication_autopilot.py`（命令与自动修复映射入口）
- `scripts/run_publication_real_release_gate.py`（真实执行的错误码/恢复策略）
- `scripts/run_publication_release_gate.py`（合同验收参数）
- `scripts/run_publication_preflight.py`（前置能力判定）
- `scripts/audit_publication_duplicates.py`（历史重复巡检入口）

历史重复巡检最小命令：

```bash
PYTHONPATH=src python scripts/audit_publication_duplicates.py --platform douyin --media-path <video> --output artifacts/publication-autopilot/douyin-duplicate-audit.json
```

## 最小运行清单（标准化）

```bash
pnpm dev:publication-browser-agent
pnpm run publication:preflight --require-tabs --target-profile-id <profile-id>
pnpm run publication:release-gate --require-tabs --target-profile-id <profile-id>
pnpm run publication:release-gate:real --media-path <video> --platform-packaging <json> --target-profile-id <profile-id> --visibility-mode draft --expected-status draft_created
pnpm run publication:autopilot --media-path <video> --platform-packaging <json> --target-profile-id <profile-id> --auto-retry --retry-cycles 2
```

其中 `profile-id` 取发布凭据里与绑定浏览器可复用的 profile 标识；如你启用 `allow_republish` 或切换适配器，务必在复盘记录中标注并单独验证。
