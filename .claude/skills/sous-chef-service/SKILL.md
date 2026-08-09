---
name: sous-chef-service
description: Start, monitor, stop, and restart the my-digital-sous-chef Telegram bot service. Use whenever the user asks to run/start/stop/restart the bot, check whether it is up, look at its logs, or diagnose an error it reported — and whenever a sous-chef log Monitor event or background-task exit notification arrives.
---

# Running the sous_chef service

All process control goes through `./scripts/sous-chef-ctl` — never invoke
`uv run --env-file .env python -m sous_chef` directly, or the PID, log, and
restart bookkeeping this skill depends on won't exist.

Subcommands: `run`, `stop`, `restart`, `status`, `logs [-n N]`, `errors`.
State lives in `.run/` (gitignored).

## Starting

Two steps, both required:

1. Launch the process as a **background task**:

   `Bash(command: "./scripts/sous-chef-ctl run", run_in_background: true)`

   It stays in the foreground of that task and owns the process group.
   It refuses to start if the service is already up — two pollers on one
   Telegram token produce 409 `getUpdates` conflicts that look like a real bug.

2. Arm a **persistent Monitor** on the log:

   ```
   Monitor(
     command: "tail -F .run/sous-chef.log | grep -E --line-buffered \
       'Traceback|ERROR|CRITICAL|Exception|agent turn failed|instructions turn failed'",
     description: "sous_chef errors",
     persistent: true,
   )
   ```

   `-F`, not `-f`: `run` rotates the log on every start, and `-f` would keep
   following the dead inode and go silent forever after the first restart.
   The grep is deliberately broad — a filter matching only known signatures
   goes quiet during an unfamiliar failure, and quiet is indistinguishable
   from healthy.

Confirm the start worked with `./scripts/sous-chef-ctl logs`. A healthy boot
shows python-telegram-bot's "Application started" line. **Nothing else is
printed when the bot is healthy** — silence afterward is normal, not a problem.

## Why the Monitor is the primary signal

`build_application` in `src/sous_chef/bot/app.py` registers no
`add_error_handler`, so python-telegram-bot catches handler exceptions, logs
them, and **keeps polling**. The most common failure therefore leaves the
process alive and the background task running — the log is the only place it
surfaces. Process exit is the secondary signal; it catches startup crashes
(`ConfigError` from a missing env var, `InvalidToken`).

## Reacting to alerts

**Background-task exit notification** — check for the stop sentinel first:

```
test -f .run/stopping && echo intentional
```

If present, the user asked for the stop. Clear it (`rm -f .run/stopping`) and
do nothing else. Do not restart.

**Monitor event, or an unexpected exit** — in order:

1. `./scripts/sous-chef-ctl errors` — the last traceback, falling back to the
   rolled `.log.1`.
2. Tell the user in plain language what failed, referencing the real cause,
   not just the exception name.
3. Decide whether to restart (below). Default is **diagnose, then restart**.

### Do not restart for these

`telegram.error.NetworkError`, `TimedOut`, and `RetryAfter`. PTB logs these at
ERROR during ordinary connectivity blips and recovers by itself. Report and
move on.

### Restarting

`./scripts/sous-chef-ctl stop`, confirm it reports `stopped`, then relaunch
step 1 and re-arm the Monitor from step 2.

**Cap: 3 restarts in 10 minutes.** The script has no idea a launch is a
restart, so this is yours to track — before each restart append a timestamp:

```
date -u +%Y-%m-%dT%H:%M:%SZ >> .run/sous-chef.restarts
```

and count entries inside the window first. On the 4th, stop and report instead
of restarting. A missing env var or bad token fails identically every attempt;
without the cap that is an infinite spin.

Mention when relevant: `agent/session.py` keeps per-chat conversation state in
memory only, so a restart discards any in-flight conversation by design.

## Known failure signatures

| Signature | What it means | Process survives? |
|---|---|---|
| `ConfigError` | missing or malformed env var (`SOUS_CHEF_*`, `ANTHROPIC_API_KEY`) — raised by `Settings.from_env()` before anything starts | no |
| `telegram.error.InvalidToken` | bad `SOUS_CHEF_TELEGRAM_TOKEN`, fails inside `run_polling()` | no |
| `telegram.error.BadRequest` in `on_callback` / `_send_meal_instructions` | MarkdownV2 escaping miss in a meal name; user sees a dead button | yes |
| `sqlite3.OperationalError: no such column` | schema drift in `sous_chef.db` (the cookbook `instructions` column has no migration) | yes |
| `agent turn failed` / `instructions turn failed` | caught agent error; the user got `AGENT_FAILURE_TEXT` and can retry | yes |
| nothing at all, for many minutes, mid-turn | `AnthropicTransport` sets no `timeout`/`max_retries` (`agent/client.py`), so one stalled turn can occupy ~30 min | yes |

## Stopping

`./scripts/sous-chef-ctl stop`. It signals the whole process group — `uv` is
the parent and `python` the child, so signaling the bare PID orphans the bot —
and escalates SIGINT → SIGINT → SIGTERM → SIGKILL, mirroring the manual
Ctrl-C-twice. It returns only once the group is confirmed gone.

Stop the Monitor too (`TaskStop`), or it keeps tailing a log nobody writes.
