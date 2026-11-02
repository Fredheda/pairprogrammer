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
| `frontend/` | Next.js App Router app; `app/api/copilotkit/` is the CopilotKit runtime, `lib/agent.ts` registers the backend agent |
| `Procfile` | `honcho start` runs both apps |
| `scripts/ci-local.sh` | Runs every check CI runs |
| `.env.example` | Env var names; copy to `.env` (git-ignored) |

The browser calls the backend through the Next.js rewrite `/backend/*` ->
`BACKEND_URL` (default `http://localhost:8000`), so there is no CORS setup.

The background agent is a `ClaudeAgentAdapter` (`backend/src/pairprogrammer/agent.py`)
served over AG-UI at `POST /agent`. The CopilotKit runtime reaches it server-side at
`${BACKEND_URL}/agent` through an `HttpAgent`. The agent ID `pairprogrammer` must match in
`agent.py`, the runtime's `agents` map and `<CopilotKitProvider agentId>`.

`agent.agent_options(*fragments)` is the only place that builds `ClaudeAgentOptions`:
model, `tools=[]`, `strict_mcp_config`, `permission_mode="dontAsk"`, no setting sources
and `max_turns=MAX_TURNS`. Features add tools, roots or hooks as an `OptionsFragment`
(an object with `apply(options) -> options`) passed to `agent_options` / `make_adapter`.

The adapter is a process singleton that keeps one Claude CLI worker per AG-UI thread in
memory, so run the backend as a single uvicorn worker (no `--workers N`), or threads lose
their state between requests.

Agent tests install `tests/fakes.py:FakeClaudeClient` through
`install_fake_claude_client` (no network). The adapter takes no client factory; it looks
up `claude_agent_sdk.ClaudeSDKClient` when a thread's worker starts, and a test fails if
an `ag-ui-claude-sdk` upgrade changes that. `@ag-ui/client` is pinned to the exact
version CopilotKit pins, so only one copy is installed.

## Commands

| Task | Command |
|------|---------|
| Run both apps | `honcho start` |
| All CI checks | `scripts/ci-local.sh` (last line `== all local CI checks passed`) |
| Backend tests | `cd backend && poetry run pytest` |
| Backend lint/format/types | `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run pyright` |
| Frontend tests | `cd frontend && npm test` (vitest, jsdom) |
| Frontend lint/types/build | `npm run lint`, `npm run typecheck`, `npm run build` |

`frontend/package.json` overrides `zod` to `^4.6.6`: CopilotKit 1.83 and `@ag-ui/*`
pin zod 3, which has no fix for GHSA-mrhx-c7xc-m3w5. Remove the override once
CopilotKit ships on zod 4 (PAIR-18). Keep `@copilotkit/react-core` and
`@copilotkit/runtime` on the same version, never override `@ag-ui/*`, and after
any dependency change check that `npm ls @copilotkit/react-core @ag-ui/client zod`
shows one version each, then run `npm run build`. A2UI catalogs import from `zod/v3`.

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
`scripts/ci-local.sh` mirrors the same commands plus the blocking security
checks (needs `gitleaks`, `actionlint` and `uv` on the PATH); change them
together.

`Security` (`.github/workflows/security.yml`) runs on PRs, weekly and on
demand: `gitleaks` (PR commits; full history otherwise) and `workflow-lint`
(actionlint) on every push, `bandit`, `pip-audit`, `npm-audit` and `codeql`
once a PR is ready. Required on `main`: `backend`, `frontend`, `gitleaks`,
`workflow-lint`, `bandit`. The audits are advisory on PRs and fail the weekly
run. Dependabot (`.github/dependabot.yml`) proposes weekly grouped
minor/patch updates for backend, frontend and actions, 14 days after release.

## PR review

`Claude Review` (`.github/workflows/claude-review.yml`) reviews each ready PR
and every push to it; the owner can comment `@claude` for a follow-up. It only
comments (no approve, merge or push), skips drafts, forks, Dependabot and every
bot except Devin (`devin-ai-integration[bot]`) and Claude (`claude[bot]`), and
skips itself on a PR that changes the workflow file. Do not make it a required
check.

- Auth: repo secret `CLAUDE_CODE_OAUTH_TOKEN` (owner: `claude setup-token`,
  then `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo Fredheda/pairprogrammer`).
  Tokens last about a year; expiry: _record the date here when the token is
  created_. Fallback if subscription auth is refused:
  `anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}` in both jobs.
- Public repo: `main` takes changes only through PRs (ruleset `main-protect`).
