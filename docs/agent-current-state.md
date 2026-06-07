# Agent Current State

This file is the source of truth for the current active task state across long Codex sessions. Update it when the active objective, blockers, or "do not reopen" decisions change.

## Current Objective

Close the Bilibili production live-publication chain on a clean new-video flow, then finish Douyin fresh-start publication closeout in linear execution mode before moving on to the next platforms.

## Current Workstream

- Keep Bilibili findings and current live-runtime facts in dedicated publication state docs instead of chat memory.
- Close Bilibili source-of-truth, mainline packaging, browser-agent transport, and clean new-flow publication contracts.
- Reuse the same shared framework on the next platforms one by one, starting from real probe/preflight evidence rather than speculative abstraction.
- Treat only the publication browser-agent bound to the browser/profile declared by the task's creator card as authoritative runtime for publication work. Edge, in-app browser, and direct Codex Chrome-tab probing are invalid for publication evidence.
- Refactor publication work to a minimal fresh-start contract: each platform gets a new authoritative upload-shell tab, upload is always first, and shared draft/recovery/reroute logic must not preempt platform executors.

## Open Work

- Finish Bilibili remaining execution-layer closeout: cover editor final confirmation evidence and full post-upload publish path.
- Start the next real platform probes from the current Chrome session and identify the first shared bad layer for Douyin/Xiaohongshu without reopening already-closed Bilibili blockers.
- Finish Douyin fresh-start closeout from `https://creator.douyin.com/creator-micro/content/upload`.
- Keep fresh-start linear execution mode: new tab -> upload first -> execute platform-local editor steps once, without shared auto-repair re-entry.
- Re-verify Douyin on the authoritative browser runtime after the bridge re-attaches `attached_profile_binding`; current code-side linear-mode changes are in place, but the post-restart runtime has not yet rebound the Chrome profile.

## Resolved Decisions

- `AGENTS.md` must stay generic; active publication contracts live in `docs/publication-agent-ledger.md`.
- Bilibili standard publish flow is defined as a clean new-video flow, not editor reuse; stale draft/editor handling remains a shared publication concern.
- Preview publication copy must be promoted into production `smart-copy` source-of-truth before any live publish test.
- Bilibili cover source-of-truth now treats `4:3 首页推荐封面` and `16:9 个人空间封面` as separate slots; do not collapse them back into a single-cover contract.
- Publication browser authority is task-bound, not global: `publication-browser-agent -> bridge://chrome-extension -> browser/profile resolved from the task's creator card`. For the current FAS runs, that resolves to `Google Chrome / Profile 2 / browser-profile:chrome:21104fd69d72ad7267c2`. Any probe or live result gathered from Edge, in-app Browser, or direct Codex Chrome tab control is invalid for platform conclusions.
- Publication refactor direction is now explicit: the standard publish test path for all platforms is fresh-start linear mode. Each platform must open a new authoritative upload-shell tab, upload first, then enter the platform-local editor chain. Shared draft resume/discard handling, route “correction”, duplicate-attempt dedupe, and other generic recovery logic must not block or reroute that flow.
- Fresh-draft release-gate runs no longer use `prepare_only_current_page`; they use `fresh_start_platform_tab` only. Platform-local editor steps must run once in order and fail closed instead of replaying `body/tags` writes.

## Do Not Reopen

- Do not move current platform publication facts back into `AGENTS.md`.
- Do not treat old artifacts or compacted chat history as current task state when a publication state file exists.
- Do not regress Bilibili cover handling to a single `16:9` primary-cover contract.
- Do not treat Bilibili stop-before runs as permission to reuse stale editor pages by default.
- Do not use direct Codex browser plugins to open or probe publication pages as evidence for platform contracts. Publication evidence must come from the bound browser-agent runtime only.

## Next Concrete Action

1. Keep Bilibili conclusions current in `docs/publication-agent-ledger.md`.
2. Keep new-platform work inside the authoritative `publication-browser-agent -> creator-card-bound Chrome runtime` only.
3. For each new platform, identify the first shared bad layer before editing platform-local flow code.

## Verification

- Confirm Bilibili live publish payloads read promoted production copy and the normalized dual-cover contract.
- Confirm platform-specific current facts remain available through dedicated publication state docs.
- Confirm the next platform probes are driven from current runtime/browser evidence, not stale artifacts.
