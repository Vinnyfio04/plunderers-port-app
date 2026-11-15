# Standing instructions for coding agents

## Scope and review

- Work inside this project root: `C:\Users\Owner\Desktop\School Work\5 Fall 2026\IST 402 - Vibe Coding\live-market-workplace`.
- Inspect the relevant files, directory contents, and Git status before editing.
- Preserve existing student work and keep changes limited to the current task.
- Show the proposed or completed changes for student review before making a commit. Do not commit unreviewed work.
- Reuse the installed Python environment. Do not create or recreate a virtual environment by default.
- The production store is `backend/data/market.db`; use the central database module and versioned migrations. Preserve the legacy recovery copy and all account/decision IDs. Use a separate `MARKET_DATABASE` for fixtures, one Uvicorn worker, and the backend-owned collector. Keep full history scans out of normal tick/chart-update paths.

## Prompts, results, and secrets

- Save each major prompt in `prompts/`, retaining the existing numeric sequence.
- Record the prompt's observed results, including failed and passing checks, in `docs/verification.md`.
- Keep credentials, API keys, tokens, and other secrets out of source code, prompts, logs, screenshots, and Git.
- Use environment variables or an ignored local secrets file when credentials are eventually needed. Commit only a redacted example file.
- Use `docs/assignment_instructions.md` as the Part 4.1 acceptance reference. Label CSV and constructed feed evidence separately from actual Yahoo observations. Do not call live streaming complete until one regular-session source message is matched to its SQLite record, backend candle, WebSocket update, and visible chart result.

## Tool and dependency procedure

Use this procedure whenever a tool or package is needed.

### CHECK

1. Inspect the operating system and the intended runtime environment.
2. Check the active Python interpreter, Node.js, package managers, dependency manifests, and lockfiles.
3. Verify whether the required tool or package is already available.
4. Reuse the existing Python environment; do not create a new environment by default.

### TAKE ACTION

For every missing dependency needed by the current task, explain before installation:

- its purpose;
- the compatible version or version range;
- the exact installation command;
- the installation target (system, user, or project environment); and
- every manifest, lockfile, or other project file the action will create or change.

Obtain student approval before installing software or creating/changing a dependency manifest or lockfile. Do not bundle unrelated dependencies into the request.

### VERIFY

1. Run the smallest relevant version, import, startup, or build check in the intended environment.
2. Record the command, expected result, and observed result in `docs/verification.md`.
3. Identify any check that remains unrun and why.
4. Update README startup commands only after those commands have passed.

## SmokeTest

`SmokeTest` is a repeatable check that runs without source edits.

- Before a UI exists, it should exercise the smallest meaningful backend or integration path.
- Once a feature has a UI, it must start the required local services, open a browser, perform a real user operation, and compare the visible result with the expected result.
- Check stored data when the operation is expected to persist or update data.
- Document one command that runs the complete SmokeTest.
- Run the current offline browser SmokeTest with `node scripts/smoke-test.mjs` from the project root. It starts and stops its own local services and browser.
- Record failures as well as passes in `docs/verification.md`.

## AutoLoop

`AutoLoop` means:

1. Inspect a failed check and identify the narrowest likely cause.
2. Make the smallest in-scope correction.
3. Rerun the same check without weakening it.
4. Stop when the check succeeds, after five correction cycles, or when further progress requires student permission.

Record each cycle and its result in `docs/verification.md`.

## Product safeguards

- Treat agent output as decision support, not guaranteed financial advice or an automatic order instruction.
- Make data timestamps, source, delay, uncertainty, and error states visible when those features are implemented.
- Never enable live trade execution without an explicit, separately reviewed requirement and appropriate safeguards.
