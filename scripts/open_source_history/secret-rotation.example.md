# Secret Rotation Checklist

Copy this file into a local ignored workspace and replace the example rows with
your actual credentials and owners.

| Service | Credential | Rotation Owner | Status | Notes |
| --- | --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | owner@example.com | pending | Rotate in provider console, update `.env` only |
| MiniMax | `MINIMAX_API_KEY` | owner@example.com | pending | Check any shared automation runners |
| Zhipu | `ZHIPU_API_KEY` | owner@example.com | pending | Verify MCP/helper paths after rotation |
| Browser Agent | `PUBLICATION_BROWSER_AGENT_AUTH_TOKEN` | owner@example.com | pending | Restart service after update |
| Telegram | `TELEGRAM_BOT_TOKEN` | owner@example.com | pending | Re-issue webhook/session if needed |
| Storage | `S3_SECRET_ACCESS_KEY` | owner@example.com | pending | Verify upload workers after change |
