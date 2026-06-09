# Engineering Principles

## Clarity

- State assumptions, ownership, interfaces, and acceptance criteria before parallel work.
- Report concrete evidence: files changed, commands run, observed behavior, and remaining risk.
- Surface ambiguity early when it could change architecture, data, or user experience.

## Pragmatism

- Solve the user-visible problem end to end.
- Prefer the existing architecture and libraries over unnecessary rewrites.
- Keep changes focused while addressing confirmed root causes.
- Build the usable product experience, not a placeholder or explanatory shell.

## Rigor

- Reproduce bugs before fixing them.
- Validate model output, file uploads, database data, and frontend rendering boundaries.
- Add regression coverage proportional to risk.
- Treat browser verification as required for meaningful frontend changes.
- Do not accept a passing build as proof that behavior or layout is correct.

## Collaboration

- Lead coordinates; specialists own assigned files.
- Avoid concurrent edits to the same file.
- Resolve shared contracts before implementation.
- QA challenges assumptions and reports findings by severity.
- No teammate silently broadens scope or rewrites another teammate's work.

## Safety

- Protect user data and local work.
- Never disclose secrets.
- Require confirmation for irreversible operations.
- Prefer reversible, reviewable steps and intentional commits.
