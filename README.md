# SI PhasePilot

**A Windows desktop app that tracks software projects built phase by phase with AI coding agents.**

SI PhasePilot keeps every command you give an AI coder, every report it sends back, every review, every approved checkpoint and every important project document in one organized place. Your data lives in **your own private Supabase database**, so you can continue the same project from a second PC without losing the thread.

> **PhasePilot does not write code and does not call any AI service.**
> You plan, code and review with the tools you already use. PhasePilot is the notebook and control tower around them: it records what was asked, what came back, what was checked and what was approved.

---

## Table of contents

1. [Who is this for?](#who-is-this-for)
2. [What you can do with it](#what-you-can-do-with-it)
3. [How a phase works](#how-a-phase-works)
4. [What you need](#what-you-need)
5. [Quick start](#quick-start)
6. [The seven screens](#the-seven-screens)
7. [Your data and your privacy](#your-data-and-your-privacy)
8. [Where files are stored on your PC](#where-files-are-stored-on-your-pc)
9. [Project layout](#project-layout)
10. [Documentation](#documentation)
11. [Known limitations](#known-limitations)
12. [Contributing, security and license](#contributing-security-and-license)

---

## Who is this for?

- People who build software **with AI coding assistants** and want a clear, repeatable process: command, build, review, approve, next phase.
- Solo builders who work on **more than one computer** and need the project record to follow them.
- Anyone who has lost track of "which version did the AI actually build, and was it ever checked?"

You do **not** need to be a database expert. The [Setup Guide](docs/SETUP_GUIDE.md) walks through every step.

## What you can do with it

- **Manage several projects**, each fully separate from the others.
- **Store project documents with version history** (blueprints, specs, UI designs). Nothing is overwritten; a new upload becomes a new version.
- **Run phases one at a time.** Write the task for your AI coder, record its report, run reviews, and mark the phase passed or failed.
- **Track re-fix rounds.** Each task has an initial build and up to three re-fix rounds, each with its own record.
- **Approve baselines.** When a phase passes review you record the approved Git checkpoint (branch, commit and clean/dirty state).
- **Keep a register** of critical and deferred items so nothing is forgotten.
- **Export a handoff**: a Markdown summary, a manifest and a ZIP, ready to start a fresh session with any tool.
- **Work from two PCs.** Everything is saved to the cloud database and shown as `SYNCED`, `SAVING`, `OFFLINE` or `ERROR`.
- **Delete safely when you must.** Secure Delete shows exactly what will be removed and asks you to type the item's name first.
- **Light and Dark themes.**

## How a phase works

```
  Plan the phase (outside the app)
            |
            v
  Screen C: write the command for the AI coder, press Save Command
            |                      (status: Coding In Progress)
            v
  Your AI coder builds it  ->  paste its report into Screen C
            |                      press Completed (status: Coding Completed)
            v
  Screen D: write the review command, run the review with a DIFFERENT
            AI tool, paste its report, mark the review Passed or Failed
            |
     Failed |                      Passed
            v                         v
   Re-Fix round (max 3)       Screen E: approve the baseline
   back to Screen C           (Git checkpoint is recorded)
                                      |
                                      v
                                 Next phase
```

The rule of thumb: **the AI that reviews should not be the AI that built.** PhasePilot gives you the place to record both sides.

## What you need

| Requirement | Notes |
|---|---|
| Windows 10 or 11 | The app is Windows-only. |
| Python 3.11 or newer | Free from python.org. |
| A free Supabase account | Your private database, login system and file storage. |
| Internet connection | The app is online-first: edits are blocked while offline so two PCs can never disagree. |
| Git (optional) | Needed only for the repository, checkpoint and baseline features. |

## Quick start

The full beginner-friendly version is in the **[Setup Guide](docs/SETUP_GUIDE.md)**. In short:

1. Install Python 3.11+ (tick **Add python.exe to PATH**).
2. Download this repository and install the requirements:
   ```powershell
   git clone https://github.com/IslamShahinur/SI-PhasePilot.git
   cd SI-PhasePilot
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Create a free Supabase project and run the four SQL files from the `db/` folder, in order:
   1. `schema.sql`
   2. `schema_rev_4b.sql`
   3. `fix_audit_records_permissions.sql`
   4. `secure_delete.sql`
4. Create your login user in Supabase (Authentication, Users, Add user).
5. Tell the app where your database is. Use the **anon (public)** key only:
   ```powershell
   setx SUPABASE_URL "https://YOUR-PROJECT.supabase.co"
   setx SUPABASE_ANON_KEY "YOUR-ANON-KEY"
   ```
   Close and reopen PowerShell afterwards.
6. Start the app and sign in with the user you created:
   ```powershell
   python main.py
   ```

Then follow the **[User Guide](docs/USER_GUIDE.md)** to create your first project.

## The seven screens

Tabs **A** to **G** run along the top of the window. The main workflow uses A to E; F and G are supporting tools.

| Tab | Name | What it is for |
|---|---|---|
| **A** | Project | Project details, repository path, last Git checkpoint, foundation documents, archive and delete. |
| **B** | Documents | UI and design documents with search, preview, versions and Draft/Approved status. |
| **C** | Phase | Create phases, write the coder command, record the coder report, mark coding complete. |
| **D** | Project Review | Review rounds (Review-1 to Review-3 and Final Review), review command and report, Passed/Failed result, recommendation. |
| **E** | Baseline | Select the repository and approve baselines. Approved baselines are protected. |
| **F** | Register | Critical and deferred items you must not forget. Items are edited, not deleted. |
| **G** | Handoff | Summary, manifest and exports for moving a project to a new session or person. |

The top bar on every screen holds the **Project** selector (with a **+** button for a new project), the **Phase** selector, the sync status and the theme switch.

## Your data and your privacy

- **You own the database.** Your data goes to your own Supabase project, not to any server run by this app's author.
- **Every row is private to its owner.** Database rules ensure a signed-in user can only see and change their own data.
- **No secrets in the app.** The app uses only the public **anon** key. **Never** put a `service_role` or secret key anywhere near this app.
- **Nothing is hard-deleted by accident.** Projects and documents are archived first. Secure Delete is the only permanent removal, and it is permanent: there is no trash and no undo.
- **Files are private.** Uploaded documents sit in a private storage bucket, in a folder named after your user.

## Where files are stored on your PC

The app keeps only small local files in `%APPDATA%\SI-PhasePilot\`:

| Item | Purpose |
|---|---|
| `settings.json` | Device ID, last opened project, theme, "remember me" choice. |
| `logs\app.log` | Diagnostic log. Look here first if something goes wrong. |
| `exports\` | Handoff exports you created. |
| `temp\` | Temporary files, safe to clear. |

The "remember me" sign-in is stored in **Windows Credential Manager**, not in a file.

## Project layout

```
SI-PhasePilot/
  main.py               Starts the app
  data.py               All database and storage access
  data_review.py        Review-record access
  data_delete.py        Secure Delete logic
  services.py           Local helpers (settings, Git, clipboard, sign-in storage)
  workflow.py           Phase and status rules
  requirements.txt      Python packages (pinned versions)
  ui/                   Screens, shared panels, Secure Delete dialog
  db/                   The four SQL files for Supabase
  docs/                 Setup guide, user guide, design documents
  tests/                Automated tests
```

## Documentation

| Document | For |
|---|---|
| [Setup Guide](docs/SETUP_GUIDE.md) | Installing and connecting everything, step by step. |
| [User Guide](docs/USER_GUIDE.md) | Using each screen, a full worked example, FAQ and troubleshooting. |
| [Changelog](CHANGELOG.md) | What changed in each version. |
| [Master Document](docs/01_Master_Document.md) | The original design specification. |
| [Security policy](SECURITY.md) | How to report a vulnerability. |
| [Contributing](CONTRIBUTING.md) | Rules for proposing changes. |

## Known limitations

- Windows only.
- Online-first by design: no offline editing.
- One automated test (`TestCanMarkCompleted`) is known to fail; it is out of date and does not affect the app.
- Some code files are longer than the project's preferred size and contain unused imports. This is cosmetic.
- The app records and organizes your process. It does **not** run your AI tools, run your tests or check your code for you.
- Features that were designed but not built (such as an AI review helper) are not part of this version.

## Contributing, security and license

- See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
- Found a security problem? Please read [SECURITY.md](SECURITY.md) first and do not post it publicly.
- Licensed under the terms in [LICENSE](LICENSE).

<!--
SCREENSHOTS: put your PNG files in docs/images/ and add lines like:
![Screen C - Phase](docs/images/screen-c.png)
Good screenshots to include: the login window, Screen A, Screen C, Screen D, Screen E.
-->
