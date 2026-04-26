# IMG_0024.MOV Luckykiss 审核报告

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 1. 已确认对象

- RoughCut `job_id`: `1c077801-edf4-4a2c-ba91-845b3ccc69eb`
- 原片文件：`\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\未剪辑视频\IMG_0024.MOV`
- 当前任务状态：`processing`
- 当前 active profile：`content_profile_final`

## 2. 原片证据

以下内容来自数据库中的 `transcript_segments` / `subtitle_items`，已经足够确认这不是工具钳视频：

- `13.12s - 15.52s`: `是LuckyKiss的1个。`
- `25.92s - 31.44s`: `益生菌含片这个产品它叫。 KissPod。`
- `117.36s - 119.76s`: `我在我的理解是1个EDC小零食。`
- `200.45s - 203.17s`: `这个含片含片直接给它放进去。`
- `240.21s - 242.21s`: `口气清新的能力还是相当不错。`
- `330.45s - 333.89s`: `弹射到嘴里这个是相当酷的1个连招儿。`
- `408.79s - 410.39s`: `1个是三百亿的这个益生菌。`
- `428.07s - 429.19s`: `另外它是这个零糖。`

## 3. 当前 RoughCut 误判点

当前 `content_profile` 摘要为：

- `subject_type`: `多功能工具钳`
- `summary`: `这条视频主要围绕多功能工具钳展开...`
- `cover_title.main`: `高价工具钳开箱`

这个结果和原片证据冲突，问题已经明确：

- 视频真实主体是 `Luckykiss / KissPod 益生菌含片`
- 视频包装风格是 `EDC / 战术 / 弹夹仓` 叙事
- RoughCut 把“包装风格”错当成了“产品主体”

## 4. 审核链路现状

当前数据库里这条任务已经完成到人工确认摘要阶段：

- 已完成：
  - `probe`
  - `extract_audio`
  - `transcribe`
  - `subtitle_postprocess`
  - `subtitle_translation`
  - `content_profile`
  - `summary_review`
  - `glossary_review`
- 未完成：
  - `final_review`
  - `edit_plan`
  - `platform_package`
  - `render`

产物现状：

- 已有：
  - `media_meta`
  - `audio_wav`
  - `transcript`
  - `content_profile`
  - `content_profile_draft`
  - `content_profile_final`
- 缺失：
  - `timeline`
  - `render_outputs`

结论：`初步摘要纠偏审核` 已落地，但 `中审 / 终审 / 成片输出` 仍未开始。

## 5. 已发现的风险

- 主体识别错误：食品/含片被误识别为装备/工具钳。
- 术语环境污染：当前通道记忆中带有 `edc_tactical` 品牌锚点，容易把视觉风格误带入主体分类。
- 健康表述风险：视频里出现 `三百亿益生菌`、`口气清新`、`调节菌群`，必须严格限制为包装或口播层面的事实，不能升级成医学结论。
- 文案一致性风险：视频中同时出现 `LuckyKiss`、`KissPod`，公开页面又常见 `KISSPORT / 益倍萃`，最终成片必须以实物主包装为准统一命名。

## 6. 建议立即执行的修正

1. 重做这条任务的 `content_profile` 人工确认：
   - `subject_type` 改为 `益生菌含片 / 弹射含片`
   - 不再使用 `工具钳 / 多功能装备` 作为主体
2. 进入 `summary_review` 前，先锁定命名规范：
   - 包装主品牌
   - 产品全称
   - 是否使用 `KissPod` 作为产品名
3. 对以下表述加风险标记：
   - `300亿益生菌`
   - `口气清新`
   - `调节菌群`
   - `零糖`
4. 如果继续产出成片，封面方向应改成：
   - `EDC 风格益生菌含片开箱`
   - 而不是 `高价工具钳开箱`

以上第 1 项已完成，当前 final profile 关键字段为：

- `subject_brand`: `LuckyKiss`
- `subject_model`: `KissPod`
- `subject_type`: `弹射益生菌含片`
- `video_theme`: `EDC 风格弹射益生菌含片开箱与实用体验`

## 7. 本次落地资产

- 审核方案：`docs/2026-03-23-luckykiss-audit-plan.md`
- 目标检索脚本：`scripts/find_video_by_keywords.py`
- 数据库快照脚本：`scripts/export_job_audit_snapshot.py`
- 人工确认脚本：`scripts/manual_confirm_content_profile.py`
- 人工确认 payload：`docs/2026-03-23-luckykiss-content-profile-confirm.json`
