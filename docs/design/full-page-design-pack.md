# RoughCut Full Page Design Pack

This pack fills the missing page-level design drafts for every current frontend
route. Each PNG is generated from `page-design-board.html` at 1440 by 900.

Use this pack together with `page-responsibility-matrix.md` before implementing
or reviewing page changes. The matrix defines what the page owns. The PNG shows
the first-screen layout and required task affordances.

## Primary Navigation

| Page | Route | Design draft | Required task coverage |
| --- | --- | --- | --- |
| 总览 | `/` | ![Overview](./assets/page-design-overview.png) | System status, queue pressure, automation roots, service risk, recent activity. |
| 制片队列 | `/jobs` | ![Jobs](./assets/page-design-jobs.png) | Create/import jobs, production lanes, recovery, queue table, handoff to final review. |
| 成片审看 | `/final-review` | ![Final review](./assets/page-design-final-review.png) | Select final video, switch versions, complete audience checklist, approve or return. |
| 发布跟踪 | `/publication-tracking` | ![Publication tracking](./assets/page-design-publication-tracking.png) | Select video/material task, copy materials, open platform publish page, backfill URL and receipt. |
| 创作者卡片 | `/creator-cards` | ![Creator cards](./assets/page-design-creator-cards.png) | Identity, platform accounts, assets, preferences, default relationships. |
| 任务策略 | `/task-strategies` | ![Task strategies](./assets/page-design-task-strategies.png) | Generate, compare, activate strategies, set review gates. |
| 视觉方案 | `/visual-plans` | ![Visual plans](./assets/page-design-visual-plans.png) | Cover, subtitles, packaging, enhancement, platform adaptation. |
| 术语与记忆 | `/terms-memory` | ![Terms memory](./assets/page-design-terms-memory.png) | Glossary, memory, hotwords, correction feedback. |
| 工具箱 | `/tools` | ![Tools](./assets/page-design-tools.png) | Tool entry, service status, last run, diagnostics. |
| 系统设置 | `/settings` | ![Settings](./assets/page-design-settings.png) | Model routing, quality thresholds, runtime, notifications, related system pages. |
| 服务控制 | `/control` | ![Control](./assets/page-design-control.png) | Health, compensation queue, diagnostics, maintenance and shutdown. |

## Compatibility And Sub Routes

| Page | Route | Design draft | Required task coverage |
| --- | --- | --- | --- |
| 智能发布旧页 | `/intelligent-copy` | ![Intelligent copy](./assets/page-design-intelligent-copy.png) | Generate platform materials and continue to publication tracking. |
| 发布配置 | `/publication-management` | ![Publication management](./assets/page-design-publication-management.png) | Platform account binding, login checks, material rules. |
| 自动任务 | `/watch-roots` | ![Watch roots](./assets/page-design-watch-roots.png) | Watch roots, pending files, rule matching, enqueue. |
| TTS | `/tools/tts` | ![TTS](./assets/page-design-tools-tts.png) | Provider/mode, reference input, text input, audio result and logs. |
| ASR | `/tools/asr` | ![ASR](./assets/page-design-tools-asr.png) | Audio input, hotwords, transcript result and logs. |
| 数字人 | `/tools/avatar` | ![Avatar](./assets/page-design-tools-avatar.png) | Source video/audio input, preview result and logs. |
| 手工编辑器 | `/jobs/:jobId/manual-editor` | ![Manual editor](./assets/page-design-manual-editor.png) | Job-local script, materials, timeline, readiness, export to queue. |

## Publication Tracking Rule

The publication tracking page must never be a passive status page. It must
always expose the semi-manual publishing work:

1. Select a finished video/material task.
2. Show the generated platform materials.
3. Provide copy actions for title, body, tags, and cover path.
4. Provide platform publish-page entry buttons.
5. Accept public video URL, receipt ID, and optional post ID backfill.
6. Show history and final URL/receipt state after backfill.
