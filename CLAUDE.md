# claude-team-harness

This repo is a **template**. `template/` is what `scripts/init.py` copies into a new workspace;
nothing in `template/` runs against this repo itself.

## Layout

- `template/`: the workspace skeleton (`CLAUDE.md`, `apps/REGISTRY.md`, `.claude/` agents, skills,
  hooks, settings). `template/_gitignore` becomes `.gitignore` on init; it is named that way so its
  `apps/*` and `research/site/` rules don't hide template files in this repo.
- `scripts/init.py`: create a workspace. `scripts/add-app.py`: add an app to one (copied into
  each workspace). `scripts/render-examples.py`: rebuild the sample research site.
- `examples/`: sample dossier and its rendered site, plus synthetic log files and the logs explainer.
- `docs/`: GitHub Pages copy of the rendered sample site.
- `tests/`: pytest suite; hooks are exercised as subprocesses inside a freshly initialized workspace.

## Commands

- Set up: `python -m venv .venv` then `.venv/Scripts/python -m pip install "pytest>=8"`
  (`.venv/bin/python` on macOS/Linux).
- Test: `python -m pytest` (from the venv).
- After changing the renderer or the sample dossier: `python scripts/render-examples.py`
  (a test fails if `examples/research/site` or `docs/` is stale).
- Try it end to end: `python scripts/init.py <tmp-dir> --no-git`.

## Rules

- Hooks and scripts use the Python standard library only and must run on Windows, macOS, and
  Linux with Python 3.10+.
- Hooks fail open: a logging or rendering bug exits 0; guards exit 2 only for a deliberate block.
  Keep it that way and add a test for any new failure path.
- Follow the current Claude Code hooks contract (stdin JSON with `hook_event_name`,
  `tool_name`, `tool_input`, ...; exit 2 blocks PreToolUse; `hookSpecificOutput` for context).
  Check https://code.claude.com/docs/en/hooks before relying on a field.
- Placeholders in `template/` are `{{WORKSPACE_NAME}}` and `{{PYTHON}}`; `init.py` fills them and
  a test checks none are left.
- No personal or company data anywhere: examples use fictional apps such as `apps/example-api`,
  and sample logs are synthetic. Build credential-shaped test strings at runtime (`fake_secret`).
- Plain writing in docs. No emojis.
