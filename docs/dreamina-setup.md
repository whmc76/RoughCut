# Dreamina Hybrid Adapter Setup

这份文档对应 RoughCut 当前已经接入的 `dreamina_web` 封面生图 backend。

当前实现已经把 Dreamina runner vendoring 到 RoughCut，本仓库可独立运行这套适配器。

当前结构是：

- RoughCut Python provider 负责现有封面生成链路、配置、调用、结果落盘
- RoughCut vendored Dreamina runner 负责 `HTTP replay + headless CDP page submit + history poll`
- Node bridge 负责 Python -> Node 模块调用

## 1. 当前接入形态

RoughCut 当前新增了 backend：

- `INTELLIGENT_COPY_COVER_IMAGE_BACKEND=dreamina_web`

调用路径：

- RoughCut Python provider：
  [image_generation.py](E:/WorkSpace/RoughCut/src/roughcut/providers/image_generation.py:1)
- Vendored Dreamina runner：
  [dreamina_web_cdp.mjs](E:/WorkSpace/RoughCut/scripts/dreamina_web_cdp.mjs:1)
- Node bridge：
  [dreamina_request_bridge.mjs](E:/WorkSpace/RoughCut/scripts/dreamina_request_bridge.mjs:1)

## 2. 必备前提

需要满足这几个前提，否则 `dreamina_web` 不会真正跑通：

1. 本机已安装 Node.js，并且 `node` 可执行
2. Chrome 可用，并能通过 CDP 调试
3. 有一份长期复用的即梦登录态 profile
4. 已准备一份成功的 `generate` 模板 JSON

## 3. 推荐目录与资产

建议固定三类路径：

1. 登录态 profile
   推荐：
   `C:\Users\Administrator\AppData\Local\HydraDreaminaCDPProfile`

2. headless profile
   推荐：
   `C:\Users\Administrator\AppData\Local\HydraDreaminaCDPProfileHeadless`

3. generate 模板
   推荐放在 RoughCut 工作区，例如：
   `E:\WorkSpace\RoughCut\data\runtime\dreamina\dreamina-generate-template.json`

4. submit state
   推荐：
   `E:\WorkSpace\RoughCut\data\runtime\dreamina\dreamina-submit-state.json`

## 4. 一次性准备顺序

严格按这个顺序做，最少踩坑：

1. 启动一个可见 Chrome，挂 CDP 端口，使用固定 profile
2. 手动登录即梦
3. 手动在页面里成功提交一单文生图
4. 用仓库内 Dreamina runner 抓一份成功模板
5. 把模板路径写进 RoughCut `.env`
6. 把 RoughCut backend 切到 `dreamina_web`
7. 先验证“参考图封面”链路，再考虑纯文本任务

## 5. 推荐环境变量

把这些变量写进 [`.env.example`](E:/WorkSpace/RoughCut/.env.example:1) 对应的实际 `.env`：

```env
INTELLIGENT_COPY_COVER_IMAGE_BACKEND=dreamina_web

# Dreamina runner
INTELLIGENT_COPY_COVER_DREAMINA_COMMAND=node
# 默认走仓库内 scripts/dreamina_web_cdp.mjs
# 只有你要覆盖 vendored runner 时才需要设置
INTELLIGENT_COPY_COVER_DREAMINA_RUNNER_SCRIPT=

# CDP
INTELLIGENT_COPY_COVER_DREAMINA_CDP_BASE_URL=http://127.0.0.1:9222
INTELLIGENT_COPY_COVER_DREAMINA_COOKIE_SOURCE_BASE_URL=http://127.0.0.1:9222
INTELLIGENT_COPY_COVER_DREAMINA_PAGE_URL=https://jimeng.jianying.com/ai-tool/generate/?type=image
INTELLIGENT_COPY_COVER_DREAMINA_PAGE_URL_PATTERN=jimeng.jianying.com/ai-tool/generate
INTELLIGENT_COPY_COVER_DREAMINA_USER_DATA_DIR=C:/Users/Administrator/AppData/Local/HydraDreaminaCDPProfile
INTELLIGENT_COPY_COVER_DREAMINA_HEADLESS_USER_DATA_DIR=C:/Users/Administrator/AppData/Local/HydraDreaminaCDPProfileHeadless
INTELLIGENT_COPY_COVER_DREAMINA_EXECUTABLE_PATH=

# Template / state
INTELLIGENT_COPY_COVER_DREAMINA_TEMPLATE_PATH=E:/WorkSpace/RoughCut/data/runtime/dreamina/dreamina-generate-template.json
INTELLIGENT_COPY_COVER_DREAMINA_SUBMIT_STATE_PATH=E:/WorkSpace/RoughCut/data/runtime/dreamina/dreamina-submit-state.json

# Runtime policy
INTELLIGENT_COPY_COVER_DREAMINA_HTTP_REPLAY_ENABLED=true
INTELLIGENT_COPY_COVER_DREAMINA_AUTO_LAUNCH=true
INTELLIGENT_COPY_COVER_DREAMINA_HEADLESS=true
INTELLIGENT_COPY_COVER_DREAMINA_KEEP_ALIVE=false
INTELLIGENT_COPY_COVER_DREAMINA_POLL_INTERVAL_MS=5000
INTELLIGENT_COPY_COVER_DREAMINA_POLL_TIMEOUT_MS=300000
INTELLIGENT_COPY_COVER_DREAMINA_SUBMIT_TIMEOUT_MS=60000
INTELLIGENT_COPY_COVER_DREAMINA_CAPTURE_TIMEOUT_MS=120000
INTELLIGENT_COPY_COVER_DREAMINA_MIN_SUBMIT_INTERVAL_MS=45000

# Model routing
# 文本任务默认 4.5；参考图默认 5.0
# 如果你明确指定，则不会依赖默认路由
INTELLIGENT_COPY_COVER_IMAGE_MODEL=5.0
INTELLIGENT_COPY_COVER_IMAGE_QUALITY=2k
INTELLIGENT_COPY_COVER_IMAGE_TIMEOUT_SEC=180
```

## 6. Chrome 启动建议

建议先手动启动一个可见 Chrome，用固定 profile 和 CDP 端口。

Windows 示例：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\Users\Administrator\AppData\Local\HydraDreaminaCDPProfile"
```

然后：

1. 打开即梦页面
2. 登录
3. 保持这个 profile 以后复用

## 7. 模板捕获建议

模板捕获可以直接使用 RoughCut 仓库内 vendored runner 完成。

目标是得到一份真实成功请求模板，保存到：

- `INTELLIGENT_COPY_COVER_DREAMINA_TEMPLATE_PATH`

最低要求：

1. 模板来自真实即梦页面提交
2. 模板对应的是文生图 generate 请求
3. 模板里的 cookie 不重要，运行时会从浏览器会话补
4. 模板结构必须能被 runner 识别为 text generate template

## 8. RoughCut 当前默认行为

当前 RoughCut 调这个 backend 时，传的是“参考图封面生成”请求，因此会带：

1. `prompt`
2. `prompt_base64`
3. `ratio`
4. `reference_images`

这意味着：

- 当前接入最适合复用你那套“参考图走 page submit”的稳定链路
- 默认会触发参考图路径，因此你外部 runner 大概率会走 `5.0`

## 9. 验证步骤

建议按三层验证。

### A. 配置层

确认这些值有效：

1. `INTELLIGENT_COPY_COVER_IMAGE_BACKEND=dreamina_web`
2. `INTELLIGENT_COPY_COVER_DREAMINA_RUNNER_SCRIPT` 指向真实文件
3. `INTELLIGENT_COPY_COVER_DREAMINA_TEMPLATE_PATH` 指向真实模板
4. Chrome CDP 端口可访问

### B. Runner 层

先单独确认仓库内 vendored runner 在这台机器能工作：

1. 能连接 CDP
2. 能读到已登录即梦页面
3. 能成功提交一单参考图任务
4. 能轮询拿回 4 张候选图

可以直接运行 smoke：

```powershell
node scripts/run_dreamina_smoke.mjs `
  --prompt "电影级产品封面，主体大，空间结构稳定，标题区留白明确" `
  --reference "E:/WorkSpace/RoughCut/frame_002.jpg" `
  --model 5.0 `
  --ratio 16:9
```

### C. RoughCut 集成层

再跑 RoughCut 现有测试：

```powershell
uv run pytest tests/test_config_profile_model_route_split.py tests/test_intelligent_copy_cover_generation.py -q
```

如果只是检查 bridge 语法：

```powershell
node --check scripts/dreamina_request_bridge.mjs
```

## 10. 常见故障定位

### 1. 报 `Dreamina runner script not found`

说明：

- `scripts/dreamina_web_cdp.mjs` 缺失
- 或你显式覆盖的 `INTELLIGENT_COPY_COVER_DREAMINA_RUNNER_SCRIPT` 路径写错

### 2. 报 `Dreamina runner failed`

说明第一坏层在 vendored Dreamina runner 或 Node bridge，不在封面业务逻辑。

优先检查：

1. runner 脚本是否能被 Node `import`
2. 是否真的导出了 `requestDreaminaWebImageGeneration`
3. `scripts/dreamina_web_cdp.mjs` 是否被误删或改坏

### 3. 报超时

优先判断是哪个边界超时：

1. CDP 连接超时
2. 页面 submit 超时
3. history poll 超时
4. RoughCut 外层等待超时

如果是正常慢任务，可先增大：

- `INTELLIGENT_COPY_COVER_IMAGE_TIMEOUT_SEC`
- `INTELLIGENT_COPY_COVER_DREAMINA_POLL_TIMEOUT_MS`
- `INTELLIGENT_COPY_COVER_DREAMINA_SUBMIT_TIMEOUT_MS`

### 4. 结果图 URL 返回了，但下载失败

当前 RoughCut 会直接下载最终选中的 URL。

优先检查：

1. URL 是否已过期
2. 是否需要即梦 Referer
3. 本机网络能否直连对应图床

## 11. 推荐上线顺序

对 RoughCut 来说，推荐这样落：

1. 先只在测试机把封面 backend 切到 `dreamina_web`
2. 只验证智能发布封面链路
3. 先跑低并发，避免 submit cooldown 撞车
4. 等单机稳定后，再考虑并发池和队列化

## 12. 后续可继续做的事

如果你要把这套进一步替代当前默认生图 provider，下一步最值得做的是：

1. 在前端配置页暴露 Dreamina 专用字段
2. 给封面物料页展示 `submit_id / transport / candidate_count`
3. 在 provider 层加入更清晰的错误分层：`cdp_connect_failed / submit_failed / poll_timeout / download_failed`
4. 增加模板捕获 CLI，直接落盘到 `INTELLIGENT_COPY_COVER_DREAMINA_TEMPLATE_PATH`
5. 评估是否把 `dreamina_web` 切成默认 provider
