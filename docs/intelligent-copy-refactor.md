# 智能文案重构记录

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 当前问题

1. 已有成品封面时，系统仍然继续叠加标题字，直接破坏原封面设计。
2. 主题识别链路会把文件名、字幕前段、模型输出和 `_seed_profile_from_text` 的启发式结果混在一起，错误一旦进入 `content_profile`，会继续污染标题、简介、标签、搜索词和封面文案。
3. 标题生成此前过度依赖通用模型输出，没有把“视频到底在讲什么”锁死，导致主题跑偏、长度过短、平台语气不对。
4. 简介此前只是通用拼接，没有把视频摘要、重点信息和互动钩子明确组织起来。

## 已处理

1. 已有封面时只做尺寸适配，不再额外叠字。
2. `司令官2Ultra / 琢匠貔貅 / FAS刀帕` 已加专题化识别和文案分流。
3. 智能文案模式增加 transcript-driven `copy_brief`，会在平台打包后再次覆盖标题、简介和标签，避免沿用错误主题。
4. Windows 下 `codex exec` 改成走 stdin，修复长 prompt 直接失败的问题。
5. 专题规则已抽成 [src/roughcut/review/intelligent_copy_topics.py](E:/WorkSpace/RoughCut/src/roughcut/review/intelligent_copy_topics.py) 的注册表，后续扩展题材不需要再改多处分支。
6. 平台标题/简介句式已抽成 [src/roughcut/review/intelligent_copy_templates.py](E:/WorkSpace/RoughCut/src/roughcut/review/intelligent_copy_templates.py)，后续调平台语气不需要再改主流程。
7. 标题和简介增加本地规则评分器 [src/roughcut/review/intelligent_copy_scoring.py](E:/WorkSpace/RoughCut/src/roughcut/review/intelligent_copy_scoring.py)，优先筛掉主体不明确、信息量过低或带错词的文案。
8. 前置 `content_profile` 的 `source_context` 派生 hints 已接入题材注册表，前置摘要和智能文案开始共享一套专题识别能力。

## 下一步

1. 继续压缩 `content_profile` 的输入和超时策略，避免首段字幕噪声把主题带偏。
2. 增加更多专题规则和负面词过滤，优先覆盖现有 EDC 系列的真实选题。
3. 把 live 样例持续沉淀成回归测试，避免修一个坏一个。
