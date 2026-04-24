# Manual Editor Open Source Alignment

## Baseline

RoughCut manual editing mode should use proven editing concepts instead of growing a custom timeline widget.

The first implementation already proves the backend loop:

- Load the latest editorial timeline and subtitles.
- Accept manually edited keep segments.
- Reproject subtitles through the same keep-segment mapping.
- Save a new editorial timeline version.
- Rebuild the render plan.
- Rerun render, final review, and platform packaging.

That loop stays. The frontend editor and data schema should now move toward open editing models.

## Reference Projects

- OpenTimelineIO: use the `Timeline / Track / Clip / Gap / SourceRange` model as the internal editorial shape.
- wavesurfer.js: use waveform, timeline, and regions plugins for interactive media timing.
- Subtitle Edit: copy the workflow model for subtitle table editing, overlap checks, batch time adjustment, split, merge, and retiming.
- Aegisub: copy the timing interaction model for waveform-based subtitle boundary adjustment.
- Video.js: use only if native video controls become insufficient for frame stepping, hotkeys, or consistent browser playback.
- Remotion: keep as a reference for preview/render composition ideas, not as RoughCut's main render kernel.

## Architecture

Manual editing is split into three contracts:

1. Source timeline

   Original media time. Keep regions are stored in source seconds.

2. Output timeline

   Concatenated result after deleted gaps are removed. Subtitles are projected into this time domain.

3. Render contract

   A versioned editorial payload plus subtitle projection. Downstream render, effects, avatar overlay, and platform package steps consume this contract.

## Data Shape

The long-term editorial payload should be OTIO-compatible:

```json
{
  "schema": "roughcut.editorial.v2",
  "tracks": [
    {
      "kind": "video",
      "items": [
        {
          "type": "clip",
          "source_range": { "start": 12.4, "duration": 5.2 },
          "output_range": { "start": 0, "duration": 5.2 },
          "source_url": "..."
        },
        {
          "type": "gap",
          "source_range": { "start": 17.6, "duration": 2.1 },
          "reason": "manual_removed"
        }
      ]
    }
  ],
  "subtitle_projection": {
    "mode": "ripple",
    "source": "latest_reviewed_subtitles"
  }
}
```

The current `keep_segments` API can remain as a compact editing input, but the persisted timeline should evolve toward this shape.

## Frontend Phases

1. Waveform regions

   Use wavesurfer.js regions as the primary keep-segment editor. Dragging or resizing a region updates `keep_segments`, and subtitles reproject immediately.

2. Subtitle table

   Add a table with source time, output time, text, confidence, and validation state. Selecting a subtitle seeks the waveform and video.

3. Timing tools

   Add nudge, split, merge, min-gap enforcement, overlap warnings, and batch shift. This follows Subtitle Edit and Aegisub workflows.

4. Preview performance

   Generate proxy audio, waveform peaks, and thumbnails server-side for long videos. The editor should not depend on browser decoding of full source media.

5. Render optimization

   Track change type. Subtitle-only changes should avoid rebuilding video cuts. Timeline changes should rebuild cuts and keep downstream effects/avatar render intact.

## Current M1 Implementation

The first open-source-aligned frontend step uses `wavesurfer.js`:

- `wavesurfer.js` is added as a BSD-3-Clause dependency.
- The manual editor now renders a waveform timeline.
- Keep segments are editable regions.
- Clicking the waveform seeks the video preview.
- Dragging/resizing regions updates subtitle projection in real time.
- The existing apply endpoint still saves and reruns rendering.

## Current M2 Implementation

The backend now persists an OTIO-style editorial shape alongside the legacy render-compatible `segments` list:

- `schema` is set to `roughcut.editorial.v2`.
- `source_duration_sec` and `output_duration_sec` are recorded.
- `tracks` contains `source_video` with clips and removed gaps, plus `output_video` with only kept clips.
- Each item carries `source_range`; kept clips also carry `output_range` and `media_reference`.
- `subtitle_projection` records that subtitles were projected with ripple keep-segment mapping.
- OTIO export prefers the `output_video` track when present and falls back to legacy `segments` for older timelines.

## Current M3 Implementation

The manual editor now has a Subtitle Edit/Aegisub-style subtitle timing surface:

- The frontend renders a subtitle timing table on the output timeline.
- Selecting a subtitle seeks the video and waveform preview.
- Text, start time, and end time can be edited per subtitle.
- Selected subtitles can be nudged by 100 ms in either direction.
- All subtitles can be shifted left or right by an operator-provided millisecond value.
- The table reports empty text, too-short subtitles, overlaps, and out-of-range timings.
- A minimum-gap action can normalize subtitle spacing in the current output timeline.
- Split creates a new persisted subtitle override; merge extends the selected subtitle and marks the next one deleted.
- Changed rows are marked in the table and counted before saving.
- The apply endpoint accepts `subtitle_overrides` and applies them after ripple projection.
- The saved editorial timeline stores `subtitle_projection.overrides` plus final `subtitle_projection.items`.
- Reopening the manual editor reloads saved subtitle overrides from the latest editorial timeline.

This covers the first practical Subtitle Edit/Aegisub-style timing pass. The next missing pieces are keyboard shortcuts, waveform subtitle boundary handles, and stronger server-side diagnostics for impossible timing edits.

## Current M4 Implementation

The manual editor now has a first long-video preview asset layer:

- The backend can generate cached manual editor preview assets under the job storage directory.
- Assets include mono 16 kHz proxy audio, waveform peaks JSON, and a bounded set of timestamped low-resolution thumbnails.
- `/manual-editor/assets` returns the proxy audio URL, peaks, sample rate, duration, thumbnail URLs, timestamped thumbnail items, and cache status.
- `/manual-editor/assets/status` checks whether cached assets are ready without running ffmpeg.
- `/manual-editor/assets/warm` schedules background generation through FastAPI background tasks.
- `/manual-editor/assets/{filename}` serves only files inside the job's manual editor asset directory.
- The frontend requests status after loading the manual editor session, triggers warmup if needed, and polls until ready.
- wavesurfer.js uses proxy audio plus precomputed peaks when available, falling back to the original source URL otherwise.
- The UI shows cache status, peak count, a zoomable waveform, and a clickable thumbnail strip near the waveform.

The synchronous `/manual-editor/assets` endpoint remains as an explicit fallback. The next performance step is server-side cancellation/progress for long warmups, plus tighter integration between thumbnail strip position and output-time playback.

## Current M5 Implementation

The manual editor now classifies saved changes before rebuilding the render contract:

- Timeline edits are detected by comparing previous and submitted keep segments with a small timing tolerance.
- Subtitle-only edits are detected when keep segments are unchanged but subtitle overrides exist.
- Subtitle-only saves reuse the previous render plan's timeline analysis and editing accents, so subtitle text/timing fixes do not accidentally regenerate cut rhythm, smart effects, or avatar choreography.
- Timeline saves still rebuild timeline analysis and smart editing accents from the new keep segments.
- The apply response records `change_scope` and `render_strategy`, and the editor header previews whether the save will be a timeline change or subtitle-only change.

Current limitation: RoughCut still burns subtitles into the rendered variants, so subtitle-only saves still rerun `render -> final_review -> platform_package`. A future subtitle-layer renderer can use the same `change_scope=subtitle_only` signal to rebake only subtitle overlays from existing clean variants.

## Current M6 Implementation

The manual editor availability model now follows readiness of required editing assets instead of waiting for the whole pipeline to finish:

- The editor can open once source media, editorial timeline, and render plan are available.
- The prerequisite gate is `edit_plan` and all earlier steps being done or skipped; downstream `render`, `final_review`, and `platform_package` do not have to be complete.
- Saving is still protected against concurrent output writes: if downstream render/review/package steps are actively running, apply returns a conflict message and asks the operator to save after that running step finishes.
- Subtitle-only reruns preserve existing render artifacts so the render step can reuse the prior clean `plain_mp4` as a base.
- Render now prefers manual-editor `subtitle_projection.items` when present, so text/timing edits saved in the manual editor are authoritative for regenerated variants and platform packaging.
- Existing avatar picture-in-picture outputs can be reused during subtitle-only rerenders, avoiding unnecessary provider calls when the visual timeline did not change.

## Current M7 Implementation

The editor now has a first keyboard workflow layer inspired by subtitle timing tools:

- `Space` toggles edited timeline playback.
- `Left` and `Right` seek source preview by one second.
- `Alt + Left/Right` performs approximate frame stepping at 30 fps.
- `[` and `]` nudge the selected subtitle by 100 ms.
- `Alt + [` and `Alt + ]` nudge the selected subtitle by 10 ms for fine timing.
- `Ctrl/Cmd + S` saves the current edit.
- `Delete/Backspace` removes the selected keep segment when segment editing is focused outside text inputs.
- `A` and `S` set the selected subtitle start/end to the current output playhead.
- `J` and `K` move to the previous/next subtitle.

Shortcuts are ignored while typing in text fields except for save, so subtitle text editing remains safe.

## Current M8 Implementation

The manual editor save path now has optimistic revision protection:

- The session payload includes the current editorial timeline id/version and render-plan timeline version.
- Save requests carry those base revision fields back to the API.
- If another process has changed the timeline or render-plan base after the editor opened, apply returns HTTP 409 instead of overwriting newer work.
- The frontend surfaces conflict errors as save feedback so the operator can refresh before retrying.

## Current M9 Implementation

The editor now shows save feedback and impact before committing changes:

- The frontend computes whether the save is timeline, subtitle-only, or no material change.
- The header summarizes segment-count delta, output-duration delta, and changed subtitle count.
- Save is disabled when there is no material edit.
- The operator gets a confirmation prompt with the impact summary before the backend rerun is triggered.
- Save success and save failure messages are shown near the job detail panel.

## Current M10 Implementation

Preview asset generation now exposes persistent status for long videos:

- The backend writes `status.json` beside proxy audio, peaks, thumbnails, and manifest data.
- Warmup status includes asset version, lifecycle status, stage, progress, detail, error, and timestamp.
- Stages currently cover `queued`, `proxy_audio`, `waveform_peaks`, `thumbnails`, `cached`, `ready`, and `failed`.
- `/manual-editor/assets/status` returns the persisted status even when assets are not ready.
- `/manual-editor/assets/warm` records a queued state before launching background generation.
- Failed ffmpeg/proxy generation is preserved in status so refreshing the editor does not hide the failure.
- The frontend displays stage chips, progress bar, cache version, detail text, and failure reason in the preview asset area.

## Guardrails

- Do not copy GPL code from Subtitle Edit, Aegisub, or audiowaveform into RoughCut.
- Do not replace the existing render pipeline with a browser-first renderer.
- Do not store only UI state. Persist deterministic editorial data that can be re-rendered without the browser.
- Do not make the frontend the source of truth for subtitle timing. Frontend projection is a preview; backend projection remains authoritative.
