# Changelog

All notable changes to SI PhasePilot are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-11-10

First public release.

### Added

**Foundation (Phase 1)**
- Sign in with email and password through your own Supabase project, with an optional "Remember me" that stores the session in Windows Credential Manager.
- Multiple projects, fully isolated from each other. Create, edit, archive and reopen.
- Repository path per project.
- Document storage in a private bucket with full version history (new uploads become new versions; nothing is overwritten).
- Online-first sync with four visible states: `SYNCED`, `SAVING`, `OFFLINE`, `ERROR`. Writes are blocked while offline or saving.
- Conflict protection: if two windows change the same item, the app reports a conflict instead of overwriting.
- Light and Dark themes, remembered between sessions.
- Local runtime files kept in `%APPDATA%\SI-PhasePilot\` (settings, logs, exports, temp).

**Phases, review and register (Phase 2)**
- Screen C (Phase): numbered phases, coder commands, coder reports and work items.
- Screen D (Project Review): review commands, reports and Passed/Failed results.
- Screen E (Baseline): repository selection and approved baselines.
- Screen F (Register): critical and deferred items.

**Handoff and release verification (Phase 3)**
- Screen G (Handoff): project summary, manifest and Markdown/ZIP export.

**Hardening and workflow (Phase 4)**
- *4A:* new top bar with project and phase selectors, redesigned Screens A and B, shared document panel.
- *4B:* simplified phase workflow with three statuses (Awaiting for Task, Coding In Progress, Coding Completed), task types Coding and Re-Fix-1 to Re-Fix-3, review rounds Review-1 to Review-3 plus Final Review, and a recommendations box. Database workflow rules added in `db/schema_rev_4b.sql`. Review-record permissions added in `db/fix_audit_records_permissions.sql`.
- *4C:* redesigned Screens E, F and G with the same layout language as the rest of the app.
- *4D:* **Secure Delete** for projects, phases, commands, documents and approved baselines:
  - an impact list is shown before anything is removed
  - the exact item name must be typed; Enter does nothing; Cancel is the default
  - projects and approved baselines also need a confirmation tick box
  - blocked while a phase is Coding In Progress
  - database rows are removed in one all-or-nothing database function (`db/secure_delete.sql`); stored files are removed afterwards, and any file that cannot be removed is logged and reported
  - one log line per successful delete

**Database**
- Four SQL files in `db/`, to be run in order: `schema.sql`, `schema_rev_4b.sql`, `fix_audit_records_permissions.sql`, `secure_delete.sql`.
- Row-level privacy rules so every signed-in user only sees their own data.

**Documentation**
- README, Setup Guide, User Guide, Security policy, Contributing guide and the original design documents.

### Known issues
- One automated test, `TestCanMarkCompleted.test_enabled_when_has_report_and_not_cleared`, is out of date after the 4B status change and fails. It does not affect the app.
- A few code files contain unused imports and several files are longer than the preferred 800 lines. This is cosmetic.
- Windows only.

### Not included
- Features that were designed but intentionally not built in this release, such as an AI review helper and an automated rules engine.

[Unreleased]: https://github.com/YOUR-USERNAME/SI-PhasePilot/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/YOUR-USERNAME/SI-PhasePilot/releases/tag/v1.0.0
