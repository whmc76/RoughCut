# Codex Publication Incident 2026-06-05

## Incident

During the Bilibili publication closure work, the agent repeatedly returned to the already diagnosed duplicate-upload problem instead of advancing the current open blockers: Bilibili cover upload, collection selection, and schedule. This consumed time without moving the active publish path forward.

## Observed Symptom

- The user repeatedly stated that the duplicate-upload root cause had already been found.
- The current Bilibili page already had a normal uploaded draft, but the agent continued to inspect upload behavior.
- The agent re-explained stale conclusions instead of executing the next current-page project.

## First Bad Layer

The failure happened at the agent workflow layer, before platform automation logic:

- No durable per-platform issue ledger existed.
- Resolved issues were not protected from being reopened by stale logs or old screenshots.
- The agent did not treat "current page already has the intended draft" as a terminal state for the upload project.

## Root Cause

The active task state was implicit in conversation context instead of explicit in a local source of truth. After long context, interruptions, and multiple similar Bilibili artifacts, the agent confused:

- a resolved root cause: duplicate upload path;
- stale page states and old artifacts;
- the current page state: a valid Bilibili uploaded draft waiting for cover, collection, and schedule.

This caused repeated work on an old blocker.

## Why It Surfaced Now

Bilibili had several visually similar states:

- stale duplicate draft pages;
- normal uploaded draft page;
- cover editor modal;
- draft resume prompt;
- notification prompt.

Without an explicit issue ledger and terminal-state rule, the agent kept treating old evidence as live evidence.

## Correct Behavior Going Forward

- Maintain an issue ledger per platform during publication work.
- Mark duplicate upload as resolved after the upload path root cause is fixed and verified.
- Do not revisit resolved issues unless fresh live evidence shows the current script version still creates the issue.
- When the current Bilibili page has the intended uploaded draft, the upload project is complete.
- Continue only with the next current-page projects: cover, collection, schedule, final verification.

## Persistent Fix

The repository now has root-level Codex operating rules in `AGENTS.md`. These rules require:

- page truth over stale artifacts;
- a per-platform issue ledger;
- resolved issue protection;
- project terminal states;
- single Bilibili upload path;
- Bilibili `16:9` cover asset for the current chain;
- Bilibili collection from creator/content strategy.

## Residual Risk

This does not by itself complete Bilibili automation. It prevents the agent from repeating the same resolved-problem loop. The remaining implementation work is to execute and then harden the Bilibili current-page projects:

- upload the finished `16:9` cover through the modal `上传封面` area;
- select `EDC刀光火工具集`;
- set schedule from the existing publishing strategy;
- stop before final publish unless explicitly instructed otherwise.
