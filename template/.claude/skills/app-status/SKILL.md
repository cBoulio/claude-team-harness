---
name: app-status
description: Summarize the state of every app in the workspace - git branch, uncommitted changes, ahead/behind remote, last commit, registry status, and open issues. Use when someone asks what's going on across the apps or what needs attention.
---

# App status

For each directory in `apps/` (skip `REGISTRY.md`):

1. If it's a git repo, collect:
   - `git -C apps/<app> branch --show-current`
   - `git -C apps/<app> status --porcelain` (count of changed files)
   - `git -C apps/<app> fetch --quiet`, then `git -C apps/<app> rev-list --left-right --count HEAD...@{u}`
     (ahead/behind; skip if there's no upstream or the fetch fails)
   - `git -C apps/<app> log -1 --format="%cr - %s"`
2. If it's not a git repo, note that.
3. Compare against `apps/REGISTRY.md`: flag apps missing from the registry, and registry rows
   whose directory is gone.
4. Count open issues per app with `python .claude/hooks/log_issue.py list --app <app>`.

Output one table: app | branch | uncommitted | ahead/behind | last commit | open issues | registry status.
Below it, list only what needs attention (uncommitted work, unpushed commits, behind remote,
registry mismatches, high or critical open issues). Don't change anything.
