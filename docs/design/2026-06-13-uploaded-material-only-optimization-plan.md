# RoughCut Uploaded-Material-Only Optimization Plan

Date: 2026-06-13

## Objective

Define the next optimization-upgrade round for RoughCut after the current `information_density` strategy-contract migration, while keeping the product strictly focused on editing user-uploaded materials only.

This plan does not introduce:

- external stock download;
- paid generation providers;
- a second render pipeline;
- a second cut-decision pipeline;
- or a generalized plugin framework.

The purpose of this round is to make RoughCut better at deciding which built-in editing capabilities to use for uploaded materials, without letting new tutorial/highlight/multi-material logic leak across the existing editorial, packaging, render, and publication boundaries.

## Scope Boundary

This plan is intentionally narrower than the long-term product direction.

In scope:

- uploaded source video;
- uploaded auxiliary local materials such as B-roll, still images, music, SFX, intro/outro, watermark assets;
- strategy-based capability selection;
- packaging-only enhancements driven by local evidence and local assets;
- narrow new editing modes built on the existing strategy architecture.

Out of scope:

- external stock providers;
- external asset download;
- AI image generation;
- AI video generation;
- paid audio/music generation;
- provider budget approval flows;
- broad frontend redesign;
- replacing the current FFmpeg render kernel.

## Architectural Rule

All new behavior in this round must fit inside the current mainline:

```text
Source Timeline
  -> Strategy Profile
  -> Capability Orchestrator
  -> Evidence / Candidate Producers
  -> Strategy Decision / Risk Gate
  -> Editorial Timeline
  -> Packaging Timeline
  -> Render Plan
  -> Render / Publication Gates
```

The key rule is that uploaded-material optimization is not allowed to become a parallel workflow.

### Allowed Responsibilities

| Layer | Allowed to do |
|---|---|
| `Strategy Profile` | classify content shape and choose mode defaults |
| `Capability Orchestrator` | decide which capabilities are enabled, suggested, or manual-only |
| `Evidence / Candidate Producers` | emit local facts, candidate segments, focus events, insert plans, audio cues |
| `Strategy Decision / Risk Gate` | decide which candidate actions can auto-apply |
| `Editorial Timeline` | store keep/cut/reorder decisions only |
| `Packaging Timeline` | store subtitles, focus, B-roll inserts, chapter cards, local BGM/SFX, intro/outro, watermark |
| `Render Plan` | normalize one consumable runtime contract for render/manual-editor/publication |

### Forbidden Responsibilities

| Layer | Must not do |
|---|---|
| `Editorial Timeline` | consume packaging logic to change keep/cut decisions |
| `Packaging Timeline` | rewrite keep/cut decisions |
| `Render` | invent video-type logic or capability-selection branches |
| `Publication` | re-derive editing strategy from artifacts ad hoc |
| LLM classification | directly apply final cuts or packaging operations |

## Framework Principles

### 1. One Mainline, No Side Pipelines

Do not port outside tools such as standalone `rough_cut.py`, `render_final.py`, or alternate transcript/render scripts as runnable side paths.

Outside references may inform local producers, readers, or gates, but RoughCut keeps one authoritative mainline.

### 2. Capability Selection Must Be Explicit

Current and future modes should not let tutorial, talking-head, highlight, and multi-material logic drift into random callsites.

A lightweight capability orchestration layer is required so the rest of the pipeline consumes the result instead of re-deciding mode behavior locally.

### 3. LLM Suggests, Policy Decides

The model can classify content and suggest a strategy profile, but deterministic policy decides:

- which capabilities are enabled;
- which can auto-apply;
- which stay suggestion-only;
- which require manual user confirmation.

### 4. Uploaded Assets First

Any enrichment must prefer:

- uploaded video clips;
- uploaded stills;
- uploaded audio;
- already-present packaging assets.

No missing local asset may silently trigger external acquisition.

### 5. Packaging Enhances, Editorial Decides

Local B-roll, focus events, chapter cards, local BGM, and inserted stills are packaging features unless they truly alter the editorial structure through the shared decision gate.

### 6. Minimal New Contracts

Only add a contract when it is needed across more than one stage.

This round should avoid:

- a workflow DSL;
- a large plugin registry;
- duplicated artifacts that restate the same facts under different names.

## Capability Orchestration

This round requires one small new layer:

- `src/roughcut/edit/capabilities.py`
- `src/roughcut/edit/capability_policy.py`
- `src/roughcut/edit/capability_orchestrator.py`

It is not a new pipeline. It is a routing decision layer.

### Purpose

Given:

- `strategy_profile`;
- content profile / inferred video type;
- local uploaded asset inventory;
- user-selected mode and automation preferences;
- current render/package constraints;

produce one normalized capability state map.

### Suggested Output Shape

```json
{
  "strategy_type": "step_demonstration",
  "capabilities": {
    "speech_density_trim": "auto_apply",
    "screen_focus": "auto_apply",
    "chapter_cards": "suggest",
    "local_broll_insert": "suggest",
    "local_audio_cues": "suggest",
    "highlight_window_selection": "disabled",
    "multi_material_assembly": "manual_required"
  }
}
```

### Allowed Capability States

- `auto_apply`
- `suggest`
- `manual_required`
- `disabled`

These states must be consumed downstream instead of recomputed at render/manual-editor/publication exits.

## Planned Modes

This round stays inside uploaded-material-only use cases.

### 1. `information_density`

Current default talking-head / unboxing / explainer baseline.

Keeps:

- speech-focused trim;
- conservative low-risk auto cuts;
- existing packaging defaults.

### 2. `step_demonstration`

For tutorials, product demos, and screen recordings.

Priorities:

- preserve step continuity;
- protect action-relevant silent intervals;
- allow focus events and chapter cards;
- avoid over-trimming non-speech moments that still carry instructional meaning.

### 3. `experience_and_mood`

For vlog-like uploaded-material edits using local B-roll and local music only.

Priorities:

- protect mood-carrying visual intervals;
- allow richer local insert usage;
- keep cuts less aggressive than `information_density`.

### 4. `event_highlight`

For uploaded long-form material where the product should propose highlight windows.

Priorities:

- select candidate windows;
- keep the final auto-apply threshold conservative;
- avoid replacing the current default timeline path for non-highlight jobs.

### 5. `narrative_assembly`

For user-uploaded multi-material composition only.

This first round should remain lightweight:

- order and package already uploaded materials;
- do not assume external missing-shot generation;
- require stricter manual confirmation than other modes.

## Phase Plan

## Phase 0: Baseline Freeze

### Goal

Start from a stable post-refactor baseline instead of mixing new optimization work into unfinished strategy-migration slices.

### Required Inputs

- current `information_density` mainline;
- current strategy-boundary docs;
- current render/manual-editor/helper closure evidence.

### Deliverables

- explicit statement that this round is uploaded-material-only;
- explicit statement that outside provider work is deferred;
- documented anti-side-pipeline rule.

### Closure Conditions

- current mainline closure evidence remains green for the `information_density` baseline;
- no new code in this round bypasses `editorial_timeline`, `packaging_timeline`, or `render_plan`;
- the plan document is the source of truth for follow-on optimization work.

## Phase 1: Capability Orchestration Layer

### Goal

Prevent different editing logics from being smeared across unrelated consumers.

### Deliverables

- capability definitions;
- strategy-to-capability policy;
- orchestrator that combines strategy, local assets, and user mode preferences.

### Closure Conditions

- mode/capability decisions are no longer re-derived independently in render/manual-editor/publication paths;
- the LLM classification output is advisory and flows through deterministic policy;
- existing `information_density` behavior remains equivalent unless a user explicitly chooses another mode;
- focused tests prove capability-state resolution.

## Phase 2: Uploaded Asset Inventory

### Goal

Normalize what local material is available before packaging decisions are made.

### Asset Classes

- primary source video;
- uploaded auxiliary clips;
- uploaded still images;
- uploaded BGM/SFX;
- intro/outro assets;
- watermark/logo assets.

### Deliverables

- one normalized local asset inventory contract;
- shared readers for packaging/mode consumers.

### Closure Conditions

- old jobs with no auxiliary assets still behave the same;
- jobs with auxiliary local assets can route them through shared readers;
- no external source/provider/license contract is added in this phase.

## Phase 3: Local Audio Packaging Plan

### Goal

Support uploaded-material-only BGM/SFX planning without external generation.

### Deliverables

- local audio cue planner;
- shared packaging-timeline representation for local BGM/SFX cues;
- packaged-variant-aware gate behavior.

### Closure Conditions

- local audio cues live in `packaging_timeline`, not in editorial logic;
- plain variants still render when local BGM/SFX are missing;
- packaged variants can consume the local plan deterministically;
- focused tests cover ready/missing/suggest states.

## Phase 4: `step_demonstration` Focus Layer

### Goal

Introduce tutorial/recording-specific packaging behavior without destabilizing the mainline.

### Deliverables

- focus-event evidence/plan support;
- chapter-card support for instructional boundaries;
- mode policy that protects instructional continuity.

### Closure Conditions

- focus logic only affects `packaging_timeline`;
- silent but instructional intervals are not blindly cut by default;
- tutorial jobs degrade cleanly when no focus evidence exists;
- at least one recorded-screen anchor validates timing and framing behavior.

## Phase 5: Local Insert and B-roll Packaging

### Goal

Use already uploaded local materials to enrich talking-head, tutorial, and mood-driven edits.

### Deliverables

- local insert recommendation/selection plan;
- shared packaging representation for inserted clips/stills;
- narrow gating around missing local matches.

### Closure Conditions

- no external asset lookup occurs;
- no local insert behavior mutates the editorial keep/cut contract;
- missing matches remain suggestion-only by default;
- packaged output can consume local insert plans through shared readers.

## Phase 6: Highlight and Multi-Material Candidate Support

### Goal

Add candidate support for uploaded long-form highlight jobs and light multi-material composition.

### Deliverables

- highlight-window candidate producer;
- light uploaded-material assembly planner;
- shared decision-gate integration for conservative auto-apply behavior.

### Closure Conditions

- highlight selection enters the strategy decision layer instead of bypassing it;
- multi-material assembly does not become a second render pipeline;
- automatic application remains conservative;
- candidate provenance and reasons are visible in artifacts.

## Phase 7: Product Mode and UI Exposure

### Goal

Expose the new capability system as a small number of high-level product controls.

### Intended User Controls

- edit mode:
  `auto`, `talking_head`, `tutorial`, `vlog`, `highlight`, `multi_material`
- automation level:
  `conservative`, `standard`, `richer`
- material usage:
  `main_only`, `all_uploaded`, `selected_uploaded`

### Closure Conditions

- UI does not expose provider-specific or stock-specific configuration in this round;
- mode selection resolves through `strategy_profile + capability_policy`, not bespoke view logic;
- default jobs remain on the current stable path.

## Verification Strategy

Each phase should use the narrowest proof that the new behavior works without reopening the closed refactor boundary.

### Required Verification Pattern

1. focused contract/unit tests for the new layer;
2. py_compile or equivalent syntax check for touched modules;
3. one representative replay or anchor for the affected mode when the phase changes runtime behavior.

### Minimum Expectations by Phase

| Phase | Minimum proof |
|---|---|
| 1 | strategy-to-capability policy tests |
| 2 | local asset inventory contract tests |
| 3 | local audio cue plan tests + one packaged render smoke |
| 4 | focus/timeline packaging tests + one tutorial render anchor |
| 5 | local insert plan tests + one packaged insert anchor |
| 6 | highlight/multi-material candidate tests + one highlight anchor |
| 7 | API/UI mode contract tests |

## Anti-Overdesign Guardrails

The following are explicitly deferred unless a later runtime failure proves they are necessary:

- provider registry expansion;
- asset marketplace adapters;
- approval ledgers for paid generation;
- broad new schema families duplicating editorial/packaging/render-plan facts;
- full workflow builders or visual graph editors;
- replacing the current render kernel with Remotion or another compositor.

If a new proposal cannot be expressed as one of:

- capability policy;
- evidence/candidate producer;
- packaging-timeline extension;
- render/publication gate;

it is probably too broad for this round.

## Exit Condition For This Plan

This uploaded-material-only optimization round is complete only when:

1. the capability orchestration layer exists and is authoritative for mode-specific capability selection;
2. uploaded local assets can be indexed and consumed through shared contracts;
3. at least tutorial focus, local audio packaging, and local insert support are integrated without breaking the current `information_density` baseline;
4. highlight and light multi-material candidate support exist without introducing a second pipeline;
5. the UI/API surface exposes only compact high-level controls;
6. the deferred external-material/provider scope remains out of the mainline.
