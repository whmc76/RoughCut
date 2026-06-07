# Publication Agent Ledger

This ledger is the source of truth for long publication sessions. Read it before touching browser state or running platform automation.

## Global Rules

- One platform has one current open blocker.
- Resolved blockers stay closed unless fresh live evidence from the current script version invalidates them.
- Old artifacts, old screenshots, and old browser states cannot reopen a resolved blocker.
- If the current page already satisfies a project, that project is complete and must not be modified again.
- Upload progress may block the final publish click, but it does not block independent editable projects when those controls are visible.
- Publication browser evidence is valid only when it comes from `publication-browser-agent` bound through `bridge://chrome-extension` to the browser/profile declared by the task's creator card. Edge, in-app Browser, or direct Codex Chrome-tab probing are not valid publication evidence.

## Authoritative Browser Runtime

- Browser/profile binding must be resolved from the task's creator card / publication credential.
- For the current FAS publication runs, that binding resolves to:
  - Browser: `Google Chrome`
  - User data dir: `C:/Users/28687/AppData/Local/Google/Chrome/User Data`
  - Profile directory: `Profile 2`
  - Bound profile id: `browser-profile:chrome:21104fd69d72ad7267c2`
- browser-agent base URL: `http://127.0.0.1:49310`
- browser transport: `chrome_extension_bridge`
- bridge endpoint: `bridge://chrome-extension`
- bridge extension: `RoughCut Publication Bridge`

Invalid evidence:

- Any platform page opened in Edge
- Any platform page opened by Codex browser tools outside `publication-browser-agent`
- Any probe result gathered when `/healthz.attached_profile_binding` does not match the binding resolved from the current task's creator card

2026-06-07 invalidated batch:

- The earlier cross-platform batch tab-opening attempt that surfaced YouTube/Xiaohongshu/Kuaishou/Toutiao/Douyin pages in an Edge window is invalid and must not be used for future platform conclusions.

## Bilibili

### Current Goal

Keep Bilibili closed on the shared framework side and only reopen it if fresh live evidence from the current script version contradicts the current contract.

### Current Page State

- Current runtime should treat Bilibili standard publication as a clean new-video flow from `https://member.bilibili.com/platform/upload/video/frame`.
- If the upload entry shows `本地浏览器存在...未提交的视频` with `继续编辑 / 不用了`, the correct discard action remains `不用了`.
- If a populated dirty editor must be exited before reset, prefer `存草稿` before any route switch that could trigger `离开此网站`.

### Resolved

- Duplicate upload root cause has been diagnosed and fixed at the script path level.
- Bilibili must have a single upload path. If the intended file is already attached, do not touch file inputs, upload buttons, fallback uploaders, or native chooser paths.
- The draft resume prompt is conditional only. If absent, do not search for it.
- `stop_before_final_publish` is publish suppression only. It must not silently switch the task into current-page reuse mode.
- Mainline Bilibili payload generation no longer trusts stale explicit `publish_ready=false` when the current platform fields are otherwise usable.
- Preview copy and production `smart-copy` source-of-truth are now connected by the shared promotion chain. Live publish must read promoted production copy, not local preview artifacts.
- The Bilibili stale-editor reset path now explicitly distinguishes a clean upload entry from a populated wrong-draft editor surface.
- Bilibili production live payloads now inherit normalized packaging instead of raw platform subentries, so shared `cover_matrix` data reaches mainline execution.
- Bilibili cover source-of-truth is no longer a single `16:9` primary-cover contract. The current normalized contract is:
  - `首页推荐封面（4:3） -> landscape_4_3`
  - `个人空间封面（16:9） -> landscape_16_9`
- Browser-agent Bilibili cover execution now consumes per-slot expected paths and fails closed when either slot path is missing instead of reusing one image for both slots.

### Open

- Current first open Bilibili blocker is no longer source-of-truth or stale-draft reset. It is the execution-layer closeout inside the cover editor:
  - fresh live evidence still shows `clicked_done=false`
  - `default_first_frame_after=true`
  - `editor_still_open=false`
  - so slot-path routing is fixed, but the cover editor final confirmation/readback contract is still not fully closed.
- Upload progress may still legitimately block final publish. This is not a Bilibili framework regression as long as the task stops on `upload_ready` only.
- After browser-agent restarts, `RoughCut Publication Bridge` may need to reconnect before live verification can resume. This is an external runtime state, not a publication-framework regression.

### Invalidating Evidence Required

Duplicate upload can only be reopened if a fresh run with the current script version creates a second upload from a clean page where the intended file was not already attached.

The clean-new-flow discard contract can only be reopened if fresh live evidence with the current script version shows Bilibili no longer presenting `继续编辑 / 不用了`, or the site replaces that prompt with a materially different discard flow.

The dual-cover source-of-truth contract can only be reopened if fresh live evidence with the current script version proves Bilibili no longer requires distinct `4:3` and `16:9` slot uploads, or the page materially changes the slot model.

## Next Platforms

### Douyin

- Douyin source-of-truth start page is `https://creator.douyin.com/creator-micro/content/upload`, not `/creator-micro/content/post/video`.
- Shared publication contract for Douyin has been corrected to the new standard mode:
  - fresh-draft platform tests must use `fresh_start_platform_tab`, not `prepare_only_current_page`
  - the platform gets a new authoritative upload-shell tab
  - upload is always the first step
  - platform-local editor steps run once in order, without shared pre-publish auto-repair re-entry
  - duplicate-history gate, live-publish capability gate, and current-page route correction must not preempt that fresh-start flow
- Current first open blocker for Douyin is now platform-local editor closeout plus runtime rebind:
  - code-side fresh-start linear execution mode is in place, and Douyin topic verification now prefers inserted body topics over recommended chips
  - the current live blocker after the latest browser-agent restart is that `/healthz.attached_profile_binding` has not yet reattached to the authoritative Chrome profile, so fresh live evidence cannot yet validate the new linear-mode behavior
  - once runtime binding is restored, the remaining Douyin closeout items are platform-local only: body idempotence confirmation, topic suggestion selection verification, collection selection/creation, declaration value verification, and schedule value verification

### Xiaohongshu

- Probe immediately after Douyin.
- Watch for whether current normalized cover contract, collection strategy, and publish-route readiness assumptions survive on a second creator platform without reopening Bilibili findings.
- First live preflight result on `2026-06-07`:
  - browser-agent session is ready
  - creator-session route is available at `https://creator.xiaohongshu.com/publish`
  - shared preflight now falls back from `chrome_extension_bridge` health/session data instead of failing hard on legacy `9222/json/list`
  - tab can now be marked `found` from creator-session route evidence
- Current first open blocker for Xiaohongshu is twofold:
  - production `platform-packaging` still `publish_ready=false`
  - direct `/probes` for `xiaohongshu` currently times out, so detailed page inventory is still a shared framework issue rather than a Xiaohongshu-local flow issue
