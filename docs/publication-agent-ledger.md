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

## 2026-06-19 Account Binding Rule

- Creator platform binding must not infer "bound" from a default platform, default browser, or synthetic account label.
- `social-auto-upload` bindings require an explicit account label plus a user-confirmed login flow. The UI must open a login/QR/manual-login modal first, then save the binding only after the user confirms the platform account.
- Legacy bindings with `status=login_reference_bound` are not confirmed accounts. Treat them as needing re-login confirmation and block automatic publish until upgraded to `status=login_confirmed`.
- This is required because the same platform can have multiple accounts, and RoughCut must know which account label the publication credential targets.
- The publication-management binding modal now auto-starts the login flow when opened and polls `social-auto-upload check` until login succeeds. If the Docker API runtime cannot access the Windows `social-auto-upload` root, it must call `codex_host_bridge` host routes for login/check instead of falling back to fake success or requiring copied shell commands.

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
- 2026-06-19 Jenny Baby binding update:
  - creator `7be7da2e-7d54-4d0b-a63d-809d71094839` is bound to Bilibili with display label `珍妮斯baby · Chrome`.
  - Credential isolation key is `creator-7be7da2e7d54-bilibili-chrome`; cookie file is `E:/WorkSpace/_eval/social-auto-upload/cookies/bilibili_creator-7be7da2e7d54-bilibili-chrome.json`.
  - Stored binding must keep `account_label` for UI display and `account_name` for the isolated social-auto-upload key. Do not use the display label as the cookie key.
  - The `credential_ref` contract is `social-auto-upload:<account_name>:<platform>`, currently `social-auto-upload:creator-7be7da2e7d54-bilibili-chrome:bilibili`.
  - Root cause fixed during binding: Bilibili login saved a valid storage state, but `sau_cli.py bilibili check` still used the old `biliup renew` path and reported `invalid`; it now reuses `bilibili_setup/cookie_auth`, and `cookie_auth` accepts loaded Bilibili auth cookies as the base login-state evidence.

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
- 2026-06-19 Jenny Baby video-account binding update:
  - creator `7be7da2e-7d54-4d0b-a63d-809d71094839` is bound to WeChat Channels with display label `珍妮斯baby · 视频号`.
  - Credential isolation key is `creator-7be7da2e7d54-wechat-channels-chrome`; cookie file is `E:/WorkSpace/_eval/social-auto-upload/cookies/tencent_creator-7be7da2e7d54-wechat-channels-chrome.json`.
  - Root cause fixed during binding: the actual post-login landing page was `https://channels.weixin.qq.com/platform`, but `_is_tencent_login_completed()` only accepted post-create/post-list URLs; `sau_cli.py tencent check` also refused to inspect the persistent profile before the JSON snapshot existed.
  - Check behavior while the dashboard is already open: if the persistent profile is locked by a headed backend window, `cookie_auth()` falls back to the saved storage_state snapshot and still returns `valid` when the session is usable.
  - Current evidence: `sau_cli.py tencent check --account creator-7be7da2e7d54-wechat-channels-chrome` returns `valid`; RoughCut login-status returns `login_valid`; RoughCut dashboard action returns `dashboard_started`.
  - Keep account isolation strict: UI label stays `account_label`; all check/publish/dashboard operations must use `account_name` from `credential_ref`.

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

## 2026-06-19 Jenny Baby Auto-Publish Closure

- All Jenny Baby `social-auto-upload` isolated credentials checked valid on the host runtime:
  - `bilibili`: `creator-7be7da2e7d54-bilibili-chrome`
  - `douyin`: `creator-7be7da2e7d54-douyin-chrome`
  - `xiaohongshu`: `creator-7be7da2e7d54-xiaohongshu-chrome`
  - `kuaishou`: `creator-7be7da2e7d54-kuaishou-chrome`
  - `wechat-channels`: `creator-7be7da2e7d54-wechat-channels-chrome`
- New publication schedule contract:
  - `PublicationAttempt` remains the publication log source of truth.
  - Same platform account defaults to one video per local day.
  - If a target account/day is already occupied by an active, published, or scheduled attempt, new attempts auto-defer to the next open local day at `10:00 Asia/Shanghai` unless an explicit schedule time was supplied.
  - The deferral reason is written to `request_payload.metadata.publication_schedule_policy` and `operator_summary`.
- Root-cause fixes for Jenny Baby S02E02 plan readiness:
  - `src/roughcut/publication_platform_matrix.json` no longer marks `wechat-channels` as `manual_handoff_only`; it is an automatic `social-auto-upload` target when a confirmed binding exists.
  - `normalize_publication_credentials(...)` infers `adapter=social_auto_upload` from `credential_ref=social-auto-upload:...`.
  - `intelligent-copy` publish inputs now merge creator-card `CreatorPlatformBinding` records into the avatar material profile publication credentials, so creator card bindings are visible to `build_publication_plan(...)`.
  - `social-auto-upload` scheduled submissions now map to `scheduled_pending`, not `draft_created`.
- Live plan evidence for S02E02 `仓储超市`:
  - Plan artifact: `artifacts/janice-s02e02-publication-plan.json`.
  - API path: `POST /api/v1/intelligent-copy/publication/plan`.
  - Result: `status=ready`, `publish_ready=true`, no blocked reasons.
  - Targets: `douyin`, `xiaohongshu`, `bilibili`, `kuaishou`, `wechat-channels`.
  - All five targets resolved to `adapter=social_auto_upload`.
- Live publish evidence for S02E02 `仓储超市`:
  - `PublicationAttempt` is now the live publication log and recovery ledger for the series.
  - Publish artifacts:
    - `artifacts/janice-s02e02-publication-publish-response.json`
    - `artifacts/janice-s02e02-publication-republish-after-host-bridge-response.json`
    - `artifacts/janice-s02e02-publication-republish-title-category-fix-response.json`
    - `artifacts/janice-s02e02-publication-retry-wechat-response.json`
  - RoughCut runtime fixes required for real publish:
    - `worker-publication` must run from the current `/app/src` source mount; the old orphan worker rejected `adapter=social_auto_upload`.
    - Docker workers must execute Windows-only `social-auto-upload` through `codex_host_bridge` `/v1/host/social-auto-upload-command`; direct subprocess from Linux resolves the root as an invalid `/app/E:/...` path.
    - `social-auto-upload` account names must come from `request_payload.metadata.credential_ref`, not RoughCut UUID credential ids.
    - Platform command building must derive missing titles from copy material/body for title-required platforms and must provide Bilibili default `tid=254` / `category=生活/亲子` when no explicit partition is supplied.
  - Platform outcomes:
    - Douyin attempt `e9ea99b791f048299a7ef840868bc604`: `scheduled_pending`, scheduled for `2026-06-19 20:30 Asia/Shanghai`.
    - Kuaishou attempt `8bccdef08a89489db09b151253c549b9`: `scheduled_pending`, scheduled for `2026-06-19 20:00 Asia/Shanghai`.
    - Bilibili attempt `133ca58ced2a4af3adf759a8c2819b51`: failed in upstream schedule UI automation after title, cover, declaration, and category succeeded. First bad layer: `social-auto-upload/uploader/bilibili_uploader/main.py::_set_schedule`; old `.time-container input[placeholder*=日期/时间/预约]` selector no longer matches the current page.
    - Xiaohongshu attempt `f616adffaac14a26ae3cffcdcf277e0d`: failed in upstream schedule UI automation. First bad layer: `social-auto-upload/uploader/xiaohongshu_uploader/main.py::set_schedule_time_xiaohongshu`; the expected datepicker input did not appear after enabling scheduled publish.
    - WeChat Channels attempt `a506e1f3058a4597bff56a3e29eabb25`: failed again after a valid `sau_cli.py tencent check`. First bad layer: upstream Tencent creator-page entry/login-state detection; `check` can report valid while real upload does not reach the creation page.
  - Do not mark Bilibili, Xiaohongshu, or WeChat Channels as successfully scheduled until the upstream `social-auto-upload` platform adapters are fixed and rerun with fresh live evidence.

### 2026-06-19 Jenny Baby Auto-Publish Root-Cause Follow-Up

- Current attempt state after the duplicate guard:
  - Xiaohongshu `f616adffaac14a26ae3cffcdcf277e0d`: intentionally failed with `social_auto_upload_duplicate_execution_guard`; do not retry before worker/source reload.
  - Douyin `e9ea99b791f048299a7ef840868bc604`: `scheduled_pending`, `2026-06-19 20:30 Asia/Shanghai`.
  - Kuaishou `8bccdef08a89489db09b151253c549b9`: `scheduled_pending`, `2026-06-19 20:00 Asia/Shanghai`.
  - WeChat Channels `a506e1f3058a4597bff56a3e29eabb25`: failed on upload-complete timeout; next run should inspect new timeout JSON/HTML diagnostics.
  - Bilibili `133ca58ced2a4af3adf759a8c2819b51`: failed before this follow-up; source now has submit-response success detection but no fresh live retry yet.
- Root cause fixed in RoughCut:
  - Long `social-auto-upload` CLI calls used to keep attempts visibly `queued` until the subprocess returned, so a later publication-worker tick could start the same attempt again.
  - `submit_publication_attempt_to_social_auto_upload(...)` now commits attempt/run `processing` state, provider task id, heartbeat, and lease before invoking the external CLI.
- Root causes fixed upstream in `E:/WorkSpace/_eval/social-auto-upload`:
  - Xiaohongshu cover upload, schedule input, upload-settled wait, and custom final publish button click paths were updated for the current DOM. The final click fix still needs live proof after reload.
  - Bilibili final submit now patches `/x/vu/web/add*` and `/x/vu/web/edit` POST bodies with the target `dtime`, records patch hits, records submit responses, and treats HTTP 2xx with JSON `code=0` as the authoritative success signal.
  - WeChat Channels upload timeout now writes PNG/HTML/JSON diagnostics with publish-button state, status/toast/error/tips text, and relevant body lines.
- Operating rule:
  - Restart/reload `worker-publication` and ensure Windows `social-auto-upload` uses the current source before any retry of Xiaohongshu, Bilibili, or WeChat Channels.
  - No active `sau_cli.py` process remained after cleanup.
- Verification:
  - RoughCut: `python -m py_compile src\roughcut\publication.py src\roughcut\publication_social_auto_upload.py src\roughcut\api\intelligent_copy.py`; `PYTHONPATH=src python -m pytest tests\test_publication_social_auto_upload.py -q` (`20 passed`).
  - Upstream: `py_compile` for Xiaohongshu/Tencent/Bilibili uploaders; `tests.test_xiaohongshu_uploader` (`12 passed`); `tests.test_tencent_uploader` (`4 passed`); non-interactive Bilibili submit/payload tests (`5 passed`).

### 2026-06-19 Jenny Baby Auto-Publish Latest Live Closure

- Current S02E02 `仓储超市` publication ledger:
  - Douyin `e9ea99b791f048299a7ef840868bc604`: `scheduled_pending`, `2026-06-19 20:30 Asia/Shanghai`.
  - Kuaishou `8bccdef08a89489db09b151253c549b9`: `scheduled_pending`, `2026-06-19 20:00 Asia/Shanghai`.
  - Xiaohongshu `f616adffaac14a26ae3cffcdcf277e0d`: `scheduled_pending`, `2026-06-20 21:00 Asia/Shanghai`.
  - Bilibili `133ca58ced2a4af3adf759a8c2819b51`: `scheduled_pending`, `2026-06-20 18:00 Asia/Shanghai`; submit response returned `code=0`, `aid=116777056995111`, `bvid=BV15Uj66SEXz`.
  - WeChat Channels `a506e1f3058a4597bff56a3e29eabb25`: still failed; latest manual stop was after applying the new upload-completion fallback, so it does not prove the new code failed.
- Xiaohongshu root cause closed:
  - The old adapter forced original declaration for remix content, which exposed a second-level content-source declaration and blocked publish.
  - The adapter now treats original declaration as opt-in, leaves it off for Jenny's secondary-creation content, and only selects content type declaration when explicitly required.
  - The final `xhs-publish-btn` click now uses visible custom-element/shadow DOM candidates and physical click fallback.
- Bilibili root causes closed:
  - `_publish()` no longer treats any clicked text as submission; it now requires a real submit signal: `/x/vu/web/add*`/`edit` route hit, submit response, success text, success URL, or auto-submit overlay.
  - Scheduled submit requests patch `dtime` and HTTP 2xx JSON `code=0` is authoritative success evidence.
  - Missing/changed optional collection UI is now diagnostic-only and cannot block the main publish path.
- WeChat Channels current open root cause:
  - The first bad layer is upstream upload-completion detection in `uploader/tencent_uploader/main.py`.
  - Live diagnostics show the page can reach the main form with an enabled but hidden/off-screen publish button; the old wait loop only accepted visible publish buttons and could wait until timeout.
  - Current source now traverses publish-button candidates, scrolls enabled buttons into view, and after the main form is stable allows an enabled hidden publish button to count as upload-complete. This code is unit-tested but still needs a fresh uninterrupted live retry.
- Latest verification:
  - RoughCut: `python -m py_compile src\roughcut\publication.py src\roughcut\publication_social_auto_upload.py src\roughcut\api\intelligent_copy.py`; `PYTHONPATH=src python -m pytest tests\test_publication_social_auto_upload.py -q` (`20 passed`).
  - Upstream Xiaohongshu: `py_compile uploader\xiaohongshu_uploader\main.py`; `python -m unittest tests.test_xiaohongshu_uploader` (`16 passed`).
  - Upstream Bilibili: `py_compile uploader\bilibili_uploader\main.py`; selected non-interactive Bilibili tests (`8 passed`).
  - Upstream Tencent: `py_compile uploader\tencent_uploader\main.py`; `python -m unittest tests.test_tencent_uploader` (`5 passed`).

### 2026-06-19 Xiaohongshu Original Declaration Policy Correction

- Product-policy correction: for Jenny Baby remix videos, 小红书“原创声明” should represent that this account created the current episode/video and is not reposting another user's ready-made work. It should be enabled for the series.
- First bad layer: RoughCut publication metadata policy, not the Xiaohongshu DOM automation.
- Root cause: `publication_platform_matrix.json` marked `xiaohongshu.supports_declaration=false` and left `default_declaration=""`; therefore RoughCut generated no declaration by default and `social-auto-upload` did not receive `--original-declaration`.
- Fix: Xiaohongshu now supports declarations and defaults to `原创声明`, so future RoughCut payloads resolve to original declaration and the social-auto-upload command appends `--original-declaration`.
- Existing live caveat: Xiaohongshu attempt `f616adffaac14a26ae3cffcdcf277e0d` was already scheduled under the prior policy at `2026-06-20 21:00 Asia/Shanghai`; if strict declaration correctness is required for that exact scheduled item, cancel/replace it in the platform queue before creating a new attempt.
- Verification:
  - `PYTHONPATH=src python -m pytest tests\test_publication.py::test_build_request_payload_uses_shared_default_declaration_for_xiaohongshu tests\test_publication_social_auto_upload.py::test_build_social_auto_upload_upload_command_for_xiaohongshu_group_chat_and_original -q` (`2 passed`).
  - `PYTHONPATH=src python -c "... platform_default_declaration('xiaohongshu') == '原创声明' ..."` passed.

### 2026-06-19 Bilibili/Xiaohongshu Publish Status Correction

- User-visible correction: Douyin and Kuaishou are the only fully accepted successes from the current live round. Bilibili and Xiaohongshu must not be treated as closed just because the CLI returned success text.
- Bilibili observed symptom: the submit API returned `code=0`, but the submitted archive landed in Bilibili backend with `tid=47` (`动画/同人·手书`) instead of the intended parenting category.
- Bilibili first bad layer: RoughCut `build_social_auto_upload_upload_command(...)` omitted `--tid/--category` when `request_payload.category` was missing.
- Bilibili root cause: the intended default `BILIBILI_DEFAULT_TID=254` / `BILIBILI_DEFAULT_CATEGORY=生活/亲子` existed in code but was not applied in the missing-category path, so Bilibili auto-classified the Bluey remix.
- Bilibili live verification: read-only creator-center API `x/vupre/web/archive/view?aid=116777056995111` returned `code=0`, `bvid=BV15Uj66SEXz`, `state=-40`, `state_desc=通过审核，等待发布`, `dtime=1781949600`, but `tid=47`.
- Bilibili fix: missing-category uploads now explicitly include `--tid 254 --category 生活/亲子`.
- Xiaohongshu correction: current scheduled attempt `f616adffaac14a26ae3cffcdcf277e0d` was created before the original-declaration policy correction and kept original declaration off. It should not be reused as proof of the corrected policy.
- Verification:
  - `python -m py_compile src\roughcut\publication_social_auto_upload.py src\roughcut\publication.py`.
  - `PYTHONPATH=src python -m pytest tests\test_publication_social_auto_upload.py::test_build_social_auto_upload_upload_command_for_bilibili_uses_parenting_default_category_when_missing tests\test_publication_social_auto_upload.py::test_build_social_auto_upload_upload_command_for_xiaohongshu_group_chat_and_original tests\test_publication.py::test_build_request_payload_uses_shared_default_declaration_for_xiaohongshu -q` (`3 passed`).

### 2026-06-19 Bilibili Post-Submit Verification Closure

- Bilibili observed symptom: a platform submit response can be successful while the resulting backend archive has the wrong business fields. Current live archive `aid=116777056995111` exists and is scheduled, but has `tid=47` instead of expected `254`.
- First bad layer: RoughCut success mapping after `social-auto-upload upload-video`; the adapter accepted CLI success without reading the platform backend record.
- Root cause: Bilibili `code=0` proves submission acceptance only. It does not prove category/title/schedule correctness, so missing default `--tid` surfaced as a false success.
- Fix:
  - Added `sau_cli.py bilibili verify-video --aid ...` in `E:/WorkSpace/_eval/social-auto-upload`; it reads `x/vupre/web/archive/view` with stored creator cookies and validates expected title, tid, and schedule timestamp.
  - RoughCut now parses Bilibili `aid` from upload stdout, calls `verify-video`, stores the verification payload, and marks the attempt `needs_human` on mismatch or missing receipt instead of `scheduled_pending`.
- Live verification:
  - `sau_cli.py bilibili verify-video --account creator-7be7da2e7d54-bilibili-chrome --aid 116777056995111 --expected-title "S02E02关键画面整理" --expected-tid 254 --expected-schedule "2026-06-20 18:00"` returned exit code `1` with `success=true`, `verified=false`, `state_desc=通过审核，等待发布`, mismatch `tid expected=254 actual=47`.
- Test verification:
  - RoughCut py_compile for `publication.py` and `publication_social_auto_upload.py` passed.
  - RoughCut targeted pytest passed: Bilibili default category, Xiaohongshu original declaration command, Bilibili verification success path, Bilibili verification mismatch path, and Xiaohongshu default declaration payload (`5 passed`).
  - social-auto-upload `sau_cli.py` py_compile passed.
  - social-auto-upload selected Bilibili CLI verification tests passed (`3 passed`).
