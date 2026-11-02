# Pairprogrammer

A local web app that replaces reading tickets, specs and plans with a short
spoken briefing: an agent explains a work item or a spec/plan as full-screen
slides with captions in at most 4 minutes, answers interruptions in 2-3
sentences, and grounds every claim in the work item, its linked docs and the
repo. v1 is read-only and runs locally only.

## Quick start

Prerequisites: Python 3.13, [Poetry](https://python-poetry.org/) 2, Node 26
(`.nvmrc`), [honcho](https://github.com/nickstenning/honcho)
(`pipx install honcho`).

```bash
cp .env.example .env                          # optional: change ports
(cd backend && poetry install)
(cd frontend && npm ci)
honcho start                                  # backend :8000, frontend :3000
```

Open http://localhost:3000; the page shows `Backend: ok` when the backend is up.

## Checks

```bash
scripts/ci-local.sh                           # everything CI runs
```

See [AGENTS.md](AGENTS.md) for layout and per-app commands.
