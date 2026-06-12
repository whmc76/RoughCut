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
- The Bilibili cover-editor closeout is now closed in the `social-auto-upload` adapter path:
  - the modal submit button is resolved from the visible bottom action band instead of generic text-only matching
  - main-form cover readiness is verified from actual preview/background-image state instead of stale overlay text
  - final publish click now accepts the real `立即投稿` container/button variants
  - post-submit flow now waits for platform completion/redirect evidence before closing the browser, so upload is not aborted mid-transfer
- Fresh live evidence on `2026-06-10 22:21:33` confirms the title `迟来的开箱！maxace蜂巢3顶配，这做工细节经得起细看` is present in `https://member.bilibili.com/platform/upload-manager/article` with platform state `转码中 / 审核中`.

### Open

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

## 2026-06-11 Stable Baseline

### Formal RoughCut Publication Status

- `douyin` is closed as a RoughCut formal publication platform.
- `kuaishou` is closed as a RoughCut formal publication platform.
- `xiaohongshu` is closed as a RoughCut formal publication platform.
- `bilibili` is closed as a RoughCut formal publication platform on the adapter/runtime side.
- `wechat-channels` is not closed yet. Current blocker is login-state stability, not publish-field control logic.

### Current Production Flow

- Intelligent publish no longer requires `browser-agent` readiness for targets that resolve to `social_auto_upload` only.
- Formal publish now reads promoted production `smart-copy`, not preview-only artifacts.
- Incompatible source media is auto-transcoded into `smart-copy/_publication_runtime/*.publication-runtime.mp4` before publish.
- Current direct-publish override is authoritative: explicit blank `scheduled_publish_at` cancels inherited schedule windows instead of falling back to packaging slots.
- All currently closed platforms should publish through the same RoughCut `submit_publication_attempts -> adapter executor` path; do not validate with one script and then release with another.

### Bilibili

- The stable Bilibili cover contract is dual-slot and must stay explicit:
  - `landscape_4_3` for `首页推荐封面（4:3）`
  - `landscape_16_9` for `个人空间封面（16:9）`
- RoughCut formal payloads now carry both cover slots into `social-auto-upload`.
- RoughCut `social-auto-upload` adapter now also emits stable Bilibili category fallback by passing both:
  - page category display: `生活兴趣/户外潮流`
  - fallback `tid=250`
- Root cause of the earlier “测试时分区正确，真发布跑偏” regression:
  - symptom: the published Bilibili稿件 drifted to the wrong partition during formal release
  - first bad layer: `src/roughcut/publication_social_auto_upload.py::maybe_resolve_bilibili_tid`
  - root cause: when UI category text existed but did not map directly to a known `tid`, the adapter suppressed `legacy_api_fallback` and sent only the display string downstream
  - why it surfaced now: RoughCut formal publish had switched to the `social-auto-upload` adapter path, which needs a stable `tid` fallback even when page text uses a newer hierarchical label
- This root cause is fixed in-repo. Reopen Bilibili only if fresh live evidence from the current script version shows category drift again.
- The already published `maxace蜂巢3顶配` Bilibili稿件 may still contain the old wrong partition/tag result. Treat that as historical output drift, not an open framework blocker.

### Douyin

- Current formal contract is direct publish first, not schedule-first.
- Stable requirements already proven in the formal path:
  - accurate collection selection
  - vertical and horizontal cover slot support
  - no wait-for-upload-complete gate before editable field completion
- Do not reintroduce pre-publish “repair re-entry” loops. Upload starts first; editable fields are filled linearly while upload progresses.

### Kuaishou

- Current formal contract is closed on:
  - collection selection
  - declaration
  - topic/tag insertion
  - upload-time field completion
- Tag selection should prefer real dropdown suggestions when available, but case drift in the final tag should not block publish if the first matching recommendation is usable.

### Xiaohongshu

- Current formal contract is closed on:
  - collection
  - original declaration
  - group chat
  - cover-first ordering to avoid later modal interruption
- The decisive stabilization rule is: complete cover-related work before later declaration/group-chat modal interactions can be interrupted by upload-finish side effects.

### WeChat Channels

- WeChat Channels is now part of the RoughCut `social-auto-upload` target matrix and is no longer treated as manual handoff by contract.
- Cover contract is already upstream-aligned:
  - `landscape_4_3`
  - `portrait_3_4`
- Current open blocker is login-state durability:
  - symptom: formal publish reaches `social-auto-upload` but fails before upload because the page lands on `https://channels.weixin.qq.com/login.html`
  - first bad layer: upstream `E:/WorkSpace/_eval/social-auto-upload/uploader/tencent_uploader/main.py::cookie_auth/_is_tencent_login_completed`
  - root cause: the old login check treated login-page marketing text containing `发表视频` as proof of a valid creator session
  - why it surfaced now: once WeChat Channels moved into the same formal adapter path, fake-positive cookie validation allowed the publish step to continue into a non-creator page where no upload control existed
- Upstream fixes already applied locally:
  - `cookie_auth()` now waits for route stabilization before judging validity
  - `_is_tencent_login_completed()` now requires real creator-page controls instead of generic marketing text
  - upload entry probing now captures explicit diagnostics when no file input is found
- Practical conclusion:
  - if `sau_cli.py tencent check --account "FAS · Chrome"` is `invalid`, do not continue publish attempts
  - first refresh login, then publish
- Remaining blocker to close WeChat Channels is external runtime state: cookie expiry / confirmation flow, not current field automation logic.

### YouTube And X

- Current target direction is:
  - `youtube -> browser-agent` bound to the creator card's real Chrome profile
  - `x -> x_link_share` with the public YouTube link, not local video upload
- Root cause of the old YouTube/X drift:
  - symptom: `x` was modeled in RoughCut runtime payloads as a link-share target, but the shared platform matrix still described it like a local video-upload platform
  - first bad layer: `src/roughcut/publication_platform_matrix.json`
  - root cause: shared publish-project contract for `x` had not been updated after `x_link_share` became the intended execution path
  - why it surfaced now: adding `YouTube -> X` chained publish would otherwise keep test/playbook logic and production adapter logic split again
- This is now corrected in-repo:
  - `_resolve_publication_target_adapter("x", "")` defaults to `x_link_share`
  - `x.publish_scheme.projects` now uses `link_share`, not `media_upload`
- Current status:
  - `youtube` is intentionally kept off the RoughCut `social-auto-upload` adapter path
  - root cause: `social-auto-upload` cannot safely reuse an already-open real Chrome Google session for YouTube without hitting profile-lock/runtime drift
  - practical rule: when the requirement is "reuse the bound real Chrome Google account", `youtube` must stay on `browser-agent`, not `social-auto-upload`

### Certification Snapshot

- On `2026-06-10` real RoughCut formal publication for `maxace蜂巢3顶配开箱` reached:
  - `bilibili -> published`
  - `douyin -> published`
  - `kuaishou -> published`
  - `xiaohongshu -> published`
  - `wechat-channels -> blocked by invalid login state`
- `PUBLICATION_SOCIAL_AUTO_UPLOAD_PYTHON` must point to the repo-local interpreter:
  - `E:/WorkSpace/_eval/social-auto-upload/.venv/Scripts/python.exe`
  - using system `python` can reintroduce fake auth failures caused by missing dependencies.
