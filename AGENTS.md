# Agent rules

## Writing
- Plain, terse language. No emojis, no marketing tone.
- Keep within the length asked for; prioritize, most important first.
- Rank options by value against effort; size work as S/M/L.
- When asked for a review only, do not change code, commit or open PRs; deliver the report.

## Evidence
- Back every claim with evidence: file:line, command output or a screenshot. Run the thing; do not guess.
- Read the project docs (README, design notes, mockups) before the code.
- Treat the owner's assumptions and "out of scope" decisions as questions to answer honestly, not as givens.
- Look at screenshots yourself before reporting on them; send only the few that show the point.

## UI checks
- Screenshot the main pages and states: hover, selection, search, empty and error states.
- Light and dark themes, device scale 1 and 2, and a narrow viewport (about 1000 px).
- Write browser automation scripts to files, not inline shell.

## Environment
- Use the preinstalled browser; do not reinstall browser tooling.
- Stop servers by port (`fuser -k <port>/tcp`), never by pattern (`pkill -f`).
- Use synthetic or test data when the real backend is unreachable.

# From corrections in this session

## Commits and PRs
- Commit message: short subject, terse bullets, then one `Assisted-by:` trailer naming the agent and model in use. The owner is the author and committer; never `Co-Authored-By` with an agent, no session links, no "Generated with" lines.
- PR: short title; body of terse bullets grouped under plain labels (Map, Search, Other); no headings, footers, links or emojis.
- After posting a PR or comment, read it back and remove anything a tool appended.
- Keep history linear: branch from the current default branch, no merge commits.
- One commit per development cycle; run the test suite before each commit.
- No breaking changes without asking: new settings optional, data formats only gain fields.
- Rewriting history or force-pushing needs explicit approval.

## Domain
- Do not adopt upstream conventions blindly: when a reference tool's semantics look wrong (e.g. container utilization), ask or follow the owner's definition.

# This project

- Lint: `make lint` (flake8, also in CI).
- Tests: `make test`, or `.venv/bin/python -m pytest -q`. Browser tests need Chromium; set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` when it is not where Playwright looks. Tests run offline on `tests/synthetic_data.py`.
- Demo data: `OUTPUT_DIR=<dir> .venv/bin/python -c "from app.cli import full_update; from tests.synthetic_data import FakeNetboxManager; full_update(mgr=FakeNetboxManager())"`, then `OUTPUT_DIR=<dir> INITIAL_UPDATE=0 NETBOX_API_URL=https://netbox.example.com .venv/bin/python -m app.webapp` (port 5000, base path /prefix-map). The server caches templates: restart it after template changes.
- Bump `RENDER_VERSION` in `app/cli.py` when drawing code changes.
- Keep in step with code changes: `docs/design.md`, the Help page (`templates/help.html`), `README.md` and `README.ru.md`.
- README screenshots: `docs/img/screenshots.py` against a running demo server.
- Data files only gain fields; the map page must still open data files of older versions.
- Optional NetBox objects (roles, IP ranges, VLANs, scopes) are skipped with a warning when the token cannot read them.
