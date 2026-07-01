# RoughCut Page Responsibility Matrix

This matrix defines the page-level design contract for the full frontend
redesign. It is intentionally task-first: every page must expose the work it
owns, the evidence an operator needs, and the action that completes that work.

## Design Language

- Product surface: RoughCut Operator Console.
- Tone: dense, direct, workflow-led.
- Layout primitives: left rail, status strip, split workspace, table/list,
  inspector, drawer/modal.
- Primary accent: teal.
- Semantic status only: green, amber, red.
- Avoid decorative dashboard mosaics. Use cards only when the card is the
  interaction.

## Primary Pages

| Page | Route | Actual responsibility | Required primary actions | Must show by default | Non-goals |
| --- | --- | --- | --- | --- | --- |
| 总览 | `/` | System overview and cross-workflow attention. | Jump to queue, review, automation, tools, or service risk. | Active queue pressure, waiting review, failed jobs, automation roots, service health, recent activity. | Editing content, final approval, publishing forms, publication execution. |
| 制片队列 | `/jobs` | Import, queue, run, recover, rerun, and hand off finished output. | Create job, start/retry/cancel, open folder, download, open manual editor, send finished output to review. | Production lanes, blocked jobs, complete candidates, filters, queue table, job operations. | Final audience acceptance, platform publishing, creator account configuration. |
| 成片审看 | `/final-review` | Watch final publishable video and decide pass or return. | Select candidate, switch final video version, complete checklist, approve to publication, return to queue. | Real video or clear unavailable state, candidate queue, version tabs, audience checklist, decision note. | Automated quality scoring, platform publishing, content editing. |
| 发布跟踪 | `/publication-tracking` | Semi-manual publication handoff and result tracking. | Select video/material task, copy platform material, open platform publish page, backfill public URL and receipt. | Video/material selection, generated material readiness, platform rows, publish-page buttons, copy buttons, backfill form, history. | Creator account setup as the main job, pretending to publish without a manual platform step. |
| 创作者卡片 | `/creator-cards` | Manage creator identity, accounts, assets, preferences, and default relationships. | Create/update creator, bind platforms, upload assets, set default strategy and visual plan. | Creator rail, identity fields, platform bindings, asset library, relationship summary. | Publishing execution, queue operations. |
| 任务策略 | `/task-strategies` | Generate, compare, activate, and govern task strategies. | Choose creator, generate strategies, compare candidates, activate one, set review gate. | Strategy candidates, score/fit signals, applicable task types, activation state, gate rules. | Visual packaging, publishing execution. |
| 视觉方案 | `/visual-plans` | Define packaging, subtitles, cover direction, enhancement, and platform adaptation. | Choose creator, generate visual plan, preview packaging rules, activate plan. | Cover/subtitle/packaging constraints, platform adaptations, preview lanes, active plan. | Publishing execution, task queue operations. |
| 术语与记忆 | `/terms-memory` | Maintain glossary, learned memory, hotwords, and correction feedback. | Add glossary entry, import built-ins, approve/ignore correction, tune hotwords. | Tabs for glossary/memory/hotwords/corrections, recent changes, conflict warnings. | Production control, publishing decisions. |
| 工具箱 | `/tools` | Diagnose ASR, TTS, avatar services and run single-purpose tests. | Open tool, run diagnostic, inspect service state. | Tool entry list, service status, last run, direct links to TTS/ASR/avatar. | Main workflow execution. |
| 系统设置 | `/settings` | Configure model routing, quality thresholds, runtime, notifications, and integrations. | Save/reset settings, inspect active routing, open related system pages. | Summary cards, grouped setting panels, autosave state, validation hints. | Task execution, live service shutdown. |
| 服务控制 | `/control` | Monitor service health, compensation queues, diagnostics, and shutdown. | Refresh status, requeue/drop notifications, inspect health, enter maintenance/shutdown. | Service grid, readiness checks, compensation queue, managed services, maintenance control. | Content decisions, publishing decisions. |

## Compatibility And Sub Pages

| Page | Route | Actual responsibility | Required primary actions | Must show by default | Boundary |
| --- | --- | --- | --- | --- | --- |
| 智能发布旧页 | `/intelligent-copy` | Compatibility page for material generation and old publication flows. | Select local output folder, generate platform material, preview copy, continue to publication tracking. | Folder input, style options, platform material preview, generated material task history. | New publication execution belongs to `/publication-tracking`. |
| 发布配置 | `/publication-management` | Configure creator publication profiles and platform account bindings. | Select creator, bind account, test login, edit platform rules. | Creator picker, account state, platform requirements, login modal entry. | Does not publish content. |
| 自动任务 | `/watch-roots` | Inspect watched roots and enqueue automated tasks. | Select root, review pending files, enqueue or refresh. | Directory list, pending items, auto-cut readiness, enqueue entry points. | Does not edit finished videos or publish. |
| TTS | `/tools/tts` | Generate and test speech from text and reference audio. | Pick provider/mode, upload reference, run generation, preview/download audio. | Provider state, input controls, reference history, result panel. | Not a production queue. |
| ASR | `/tools/asr` | Transcribe audio and inspect segments/hotwords. | Upload audio, run transcription, copy/export text. | Hotword context, input upload, transcript, segments, errors. | Not glossary maintenance. |
| 数字人 | `/tools/avatar` | Test avatar preview from video/audio materials. | Upload source video/audio, run preview, inspect output. | Service state, material upload, result preview. | Not full production publishing. |
| 手工编辑器 | `/jobs/:jobId/manual-editor` | Manually assist a specific job with timeline, script, materials, and export readiness. | Adjust script/materials, preview timeline, save, export/return to queue. | Job context, timeline, script blocks, asset bins, readiness checks. | Global queue management and publication tracking. |

## Missing Design Pack

The full design pack is generated from `docs/design/page-design-board.html`.
Each frame is 1440 by 900 and is exported to `docs/design/assets/page-design-*.png`.

Existing visual references remain useful, but this pack is the source of truth
for page responsibility coverage across all current routes.
