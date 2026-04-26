# RoughCut 审核框架设计

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 目标

把 RoughCut 的人工审核从“单条 case 临时排查”升级为“可复用的通用框架”，让任何 job 都能按同一套流程完成：

1. 定位原片
2. 导出数据库快照
3. 识别主体冲突与审核阻塞
4. 生成标准审核包
5. 执行人工确认并写回 `content_profile_final`
6. 继续推进 `render / final_review / platform_package`

## 核心原则

- 主体判断优先级：包装视觉风格不能压过字幕和口播中的真实产品主体。
- 审核结果必须可落库：不能只停留在文档备注，必须能回写到 RoughCut 的 artifact / step 状态。
- 审核过程必须可复用：同一能力应适用于 Luckykiss，也适用于后续其他 job。
- 风险表述分层：原片口播、包装可见事实、公开页面营销卖点、医学或功能结论必须分层管理。

## 框架产物

### 1. 定位层

- `scripts/find_video_by_keywords.py`
- 用于从共享盘或原片目录批量找出候选视频

### 2. 快照层

- `scripts/export_job_audit_snapshot.py`
- 用于导出单条 job 的：
  - step 状态
  - artifact 摘要
  - transcript / subtitle 命中
  - 启发式阻塞项

### 3. 审核包层

- `scripts/build_job_audit_pack.py`
- 用于把 job 快照渲染成统一 Markdown 审核包

### 4. 人工确认层

- `scripts/manual_confirm_content_profile.py`
- 用于把人工确认 payload 正式写回：
  - `content_profile_final`
  - `summary_review`
  - content profile review stats
  - content profile memory

### 5. 自动防线层

- `src/roughcut/review/content_profile.py`
  - 增加“字幕主体与摘要主体冲突” blocking reason
- `src/roughcut/pipeline/quality.py`
  - 增加 `subject_conflict` 质量问题

## 通用执行流程

### A. 快速定位

1. 用关键词扫共享盘原片
2. 锁定 `job_id / source_name / source_path`

### B. 导出审核快照

1. 跑 `export_job_audit_snapshot.py`
2. 查看 active profile、issues、缺失 step

### C. 生成审核包

1. 跑 `build_job_audit_pack.py`
2. 形成统一审片资料

### D. 人工确认

1. 准备确认 payload
2. 跑 `manual_confirm_content_profile.py`
3. 写回 `content_profile_final`

### E. 继续成片链路

1. 基于 `content_profile_final` 继续 `edit_plan / render / final_review / platform_package`
2. 禁止回退使用旧的 draft / 错误 summary

## 当前已验证的通用能力

- 入口产品被误识别成装备/工具类时会被自动拦截
- 任意 job 可导出快照 JSON
- 任意 job 可生成 Markdown 审核包
- 任意 job 可通过确认 payload 正式完成 `summary_review`

## 当前局限

- `final_review` 与 `render` 仍需要后续生产链条继续推进
- 命名冲突、营销页卖点与实物包装不一致时，仍需人工确认
- 当前审核包主要围绕 `content_profile` 与摘要纠偏，尚未自动生成成片级镜头审核报告
