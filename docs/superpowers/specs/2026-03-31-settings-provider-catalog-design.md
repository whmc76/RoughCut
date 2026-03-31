# 设置页 Provider 状态与模型目录设计

## 目标

把系统设置里的转写、推理、视觉回退三条链路统一成：

- 地址只读展示，不允许在设置页编辑环境地址
- 本地服务地址支持自动检测与手动验证
- 所有模型选择都改为下拉，不再要求用户手填
- Ollama 模型目录实时检测
- OpenAI、Anthropic、MiniMax 模型目录支持手动刷新并缓存
- 总览页、配置方案页、差异摘要同步适配新的状态与目录展示

## 现状

- 地址来自 `/config/environment`，并且被 `ENV_MANAGED_SETTINGS` 保护，前端不能直接写回
- `/config/options` 目前只返回静态 `transcription_models`
- 推理模型、视觉回退模型、本地模型仍然是文本输入
- 前端设置页只有 `config`、`runtimeEnvironment`、`options` 三类查询，没有服务状态和动态模型目录

## 范围

本次覆盖以下入口：

- 系统设置页
- 当前生效配置总览
- 配置方案切换与对比
- 差异摘要文案

不做以下事情：

- 不在设置页开放地址编辑
- 不改运行环境变量的来源和持久化方式
- 不重做整套 Provider 架构

## 方案

### 1. 新增服务状态接口

新增只读接口 `GET /config/service-status`，返回各服务的：

- provider 标识
- 用途分类，如 `transcription`、`reasoning`、`vision_fallback`
- 只读地址
- 当前状态，`ok` / `unreachable` / `unauthorized` / `not_configured`
- 错误原因
- 最后检查时间

规则：

- `ollama`、`qwen_asr`、数字人、语音服务做本地地址探测
- OpenAI、Anthropic、MiniMax 可返回“地址已配置 / 缺少 key / 刷新失败”这类只读状态
- 接口不回传敏感凭据

### 2. 新增模型目录接口

新增只读接口 `GET /config/model-catalog`，参数：

- `provider`
- `kind`，至少支持 `transcription`、`reasoning`、`vision_fallback`
- `refresh`，`0` 或 `1`

返回：

- provider
- kind
- models
- source，`cache` / `live`
- refreshed_at
- status
- error

模型来源规则：

- `ollama`：每次请求都直接读本地 Ollama 模型目录
- `openai` / `anthropic` / `minimax`：默认返回服务端缓存，只有 `refresh=1` 才重新拉取官方模型清单
- `funasr` / `local_whisper` / `qwen_asr`：返回内置或本地支持的模型列表；`qwen_asr` 额外带服务可达性结果

### 3. 服务端缓存策略

- 云端模型目录缓存保存在服务端内存或现有轻量缓存层
- 缓存键按 `provider + kind` 区分
- 手动刷新成功后覆盖缓存
- 刷新失败时保留旧缓存，同时返回错误信息

### 4. 前端设置页改造

设置页统一改成“先 Provider，后模型下拉”的交互：

- 转写 Provider 选择后，从对应目录里选择模型
- 推理 Provider 选择后，从目录里选择 `reasoning_model`
- 视觉回退 Provider 选择后，从目录里选择 `multimodal_fallback_model`
- 本地模式下的 `local_reasoning_model`、`local_vision_model` 都改成 Ollama 模型下拉

配套行为：

- 页面初始化时加载缓存目录
- 用户点击“刷新模型”时强制更新当前 Provider 的目录
- Ollama 单独显示“检测服务”与“刷新模型”
- 地址只读展示，旁边显示状态与错误原因

### 5. 展示层同步

以下页面同步适配：

- 设置总览：展示 provider、模型、状态摘要
- 配置方案页：展示 provider、模型，不再出现手填模型语义
- 差异摘要：当差异项是 provider 或模型时，使用统一显示名

如果当前已保存模型不在最新目录里：

- 保留原值
- 在 UI 中标成“已保存旧模型”
- 不自动清空，不强制覆盖

## 错误处理

- 服务不可达：保留当前已选模型，显示错误状态和原因
- 模型目录为空：下拉展示空态提示，但继续回显已保存值
- API key 缺失或鉴权失败：刷新失败，不阻断其他设置项加载
- 某个 Provider 刷新失败：不影响其他 Provider 的目录和缓存

## 测试要求

### 后端

- `service-status` 正常返回本地和云端状态
- `model-catalog` 支持 provider/kind/refresh
- Ollama 在线 / 离线
- 云端 Provider 刷新成功 / 鉴权失败 / 超时
- 刷新失败时保留旧缓存

### 前端

- Provider 切换后显示对应模型下拉
- 手动刷新后目录更新
- 本地服务不可达时显示错误态
- 已保存旧模型正确回显
- 设置总览、配置方案页、差异摘要同步展示新文案

## 实施约束

- 继续沿用现有 `useSettingsWorkspace` 自动保存机制
- 新增查询应与现有 `config`、`runtimeEnvironment`、`options` 分离
- 不把运行环境地址写回 `patchConfig`
- 所有 provider 文案继续走统一 helper，避免再次出现裸 key
