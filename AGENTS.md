# AGENTS.md

Guidance for agents (Claude Code, Devin) working in this repository.
`CLAUDE.md` only imports this file.

**Git:** commit and push feature branches freely, then open a PR. Merging,
force-push, deleting branches and anything on `main` are the owner's. Commit
messages are 2 lines at most, with no trailer. One ticket = one PR.

## What this is

Pairprogrammer: a local app that gives the owner a spoken, slide-backed
briefing on a work item (Jira ticket) or a spec/plan. Work is tracked in Jira
project `PAIR` (epic PAIR-2 for v1: stack, acceptance numbers, failure modes).

Stack: FastAPI backend (Python 3.13, Poetry) and a Next.js + CopilotKit v2
frontend. Planned: OpenAI Realtime voice in the browser over WebRTC, a Claude
Agent SDK background agent over AG-UI, slides as A2UI surfaces.

## Layout

| Path | What |
|------|------|
| `backend/` | FastAPI app, package `pairprogrammer` in `src/`, tests in `tests/` |
| `backend/src/pairprogrammer/{jira,github}_client.py` | Read-only Jira and GitHub clients; `remote.py` holds the GET-only HTTP layer |
| `frontend/` | Next.js App Router app; `app/api/copilotkit/` is the CopilotKit runtime (no agents yet) |
| `Procfile` | `honcho start` runs both apps |
| `scripts/ci-local.sh` | Runs every check CI runs |
| `.env.example` | Env var names; copy to `.env` (git-ignored) |

The browser calls the backend through the Next.js rewrite `/backend/*` ->
`BACKEND_URL` (default `http://localhost:8000`), so there is no CORS setup.

## Jira and GitHub reads

`make_jira_client(env)` and `make_github_client(env)` are the factory seams
(tests pass an `httpx.MockTransport`; see `tests/fake_http.py`). Both build
clients on `read_only_client`, whose request hook raises `ReadOnlyViolation`
for anything but GET, and `ReadOnlyHttp` exposes only `get`. Every call
returns `RemoteResult(text, refs)` or `RemoteError(kind, ...)` (401, 403, 404,
rate limits, network errors, bad input); nothing raises into the agent.
Refs cite `jira:PAIR-7`, `jira:PAIR-7 (comment 10479)` or
`github:Fredheda/pairprogrammer#2`. Jira keys and JQL are confined to
projects PW, CKE, TA, PP, RR and PAIR; GitHub repos to `GITHUB_OWNER`.

## Commands

| Task | Command |
|------|---------|
| Run both apps | `honcho start` |
| All CI checks | `scripts/ci-local.sh` (last line `== all local CI checks passed`) |
| Backend tests | `cd backend && poetry run pytest` |
| Backend lint/format/types | `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run pyright` |
| Frontend tests | `cd frontend && npm test` (vitest, jsdom) |
| Frontend lint/types/build | `npm run lint`, `npm run typecheck`, `npm run build` |

## Practices

- Tests first: write and run the failing test before the code. Unit tests for
  logic, offline tests at the seams with fakes at factory functions (never
  network in tests), one browser test per user flow.
- Look up current library docs (Context7 or official docs); versions here are
  newer than model training data. For Next.js read `frontend/AGENTS.md` and
  the docs bundled in `frontend/node_modules/next/dist/docs/`.
- No secrets, keys, tokens, tenant or subscription IDs in the repo, logs, PRs
  or tickets. Add new env var names to `.env.example`.
- Keep docs (this file, `README.md`) current in the same PR.

## CI

`CI` (`.github/workflows/ci.yml`) runs on every PR and push to `main` with
jobs `backend` (ruff, ruff format, pyright, pytest) and `frontend` (eslint,
tsc, vitest, next build). Job ids are required-check names: keep them stable.
`scripts/ci-local.sh` mirrors the same commands; change both together.
