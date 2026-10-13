# Logs and metrics

A workspace made from this template keeps three JSON files in its root. Hooks write them; Claude
can read them but is blocked from editing them, and `.gitignore` keeps them out of the workspace
repo. The files in this folder are small synthetic samples (made-up sessions, apps, and models)
so you can see the shape before running anything.

| File | Written by | Answers |
|------|------------|---------|
| [`sessions.json`](sessions.json) | `log_event.py` on SessionStart, UserPromptSubmit, PostToolUse, PostToolUseFailure, Stop, SubagentStop, PreCompact, SessionEnd | What happened in each session? |
| [`registry.json`](registry.json) | `log_event.py` on the same events | What do we use, how often, and where does it fail? |
| [`errors.json`](errors.json) | `log_event.py` on PostToolUseFailure and StopFailure, plus `log_issue.py` | What broke, and is it fixed? |

All three are pretty-printed, written atomically under a lock file (parallel tool calls fire
hooks at the same time), and carry a `schema_version`. If a file is ever unreadable it is moved
aside as `<name>.corrupt-<timestamp>.json` and a fresh one is started.

## sessions.json

One record per Claude Code session, keyed by session id.

| Field | Meaning |
|-------|---------|
| `status`, `started_at`, `ended_at`, `duration_minutes` | Session lifetime. `active` until SessionEnd. |
| `start_source`, `end_reason` | How it started (`startup`, `resume`, `clear`, `compact`, `fork`) and why it ended. |
| `title` | The session title, if one was set. |
| `cwd`, `git_branch`, `entrypoint`, `permission_mode`, `effort` | Context the hooks receive or read from the transcript. |
| `claude_code_versions`, `models` | Versions seen and API requests per model, read from the transcript. |
| `prompts` | Number of prompts. Prompt text is never stored. |
| `tool_calls`, `tool_failures`, `interrupts`, `compactions` | Counters. |
| `tools`, `subagents`, `apps` | Calls per tool, subagent invocations, and calls per app (`workspace` for root-level work). |
| `tokens.main`, `tokens.subagents` | Input, output, cache-read, and cache-write tokens, counted once per API request. |
| `transcript` | Bookkeeping so each scan reads only the bytes added since the last one. |

## registry.json

Running totals across all sessions.

| Field | Meaning |
|-------|---------|
| `totals` | Sessions, tool calls, tool failures. |
| `tools` | Per tool: calls, failures, total and average duration, first and last seen. |
| `mcp_servers` | Per MCP server: calls, failures, and calls per server tool. |
| `subagents` | Per subagent type: invocations, failures, and the model each ran on. |
| `models`, `claude_code_versions` | Which models and Claude Code versions the team actually ran, and when. |
| `apps` | Tool calls and failures per app. |
| `recent_tool_calls` | The last 200 calls: time, session, tool, success, duration, app, subagent, and a short redacted summary of the input. |

## errors.json

An issue log with ids (`ERR-0001`, ...), a status, and a summary block.

| Field | Meaning |
|-------|---------|
| `kind` | `tool_failure` and `api_failure` come from hooks; anything else (`bug`, `flaky-test`, `config`, `follow-up`, ...) is logged by hand. |
| `severity` | `low`, `medium`, `high`, `critical`. Hook-logged tool failures are `low`; authentication and billing API errors are `high`. |
| `source` | `hook:PostToolUseFailure`, `hook:StopFailure`, or `manual`. |
| `title`, `details`, `app`, `session_id`, `agent`, `tool_name`, `tool_input` | What and where. Text is clipped and redacted. |
| `status`, `resolved_at`, `resolution` | Set by `log_issue.py resolve`. |

Interrupted tool calls (the user pressed Esc) are counted in the session but not logged as errors.

```bash
python .claude/hooks/log_issue.py add "Checkout test depends on wall-clock time" \
  --details "fails 23:00-00:00 UTC" --severity high --app example-web --kind flaky-test
python .claude/hooks/log_issue.py list            # open issues
python .claude/hooks/log_issue.py list --all      # include resolved
python .claude/hooks/log_issue.py resolve ERR-0003 --resolution "Froze the clock in the test"
```

## Redaction

Before anything is written, strings that look like credentials are replaced with `[REDACTED]`:
private key blocks, GitHub tokens, Anthropic and other `sk-` keys, payment provider keys and
webhook secrets, AWS access key ids, Google API keys, Slack tokens, JWTs, bearer tokens,
passwords in connection URLs, and `password=` / `token:` / `api_key=` style assignments.
Redaction is pattern-based, so treat it as a safety net, not a guarantee: the files stay local
and gitignored for that reason.

## Using the data

The files are plain JSON, so `jq`, Python, or a spreadsheet import is enough. A few questions
they answer:

- Which apps generate the most tool failures this month? (`registry.json` > `apps`)
- Is the `code-reviewer` agent actually being used before commits? (`registry.json` > `subagents`)
- Which Claude Code versions are people on? (`registry.json` > `claude_code_versions`)
- How much cache-read traffic does a typical session use? (`sessions.json` > `tokens`)
- What's still open? (`log_issue.py list`)

```bash
jq '.apps | to_entries | sort_by(-.value.tool_failures) | .[:3]' registry.json
jq '[.sessions[] | .tokens.main.output] | add' sessions.json
```
