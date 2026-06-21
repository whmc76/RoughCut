# Open Source Release Checklist

This checklist covers the steps that still matter after the working tree has
already been cleaned and de-identified.

## 1. Freeze the release candidate

- Stop adding new private task notes, local evidence, or creator data to the
  branch you plan to publish.
- Commit the final open-source cleanup before any history rewrite. A mirror
  rewrite only sees committed history, not your uncommitted worktree edits.
- Run the local audits from the repo root:

```bash
python scripts/check_open_source_readiness.py
python scripts/check_agent_docs.py
```

- Treat those audits as a worktree gate, not a commit-history gate. If a tracked
  private file is only deleted in the working tree but not committed yet, the
  scan can pass while `HEAD` still contains the sensitive file.
- `check_open_source_readiness.py` now defaults to `--scope both`, which scans
  both the current worktree and the committed `HEAD` snapshot. Use
  `--scope worktree` only as a temporary cleanup aid while you are still
  deleting or replacing tracked files before the final commit.

- Run the narrow regression suite that covers publication/config/path
  normalization:

```bash
PYTHONPATH=src python -m pytest \
  tests/test_file_manager.py \
  tests/test_publication.py \
  tests/test_avatar_materials_publication_profiles.py \
  tests/test_publication_mainline.py \
  tests/test_runtime_preflight_docker_defaults.py -q
```

## 2. Prepare local history rewrite inputs

- Copy these templates into a local ignored directory such as
  `.tmp/open-source-history/`:
  - `scripts/open_source_history/paths.example.txt`
  - `scripts/open_source_history/replace-text.example.txt`
- Fill in:
  - every path that must disappear from history
  - every literal string that must be replaced in history

Do not commit the filled-in local files.

## 3. Rewrite history in a mirror

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rewrite_open_source_history.ps1 `
  -SourceRepo . `
  -WorkDir .\.tmp\open-source-history-run `
  -PathsFile .\.tmp\open-source-history\paths.txt `
  -ReplaceTextFile .\.tmp\open-source-history\replace-text.txt
```

By default the script stops if the source repo still has uncommitted changes.
That is intentional: rewriting history from a dirty worktree is a common way to
miss the latest sanitization edits.

Expected outputs:

- mirror repo: `.tmp/open-source-history-run/mirror.git`
- validation checkout: `.tmp/open-source-history-run/checkout`

The rewrite is not complete until the validation checkout is scanned again with
`python scripts/check_open_source_readiness.py` or an equivalent targeted grep.
The rewrite helper now runs `scripts/check_open_source_readiness.py --scope both`
automatically inside the validation checkout when that audit script exists.

## 4. Rotate credentials outside Git

History rewrite removes credentials from Git. It does not make an already
exposed credential safe again.

Rotate anything that ever appeared in:

- `.env`
- committed config files
- browser-agent auth payloads
- local helper scripts
- old task docs or screenshots that were committed in the past

Track the work in a local copy of:

- `scripts/open_source_history/secret-rotation.example.md`

Minimum rotation targets usually include:

- OpenAI / Anthropic / MiniMax / Zhipu / Ollama proxy credentials
- browser-agent auth tokens
- Telegram bot tokens
- third-party publish/upload credentials
- cloud storage credentials

## 5. Replace the remote history

Only do this from the rewritten mirror after validation is clean.

Example:

```powershell
cd .\.tmp\open-source-history-run\mirror.git
git remote -v
git push --force --all origin
git push --force --tags origin
```

If the hosting provider keeps cached views or security alerts tied to old SHAs,
follow the provider’s sensitive-data removal procedure as well.

## 6. Coordinate with collaborators

Anyone with an old clone must either:

- discard the clone and re-clone, or
- perform a full local cleanup against the rewritten history

Do not let teammates keep pushing from pre-rewrite clones.

## 7. Verify the published repository

After the force-push:

- clone the public repo into a brand-new directory
- rerun `python scripts/check_open_source_readiness.py`
- grep for old creator names, browser profile ids, local paths, and secret
  prefixes
- open `.env.example`, `README.md`, and `docs/design/INDEX.md` and verify they
  still describe a generic install path rather than one machine

## 8. Final gate

Do not announce the repo publicly until all are true:

- working tree audit is clean
- rewritten mirror audit is clean
- remote history is replaced
- exposed credentials are rotated
- collaborators are told to re-clone
