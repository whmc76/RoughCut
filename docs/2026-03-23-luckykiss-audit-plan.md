# Luckykiss / Kissport 弹射益生菌含片审核计划

## 1. 当前定位结论

- 当前已在 RoughCut PostgreSQL 作业库中锁定目标任务：
  - `job_id`: `1c077801-edf4-4a2c-ba91-845b3ccc69eb`
  - `source_name`: `IMG_0024.MOV`
  - 数据库状态：`processing`
  - 共享盘原片：`\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\未剪辑视频\IMG_0024.MOV`
- 当前 `E:\WorkSpace\RoughCut\output` 内仍未发现该任务的完整成片输出。
- 已排查共享盘 `\\Z4pro-gwil\团队文件-媒体工作台` 中：
  - `EDC系列\未剪辑视频`
  - `EDC系列\AI粗剪`
  - `相机文件备份\DJInano`
  - `相机文件备份\insta360go3s`
- 其中 `相机文件备份` 的多段候选原片已抽取前 30 秒口播转写，暂未出现目标产品命中；真正命中的原片位于 `EDC系列\未剪辑视频\IMG_0024.MOV`。
- PostgreSQL 链路已恢复，本地 `.env` 已对齐容器端口 `25432`，现在可以直接读取 RoughCut 的 `jobs / artifacts / transcript / subtitle_items` 记录。
- 已确认该任务的 transcript/subtitle 明确出现：
  - `LuckyKiss`
  - `益生菌含片`
  - `KissPod`
  - `三百亿益生菌`
  - `口气清新`
  - `零糖`
- 当前主要审核问题不是“找不到片”，而是“找到了片，但内容画像错了”：
  - 现有 `content_profile` 将该视频误判为 `多功能工具钳开箱`
  - 这与 transcript 中的含片/食品主体证据冲突，属于需要人工纠偏的摘要错误
- 该摘要错误已完成一次人工确认写回：
  - `content_profile_final` 已生成
  - `summary_review` 已完成
  - 当前 active profile 已修正为 `LuckyKiss / KissPod / 弹射益生菌含片`

## 2. 产品事实基线

以下为当前能从公开页面交叉得到的“可核对事实”。其中部分为电商/礼品站营销文案，使用时必须降级为“页面宣传信息”，不能直接写成医学结论。

### 高可信基线

- 产品在公开页面上通常以 `KISSPORT 益倍萃 弹射益生菌含片` 呈现。
- 市场上同时出现 `Luckykiss` 与 `Kissport` 两套命名，推断是同体系或关联 SKU，但在未看到实物包装前，不能直接断言完全等同。
- 该品类被描述为 `无糖/0糖`、`弹射/子弹仓造型`、`益生菌含片/薄荷糖`。
- 多个公开销售页提到 `300亿益生菌` 与 `清新口气 / 口腔健康` 方向卖点。

### 中可信基线

- 礼品站页面宣称口味为：
  - 海盐青柠
  - 海盐西柚
  - 爆汁蜜桃
  - 沁爽葡萄
  - 甜心草莓
- 礼品站页面提到菌株 `GMNL-143`，但需要谨慎：
  - 可以写成“页面宣称含 GMNL-143”
  - 不能直接写成“本产品临床证实有效”
- 临床注册/论文公开信息显示，`GMNL-143` 与口腔病原菌共聚集、牙龈炎改善研究相关，但对象并非该商品本身，且常见于牙膏/口腔产品研究。

### 待实物确认项

- 包装正面品牌最终写法：`Luckykiss` 还是 `KISSPORT`
- 单盒/单仓规格与颗粒数
- 配料表与营养成分表
- 是否明确标注“0蔗糖”“无糖”还是“0含糖量”
- 菌株与添加量的准确标识方式
- 执行标准、生产许可证、委托/受托生产企业信息

## 3. 容易出错的内容红线

- 不要把“清新口气”升级表述成“治疗口臭”“修复牙龈炎”。
- 不要把电商宣传里的 `300亿益生菌`、`专利菌株`、`抑菌` 当成未经核验的硬结论。
- 不要混写 `Luckykiss`、`Kissport`、`益倍萃`，必须以实物包装主标为准。
- 不要把“益生菌含片”和“口香糖/薄荷糖”完全等同，应按包装品名优先。
- 如果视频里提到“儿童/孕妇/长期服用适用”等人群结论，必须有包装或官方说明支撑。

## 4. 找片与审核落地步骤

### A. 先定位目标原片

1. 用 `scripts/find_video_by_keywords.py` 扫共享盘原片前 30-45 秒口播。
2. 优先关键词：
   - `luckykiss`
   - `kissport`
   - `益倍萃`
   - `含片`
   - `益生菌`
   - `弹射`
   - `薄荷糖`
3. 如果口播无命中，再按关键帧人工看包装正面。

推荐命令：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\find_video_by_keywords.py `
  "\\\\Z4pro-gwil\\团队文件-媒体工作台\\EDC系列\\未剪辑视频" `
  "\\\\Z4pro-gwil\\团队文件-媒体工作台\\相机文件备份" `
  --keywords luckykiss kissport 益倍萃 含片 益生菌 弹射 薄荷糖 `
  --sample-seconds 30 `
  --model base `
  --min-score 1
```

### B. 找到原片后立即补齐三份 RoughCut 产物

1. 初步摘要：
  - `content_profile_draft`
  - `content_profile`
  - `content_profile_final`
2. 中期审核：
   - `summary_review`
   - `glossary_review`
   - `quality_assessment`
3. 最终成品：
  - 成片 `mp4`
  - 字幕 `srt`
  - `publish.md`
  - 封面与平台包装文案

当前这条 `IMG_0024.MOV` 的真实状态：

- 已有：
  - `media_meta`
  - `audio_wav`
  - `transcript`
  - `content_profile`
  - `content_profile_draft`
  - `content_profile_final`
- 已完成：
  - `summary_review`
- 未有：
  - `final_review`
  - `timeline`
  - `render_outputs`

因此当前能做的是“原片 + 转写 + 初步摘要”的交叉审核，不能伪装成已经完成了中审或终审。

### C. 交叉核对矩阵

每条结论都要落到下表之一：

- 包装可见事实
- 原片口播事实
- RoughCut 摘要事实
- 中期审核修订事实
- 成片最终表述
- 公开来源事实

建议重点核对字段：

- 品牌名
- 产品全称
- 品类归属
- 核心卖点
- 菌株/菌数
- 口味
- 规格
- 功效表述
- 人群适用
- 价格与性价比结论

## 5. 当前已落地的辅助能力

- 已新增 `scripts/find_video_by_keywords.py`
  - 用本地 `faster-whisper` 扫原片开头音频
  - 对关键词进行打分排序
  - 输出 JSON 排名与逐条转写工件
- 已新增 `scripts/export_job_audit_snapshot.py`
  - 直接从 RoughCut PostgreSQL 导出单条 job 的步骤状态、artifact 摘要、转写关键词命中、字幕纠错和审核缺口
  - 可用于把 `初步摘要 / 中期审核 / 最终产物` 的缺失项一次性拉清楚
- 已新增 `scripts/manual_confirm_content_profile.py`
  - 可把人工确认 payload 正式写回为 `content_profile_final`
  - 同步完成 `summary_review`、记录 manual review 统计、回写内容画像记忆
- 已新增确认 payload：
  - `docs/2026-03-23-luckykiss-content-profile-confirm.json`
- 已给 `content_profile` 自动审核补充主体冲突预警
  - 当字幕明显出现 `含片 / 益生菌 / LuckyKiss / KissPod / 口气 / 零糖` 等入口产品信号
  - 而摘要主体仍落在 `工具钳 / 战术笔 / 弹夹 / 装备` 等品类时
  - 自动加入 blocking reason，强制进入人工复核
- 当前临时排查工件位于：
  - `output/audit_frames`
  - `output/audit_transcripts`

## 6. 外部来源

- `KISSPORT` 销售页摘要：提到 `300亿益生菌`、`0含糖量`、`子弹仓造型`
- `YY创意礼品网` 页面：提到 `KISSPORT益倍萃弹射益生菌含片`、`GMNL-143`、五种口味
- `格瑞食品(中山)有限公司` 产品展示页：出现 `Luckykiss` 与 `Kissport` 清凉含片/薄荷糖 SKU
- `ClinicalTrials.gov / PMC`：能证明 `GMNL-143` 与口腔健康研究相关，但不是该商品的直接功效背书

## 7. 当前阻塞

- “找片”与“初步摘要纠偏”两个阻塞已经解除。
- 当前剩余阻塞是：
  - `final_review` 尚未开始
  - `render` 尚未开始
  - `platform_package` 尚未开始
  - 当前通道记忆仍然强偏 `edc_tactical`，后续同类视频仍需观察是否会再次吸偏
- 现阶段可以继续往后推进，但必须以 `content_profile_final` 为唯一有效摘要来源，不能再回退使用旧的工具钳摘要。
