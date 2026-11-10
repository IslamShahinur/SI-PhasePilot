# Contributing to SI PhasePilot

Thank you for your interest. This is a small, focused project, so a few simple rules keep it healthy.

## Ways to help

- **Report a bug.** Open an issue with: what you did, what you expected, what happened, your Windows and Python versions, and the last lines of `%APPDATA%\SI-PhasePilot\logs\app.log`. Remove any keys, passwords or personal data first.
- **Suggest an improvement.** Open an issue and describe the problem you want solved before describing the solution.
- **Improve the documentation.** Fixes to the README, Setup Guide or User Guide are always welcome.
- **Send a pull request.** Please open an issue first for anything larger than a small fix, so we can agree on the approach.

## Ground rules

These rules protect the design of the app:

1. **No AI services inside the app.** PhasePilot records the process; it does not call AI APIs or include AI libraries.
2. **No new third-party packages** without discussion. The app uses only `PySide6`, `supabase` and `keyring`, plus the Python standard library.
3. **Keep the layers separate:**
   - `data.py` (and `data_review.py`, `data_delete.py`) are the **only** code that talks to Supabase.
   - `services.py` handles local things: settings, Git, clipboard, sign-in storage. It imports nothing from the data or UI layers.
   - Files in `ui/` never talk to Supabase directly and never run Git directly. They call the data and services layers, and long work runs through `run_async` so the window never freezes.
4. **Never use the `service_role` key.** Only the public URL and anon key.
5. **No hard deletes** outside Secure Delete. Everything else is archived.
6. **History is append-only.** Commands, reports, baselines and document versions are added, not rewritten.
7. **No secrets** in code, logs, reports or commits.
8. **Keep files reasonably small.** Files over about 800 lines should be split rather than grown.
9. **Edits are blocked while offline or saving.** Do not bypass this.

## Setting up for development

Follow the [Setup Guide](docs/SETUP_GUIDE.md), ideally against a **separate, throw-away Supabase project** so you never test on real data.

Run the tests:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests\test_workflow.py -q
```

Note: one test (`TestCanMarkCompleted.test_enabled_when_has_report_and_not_cleared`) is known to be out of date and fails. Please do not count it against your change, and feel free to fix it.

Check your changes compile and have no new warnings:

```powershell
python -m py_compile main.py data.py services.py workflow.py
python -m pyflakes <the files you changed>
```

## Database changes

- Put changes in a **new, clearly named SQL file** in `db/` and describe in your pull request which order to run it in.
- Make SQL safe to run twice when possible.
- Every new table needs row-level security that limits rows to their owner.
- Document the change in the [Changelog](CHANGELOG.md).

## Pull request checklist

- [ ] The change is focused on one thing.
- [ ] The app starts and the screens you touched work (test on a throw-away project).
- [ ] `py_compile` passes, with no new `pyflakes` warnings in files you changed.
- [ ] No secrets, `.env` files, logs or `.venv` are included.
- [ ] The Changelog and the relevant guide are updated.
- [ ] Database changes are in a new SQL file with run-order notes.

## Commit messages

Short and clear, in the form `area: what changed`, for example `ui: fix document row menu` or `docs: clarify storage bucket step`.

## Code of conduct

Be kind and respectful. Assume good intent. Keep feedback about the work, not the person.
