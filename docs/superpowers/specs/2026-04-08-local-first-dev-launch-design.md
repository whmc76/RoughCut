# RoughCut Local-First Dev Launch Design

**Date:** 2026-04-08

## Goal

Make RoughCut's default development path local-first: local Python processes plus the local frontend, with Docker retained only for infrastructure (`postgres` / `redis` / `minio`) and explicit containerized runtime modes.

## Problem

The current launcher and docs still present Docker `runtime/full` as the recommended development path. In practice this creates ambiguity about which code is actually serving the UI and API, and stale runtime containers can silently mask newly merged local changes.

## Approved Direction

- Default user-facing launcher path stays `start_roughcut.bat` -> local mode
- Local mode is the primary development workflow
- Docker is recommended only for infrastructure or explicit containerized runtime sessions
- Existing `runtime/full` modes remain available, but they lose default/recommended status

## Behavioral Contract

- Running `start_roughcut.bat` must be described and treated as the primary development entrypoint.
- Running `start_roughcut.bat` should start local Python services and serve the locally built frontend.
- Running `start_roughcut.bat infra` remains the recommended way to get required backing services.
- Docker `runtime/full` remain explicit advanced modes for containerized runs, not the default development recommendation.
- Launcher help, README, and guardrail tests must all use the same local-first wording.

## Scope

### In Scope

- `start_roughcut.bat` help and command descriptions
- `start_roughcut.ps1` startup messaging and local-mode safeguards
- README quickstart and Windows launcher guidance
- launcher/documentation tests that currently encode Docker-first language

### Out of Scope

- Removing Docker runtime/full implementations entirely
- Reworking deployment compose files
- Replacing Docker for infra dependencies

## Success Criteria

- A developer reading the launcher help or README understands that daily development should start locally.
- Local startup no longer gets confused with an already-running Docker runtime.
- Tests fail if docs or help text drift back to presenting Docker runtime/full as the default dev workflow.
