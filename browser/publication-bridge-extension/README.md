# RoughCut Publication Bridge Extension

This extension is the new shared browser transport for publication automation.

It does **not** unify platform flows. It only replaces the old `http://127.0.0.1:9222/json/*` browser attachment method with a real-Chrome bridge based on `chrome.debugger`.

## Install

1. Open Chrome with the real logged-in publication profile.
2. Open `chrome://extensions`.
3. Enable `Developer mode`.
4. Click `Load unpacked`.
5. Select this folder:

   `E:\WorkSpace\RoughCut\browser\publication-bridge-extension`

6. Keep Chrome running with the target logged-in profile.
7. Start `scripts/publication_browser_agent_service.mjs`.

## What it does

- Polls the local publication browser-agent service on `http://127.0.0.1:49310`.
- Enumerates real tabs from the active Chrome profile.
- Creates and closes tabs on request.
- Uses `chrome.debugger` to send CDP commands without relying on `--remote-debugging-port`.
- Forwards subscribed debugger events back to the service.
- In dev mode, checks the local target bridge version and reloads itself automatically after future updates.

## Scope

- Shared transport only.
- Platform-specific publication logic remains in the existing per-platform framework/executor paths.
