# RoughCut Frontend Rebuild Design

**Date:** 2026-04-08

## Goal

Rebuild the RoughCut frontend into a user-facing editing console with five clear top-level destinations, aggressive removal of explanatory filler, and a unified visual system that feels like a director's control surface with a small amount of monitoring tension.

## Approved Direction

- Primary visual direction: director console
- Secondary visual influence: film monitor
- Navigation model: five top-level pages
- Tone: operational, cinematic, restrained, decisive

## Information Architecture

Top-level navigation is reduced to:

1. `总览`
2. `任务`
3. `监看目录`
4. `风格实验`
5. `设置`

The following current standalone pages lose top-level status:

- `PackagingPage`
- `StyleTemplatesPage`
- `CreativeModesPage`
- `CreatorProfilesPage`
- `MemoryPage`
- `GlossaryPage`
- `ControlPage`

## Page Responsibilities

### 总览

The overview page only answers:

- can the system continue running
- where is pressure or blockage right now
- which page the user should enter next

It must not act as a tutorial or a second settings page. It shows high-value runtime status, queue pressure, recent work requiring attention, and clear next actions.

### 任务

The jobs page becomes the primary working surface. It owns:

- task creation
- queue filtering
- selection
- review and detail overlays
- restart, cancel, delete, open-folder actions

The queue is the hero. Upload and defaults are still available, but they do not dominate the first screen.

### 监看目录

The watch roots page becomes a dedicated ingest surface. It owns:

- watch root health
- scan activity
- pending media inventory
- auto enqueue and merge visibility

It does not attempt to manage finished job output or duplicate job review.

### 风格实验

This page merges style templates, creative modes, and creator profiles into a single creative control surface. It owns:

- overall edit mood and output character
- subtitle, title, copy, cover defaults
- enhancement mode selection
- creator or avatar presentation defaults

It should feel like a selection and preview surface, not a wall of configuration prose.

### 设置

Settings absorbs packaging, memory, glossary, and system-wide provider or quality configuration. It owns:

- model and provider configuration
- output and packaging defaults
- memory and glossary behavior
- runtime and automation configuration
- secondary link to system control

## Removal Rules

The redesign must remove:

- page header summary cards that explain how to read the page
- repeated descriptions of section order
- developer-facing metadata exposed in the main sidebar
- duplicated system state repeated across multiple pages
- low-signal explanatory copy that does not help a user decide or act

The redesign must keep:

- status that changes current decisions
- actions that move the workflow forward
- warnings that prevent mistakes
- concise context for configuration sections when needed

## Visual System

### Layout

- Keep the left navigation rail, but simplify it to five destinations.
- Use a stronger page frame with fewer nested cards.
- Default to sections, strips, columns, and panels only when they contain a clear interaction unit.

### Color

- Base palette: charcoal, deep olive-black, warm graphite
- Accent palette: amber, brass, old-film gold
- Error or warning palette: restrained but sharper than the rest of the interface

### Typography

- UI body stays highly readable
- Brand and major headings gain more character
- `风格实验` is allowed to be slightly more editorial than the other pages

### Motion

- subtle entry transitions for main surfaces
- noticeable state-change emphasis for warnings and review-required states
- restrained modal and filter transitions

## Structural Merges

### New `风格实验`

Combines:

- `StyleTemplatesPage`
- `CreativeModesPage`
- `CreatorProfilesPage`

Recommended internal structure:

1. current creative direction
2. style preset families
3. enhancement capability toggles
4. creator or avatar defaults

### New `设置`

Absorbs:

- `PackagingPage`
- `MemoryPage`
- `GlossaryPage`

Keeps existing settings sections and adds a secondary entry into `ControlPage`.

## Implementation Constraints

- Preserve existing working backend contracts.
- Prefer route consolidation and page composition over sweeping API changes.
- Keep existing review overlays working during the redesign.
- Favor refactoring shared layout primitives over one-off page hacks.
- Maintain responsive layout on desktop and mobile.

## Success Criteria

- Users can scan the nav and understand the product shape immediately.
- Each top-level page has one primary purpose.
- The first screen of each page avoids tutorial-style filler.
- Style and creative configuration feel unified instead of fragmented.
- Settings becomes the home for system configuration instead of surfacing low-signal tool pages.
- Frontend visuals look intentionally art-directed rather than like a generic admin dashboard.
