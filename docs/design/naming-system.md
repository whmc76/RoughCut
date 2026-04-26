# RoughCut 命名体系

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 目标

RoughCut 的命名分三层：

- 能力名：描述业务能力，例如 `avatar_generation`、`voice_clone`、`reasoning`。
- 实现名：描述可替换 provider 或本地服务，例如 `openai`、`heygem`、`indextts2`。
- 配置名：描述可持久化设置，例如 `reasoning_provider`、`voice_provider`。

能力名不能绑定具体项目、模型或 provider。实现名只允许出现在 provider 选择、凭证、运行时探测和实现模块内。

## 规则

- 公共 API 字段使用能力名或配置名，不使用某个实现名作为业务状态键。
- provider 值、agent backend 值、auth mode 值统一从 `roughcut.naming` 读取。
- 新增 provider 时先登记到 `roughcut.naming`，再接入配置、选项和运行时探测。
- 新增模型只作为配置值或 provider catalog 结果出现，不写进能力名、接口名或页面状态键。
- 项目未发布前不保留旧字段和旧值；发现历史命名时直接迁移到当前规范名。

## 当前规范名

- Auth mode: `api_key`、`helper`
- Avatar capability: `avatar_generation`、`voice_clone`、`portrait_reference`、`preview`
- Coding backend: `codex`、`claude`
- Transcription provider: `local_http_asr`、`openai`、`funasr`、`faster_whisper`
- Reasoning provider: `openai`、`anthropic`、`minimax`、`ollama`
