# SlimAgent Project Instructions

@.claude/user.md
@.claude/soul.md

## Project

SlimAgent is a Chinese-language fitness and nutrition application.

- Backend: FastAPI, SQLAlchemy async, SQLite, LangGraph, LangChain.
- Frontend: Vue 3, TypeScript, Vite, Element Plus, GSAP.
- AI: Alibaba Cloud DashScope compatible API.
- Text model: `qwen-plus`.
- Vision model: `qwen-vl-plus`.
- Image generation: DashScope Wanx.
- User-facing communication and product copy: Simplified Chinese.
- Internal instructions, plans, code comments, and agent coordination: English.

## Operating Mode

Use Claude Code Agent Teams in WSL with `in-process` display mode for substantial work.
The lead owns decomposition, file ownership, integration, final review, and acceptance.

Before feature development:

1. Inspect `git status`, recent commits, project structure, and relevant tests.
2. Audit the current implementation and reproduce reported issues.
3. Fix confirmed defects before extending the same feature area.
4. Preserve unrelated user changes and untracked media.

## Team Protocol

- Lead assigns every task and explicitly owns the final merge decision.
- Two teammates must never edit the same file concurrently.
- Lead assigns exactly one owner for database schema, shared TypeScript/Python types, and core configuration.
- Backend owns FastAPI, SQLAlchemy, database behavior, LangGraph, and backend tests.
- Frontend owns Vue, TypeScript, interaction behavior, accessibility, and responsive layout.
- AI/Vision owns DashScope integration, multimodal payloads, prompts, response parsing, and model fallbacks.
- QA/Reviewer reviews and tests by default. QA must notify Lead before making a fix and may edit only after Lead assigns ownership.
- Teammates report changed files, tests run, failures, and residual risks to Lead.
- Lead resolves cross-role contracts before parallel implementation begins.

## Autonomy

Agents may autonomously:

- Read and modify project code.
- Install required dependencies.
- Run tests and builds.
- Start local development services.
- Create Git branches using a clear task-oriented name.
- Modify database schemas after Lead assigns one owner and defines a migration/data-preservation plan.
- Decide UI details, API fields, and prompts when requirements leave them open.
- Create local commits after the verification gate below.

Do not automatically push, open a PR, merge, or change remote state. Ask the user first.

## High-Risk Confirmation Boundary

Ask the user immediately before:

- `git reset --hard`, force push, destructive rebases, or history rewrites.
- Deleting databases, uploaded user data, vector stores, or clearing database tables.
- Recursive deletion of a broad directory or removal outside the repository.
- Destructive schema migration without a verified backup or migration path.
- Any operation that could irreversibly discard user work or external data.

## Secrets

- Never print, echo, log, commit, summarize, or partially reveal API keys or tokens.
- It is acceptable to check whether a variable exists or is configured.
- Do not read `.env` into the conversation or include its values in command output.
- Prefer `.env.example` for configuration documentation.
- Redact secrets completely; do not expose prefixes or suffixes.

## Engineering Rules

- Read the relevant code before editing.
- Use existing project patterns and keep changes scoped.
- Find the root cause before fixing a bug.
- Validate files by content, not only by extension or client-provided MIME type.
- Treat LLM output as untrusted input: parse structured data, validate ranges, escape rendered HTML, and provide explicit fallbacks.
- Preserve Chinese text as UTF-8.
- Avoid silent exception handling. Log actionable context without secrets or full image payloads.
- Keep API contracts synchronized with frontend types.
- For schema changes, document compatibility and preserve existing data.

## Verification Gate

Before every commit:

1. Review `git diff` and `git diff --check`.
2. Confirm staged scope excludes secrets, local databases, uploads, build output, and unrelated files.
3. Run backend verification:
   - `cd backend && python -m compileall app tests debug_vision.py`
   - `cd backend && python -m unittest discover -s tests -v`
4. Run frontend verification:
   - `cd frontend && npm run build`
5. For UI changes, start local services and verify affected pages in a browser at desktop and mobile widths.
6. Check console errors, horizontal overflow, text overlap, loading/error/empty states, and primary interactions.
7. Review security-sensitive behavior, especially uploads, HTML rendering, logs, and secret handling.
8. Commit only when the implementation, visual result, interaction, and tests have been reviewed.

Do not claim completion based on prior test output. Use fresh evidence.

## Local Development

- Backend: `cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
- Frontend: `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173`
- Frontend URL: `http://127.0.0.1:5173`
- Backend URL: `http://127.0.0.1:8000`

If a port is occupied, reuse the existing project process or choose another port without terminating unrelated processes.

## Current Product Priorities

- Reliable food, meal, body-photo, and exercise-video multimodal analysis.
- Separate breakfast, lunch, dinner, and snack analysis with a daily calorie summary.
- Multi-view optional body analysis with persistent in-progress state.
- Correct separation of source food images and generated finished-meal images.
- Dietary alternatives and consolidated shopping lists.
- Responsive layouts without overlap or horizontal page overflow.
