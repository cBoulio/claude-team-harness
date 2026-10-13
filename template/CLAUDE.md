# {{WORKSPACE_NAME}}

{{WORKSPACE_NAME}} is a shared workspace for managing several applications with Claude Code. Each
app lives in `apps/<app-name>/` and keeps its own git repo, stack, and `CLAUDE.md`. Everything in
the root `.claude/` directory (agents, skills, hooks, settings) applies across all apps.

## Layout

- `apps/`: one directory per application. Each app is its own git repo; the workspace repo ignores them.
- `apps/REGISTRY.md`: index of every app with stack, purpose, and status. Keep it current.
- `.claude/agents/`: shared subagents (app-explorer, code-reviewer, debugger, test-runner, researcher).
- `.claude/skills/`: shared workflows (`/onboard-app`, `/app-status`).
- `.claude/hooks/`: scripts that run on tool calls for every app (guards, logging, research rendering).
- `.claude/settings.json`: shared permissions and hook wiring. Personal overrides go in
  `.claude/settings.local.json` (gitignored).
- `scripts/add-app.py`: clone or create an app under `apps/` and add its registry row.
- `research/docs/` and `research/site/`: research dossiers and their rendered HTML.

## App registry

@apps/REGISTRY.md

## Working across apps

- Before changing an app, read its `apps/<app>/CLAUDE.md`. App-level rules override these workspace rules.
- Stay inside the app you were asked to work on. Don't edit another app as a side effect; if a
  change is needed elsewhere, say so.
- Run git commands from inside the app (`git -C apps/<app> ...`), since each app is its own repo.
- Use the app's own tooling (package manager, test runner, formatter) as documented in its
  `CLAUDE.md`. Don't assume one stack for every app.
- When an app is added, removed, or changes status, update `apps/REGISTRY.md`.
- Run an app's tests before calling a change done. Use the `code-reviewer` agent before committing.

## Logs and issues

Hooks (`.claude/hooks/log_event.py`) write three JSON files in the workspace root. They're
gitignored and blocked from direct edits:

- `sessions.json`: one record per session (start/end, Claude Code version, models, prompt count,
  tool calls, failures, subagents, apps touched, token usage).
- `registry.json`: running totals for tools, MCP servers, subagents, models, Claude Code
  versions, and apps, plus the last 200 tool calls.
- `errors.json`: tool failures and API errors (logged automatically) plus issues logged by hand.

When you find a problem worth tracking (a bug, broken config, flaky test, or follow-up), log it:
`{{PYTHON}} .claude/hooks/log_issue.py add "<title>" --details "<what and where>" --severity <low|medium|high|critical> --app <app>`.
Resolve it when fixed: `{{PYTHON}} .claude/hooks/log_issue.py resolve ERR-0007 --resolution "<how>"`.
List open issues: `{{PYTHON}} .claude/hooks/log_issue.py list`. Secrets are redacted before anything is written.
If a hook itself breaks, details go to `.claude/hooks/hook-errors.log`; hooks never block a session on their own bugs.

## Research

- `research/docs/`: dossiers in markdown (front matter: title, date, author, status, tags, summary).
- `research/site/`: generated HTML. Open `research/site/index.html` in a browser.
- Writing or editing a doc in `research/docs/` triggers `.claude/hooks/render_research.py`, which
  rebuilds that page and the index. Rebuild everything with `{{PYTHON}} .claude/hooks/render_research.py --all`.
- Use the `researcher` agent for research meant to be kept. Callouts: `> [!VERDICT]`, `> [!RISK]`,
  `> [!WARNING]`, `> [!TIP]`, `> [!NOTE]`.

## Team conventions

Edit this section to match your team.

- Never commit secrets. `.env` files stay local; use `.env.example` for templates.
- Prefer small, reviewable changes.
- Don't commit or push unless asked.
- Default stack for new apps: _fill in (language, hosting, data store)_.
- Environment: _fill in (OS, shells, runtime versions)_.
