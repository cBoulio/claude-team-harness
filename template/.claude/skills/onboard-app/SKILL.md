---
name: onboard-app
description: Bring an existing app into the workspace - clone or copy it into apps/<name>/, map it, write its CLAUDE.md, and add it to the registry. Use when someone wants to pull an existing repo or local project into the workspace.
---

# Onboard an app

Input: a git URL (`https://github.com/<org>/<repo>.git`) or a local path, plus an optional name.
Default the name to the repo or folder name in kebab-case.

1. **Get the code into `apps/<name>/`**
   - Git URL: `python scripts/add-app.py <name> --repo <url> --stack "<stack>" --purpose "<purpose>"`.
     This clones the repo and adds the registry row. Use `?` for stack or purpose if unknown and
     fill them in after step 2.
   - Local path: ask whether to **copy** (original stays put) or **move** it. Copy without build
     output and dependencies (`node_modules`, `.venv`, `venv`, `dist`, `build`, `bin`, `obj`):
     `robocopy <src> apps\<name> /E /XD node_modules .venv venv dist build bin obj` on Windows,
     `rsync -a --exclude node_modules --exclude .venv --exclude dist --exclude build <src>/ apps/<name>/`
     elsewhere. Never delete the original yourself. Then add the registry row by hand.
   - If `apps/<name>` already exists, stop and ask.
2. **Map it**: launch the `app-explorer` agent on `apps/<name>/`.
3. **Check git**: if it isn't a git repo, say so and offer `git -C apps/<name> init -b main`.
   If there's no remote, offer to create one under the team's organization. Don't push without asking.
4. **Write `apps/<name>/CLAUDE.md`** from the explorer report (if one exists, offer to update it):
   - One-line purpose, stack, and status.
   - Commands: install, dev, test, build, deploy.
   - Key directories and entry points.
   - Required env vars (names only) and where they're configured.
   - Known issues or rot found during exploration. Log anything worth tracking with
     `python .claude/hooks/log_issue.py add "<title>" --app <name> --severity <level>`.
5. **Update `apps/REGISTRY.md`**: make sure the row exists and stack, purpose, and status are accurate.
6. Summarize: what was found, what's broken or outdated, and suggested next steps.
