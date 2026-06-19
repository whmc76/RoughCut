# Bluey Parenting Remix Full-Chain Test Plan

**Date:** 2026-06-17  
**Source folder:** `F:\布鲁伊育儿节目`  
**Objective:** 使用第二季育儿文案和对应原片，构建三集 2-3 分钟完整二创样片，并验证 RoughCut 从素材接入到成片/报告的端到端能力。

## Scope

本轮选取第二季前三集：

- S02E01《跳舞模式》：孩子说“好吧”，到底是不是真的愿意？
- S02E02《仓储超市》：孩子总想要别人手里的东西，是不是太贪心？
- S02E03《羽毛魔杖》：孩子被排除在外时，只说“没关系”真的够吗？

只选第二季是因为当前文案只覆盖第二季 1-52 集，第三季只有原片没有对应文案。

## Test Layers

### A. RoughCut 原生全链路

目的：验证当前系统真实任务链路是否能吃进这批动画原片，并完成 `probe -> extract_audio -> transcribe -> subtitle_postprocess -> glossary_review -> subtitle_translation -> content_profile -> summary_review -> ai_director -> avatar_commentary -> edit_plan -> render`。

命令形态：

```powershell
uv run python scripts/run_fullchain_batch.py `
  --source-dir E:\WorkSpace\RoughCut\.tmp\bluey-fullchain-input `
  --limit 3 `
  --channel-profile commentary_focus `
  --language zh-CN `
  --stop-after render `
  --output-dir E:\WorkSpace\RoughCut\output\bluey-remix-fullchain-renders `
  --report-dir E:\WorkSpace\RoughCut\output\test\bluey-remix-fullchain `
  --force-rerun-existing
```

验收：

- 三个任务至少跑到 `render` 或输出明确失败阶段。
- `batch_report.json` 和 `batch_report.md` 落盘。
- 报告记录字幕数量、剪辑保留比例、质量评分、失败原因和渲染诊断。

### B. 文案驱动二创样片链路

目的：验证“成稿文案 + 对应集数原片”能构建实际二创样片。

命令形态：

```powershell
uv run python scripts/build_script_footage_remix_samples.py `
  --source-root F:\布鲁伊育儿节目 `
  --episodes 1,2,3 `
  --output-dir E:\WorkSpace\RoughCut\output\bluey-remix-samples `
  --tts-provider moss_tts_local `
  --tts-mode moss_voice_clone `
  --reference-history-path /app/data/tools/reference-uploads/读绘本试音-2.mp3 `
  --tts-target-duration-sec 120 `
  --final-target-duration-sec 180 `
  --force
```

处理逻辑：

- 解析每集育儿口播文案。
- 将原始 4-5 分钟长文案压缩为约 780 字样片稿，保留开场痛点、剧情证据、原因拆解、可执行话术和结尾升华；实测 MOSS voice clone 约落在 3 分钟附近。
- 调用 RoughCut 工具 API 的 MOSS TTS 生成旁白音轨；默认复用百宝箱历史参考音频 `读绘本试音-2.mp3` 的 `moss_voice_clone` 配置，可切换 `--tts-provider cosyvoice3` 做对照。
- 从对应原片按时长均匀抽取多个镜头，作为观点解说画面证据。
- 原片音频不进入成片，避免把原作片段作为主体观看体验。
- 按文案字数权重生成 ASS 字幕并烧录。
- 输出 1280x720 H.264/AAC MP4 和 `script_footage_remix_sample_report.md/json`。

验收：

- 每集输出一个可播放 MP4。
- 每集输出时长目标为 120-180 秒。
- 每集有独立旁白 WAV、字幕 ASS、片段 montage 和最终成片。
- 报告记录脚本字数、旁白时长、原片时长、抽取镜头数、输出时长和合规备注。

## Quality Gates

### Content Gate

- 文案必须对应同集原片。
- 开头必须保留育儿问题和家长真实场景。
- 成片主体必须是新旁白/字幕结构，而不是原片顺序搬运。

### Technical Gate

- ffprobe 能读取输出时长。
- 输出视频编码为 H.264，音频为 AAC 或可播放 WAV 混入 AAC。
- 字幕烧录可见，中文不乱码。
- 输出时长与旁白时长基本一致。

### Remix / Compliance Gate

- 原片音频默认不保留。
- 不连续搬运完整原片段落。
- 报告必须标出“正式发布前需确认授权和平台规则”。
- 样片用于内部能力测试，不直接作为公开发布成片。

## Report Deliverables

- `output/bluey-remix-samples/script_footage_remix_sample_report.md`
- `output/bluey-remix-samples/script_footage_remix_sample_report.json`
- `output/test/bluey-remix-fullchain*/batch_report.md`
- `output/test/bluey-remix-fullchain*/batch_report.json`
- 三个最终样片 MP4

## Known Risks

- TTS 长文本生成可能耗时较长；失败时可用 `--skip-tts` 生成无声技术样片，但不能视为完整口播样片。
- 如果 TTS 生成音频超过最终目标时长，样片构建会按 `--final-target-duration-sec` 控制最终 mux 时长；正式生产建议优先做句段级二次压缩，而不是依赖硬截尾。
- RoughCut 原生全链路仍偏“原视频自动剪辑”，不会天然使用外部成稿文案作为旁白脚本；因此本轮拆分为系统全链路和文案驱动样片链路两层验证。
- 原片版权/授权状态未知，正式发布必须补授权或平台活动规则确认。


