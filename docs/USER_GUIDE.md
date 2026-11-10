# User Guide

This guide shows how to use SI PhasePilot day to day. If you have not installed it yet, start with the **[Setup Guide](SETUP_GUIDE.md)**.

> Button and label names in this guide match the app as closely as possible. If a label on your screen is slightly different, look for the button with the same purpose.

**Contents**

- [The big picture](#the-big-picture)
- [A first look at the window](#a-first-look-at-the-window)
- [Signing in and out](#signing-in-and-out)
- [Quick tour: your first project in 10 steps](#quick-tour-your-first-project-in-10-steps)
- [Screen A: Project](#screen-a-project)
- [Screen B: Documents](#screen-b-documents)
- [Screen C: Phase](#screen-c-phase)
- [Screen D: Project Review](#screen-d-project-review)
- [Screen E: Baseline](#screen-e-baseline)
- [Screen F: Register](#screen-f-register)
- [Screen G: Handoff](#screen-g-handoff)
- [Secure Delete](#secure-delete)
- [Sync status and working offline](#sync-status-and-working-offline)
- [Working on two PCs](#working-on-two-pcs)
- [Tips for a smooth workflow](#tips-for-a-smooth-workflow)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)
- [Glossary](#glossary)

---

## The big picture

PhasePilot is a **tracker**. It never talks to an AI tool for you. You do the work in your AI coding tool, and PhasePilot keeps the record:

1. **You write a command** (the task) for your AI coder and save it in the app.
2. **The AI builds**, and you paste its report back into the app.
3. **A second AI reviews** the work. You record that command and its report too.
4. **You decide**: Passed or Failed. If Failed, you do a Re-Fix round (up to three).
5. **When Passed**, you approve a baseline: a recorded Git checkpoint you can always return to.
6. **Then the next phase starts**, only after the previous one is clean.

The app only records and organizes. It does not check your code or run your tools. **You** stay in control of every decision.

## A first look at the window

```
+------------------------------------------------------------------+
| Project [ MyApp  v ] [+]   Phase [ 01 v ]    SYNCED     Dark     |  <- top bar
+------------------------------------------------------------------+
|  [A] [B] [C] [D] [E] [F] [G]                                     |  <- screen tabs
+------------------------------------------------------------------+
|                                                                  |
|                  the screen you selected                         |
|                                                                  |
+------------------------------------------------------------------+
| you@example.com            last sync 10:42             SYNCED    |  <- footer
+------------------------------------------------------------------+
```

- **Project selector and [+]:** switch projects, or create a new one.
- **Phase selector:** choose which phase you are working on. It follows you from screen to screen.
- **Tabs A to G:** the seven screens. Each has its own accent color so you always know where you are.
- **Sync status:** `SYNCED` (all saved), `SAVING` (wait a moment), `OFFLINE` (no connection) or `ERROR` (see the log).
- **Theme switch:** Light or Dark. Your choice is remembered.

## Signing in and out

- Enter the email and password of the user you created in Supabase.
- Tick **Remember me** to stay signed in on this PC. Your sign-in is kept in Windows Credential Manager.
- To sign out, use the sign-out option in the main window. This also clears the remembered sign-in.

---

## Quick tour: your first project in 10 steps

1. Start the app and sign in.
2. Click the **[+]** next to the Project box and give your project a name.
3. On **Screen A**, add a short description and click **Save**.
4. On **Screen A**, click **Browse** and choose the folder of your code repository, then save the path. (Skip if you have no repository yet.)
5. On **Screen A**, click **Add Document**, pick your blueprint or specification file, and give it a title. It is stored as Version 1.
6. Open **Screen C** and click **New Phase**. Phase 01 is created for you.
7. In **Screen C**, write the command for your AI coder, then click **Save Command**. The phase status becomes **Coding In Progress**.
8. Give the command to your AI coder (use the Copy button). When it finishes, paste its report into the Coder Report box and click **Completed**.
9. Open **Screen D**, create the review command, run it with a different AI tool, paste the review report, and mark the result **Passed** or **Failed**.
10. If Passed, open **Screen E** and approve the baseline. You are ready for the next phase.

The sections below explain each screen in detail.

---

## Screen A: Project

Everything about the project as a whole.

**What you can do**

- **Edit project details** (name, description) and click **Save**.
- **Set the repository path.** Click **Browse**, choose the folder that holds your code, then save. This lets the app read Git information.
- **See the Checkpoint.** It shows the last committed Git hash of your repository. If it shows a dash, no repository is set or Git is not installed.
- **Manage foundation documents.** These are the documents the whole project rests on (blueprint, specification, rules). Search them, preview them, open or download them, and add new versions.
- **Archive the project.** Archiving hides a finished or paused project without deleting anything. Use **Reopen** to bring it back.
- **Danger Zone** (shown in red): permanent project deletion. See [Secure Delete](#secure-delete).

**Good to know**

- Choosing a file with **Add Document** uploads it to your private storage. Files are never overwritten. Replacing a document creates a new version and the old version stays in the history.
- Some file types and very large files are not accepted. The app tells you if a file is refused.

## Screen B: Documents

Your design and visual documents (screen layouts, mockups, UI notes).

**What you can do**

- **Search and filter** the table to find a document quickly.
- **Select a row** to see a preview and its details.
- **Add Document**, then choose a file. It is stored as Version 1.
- **Open** (uses the default Windows program) or **Download** a version.
- **Replace** to upload a newer file. This becomes Version 2, 3 and so on.
- **Save Details** after editing the title or notes.
- **Mark status** as **Draft** or **Approved**.
- **Archive** a document you no longer need. It is hidden, not destroyed.
- **Delete** (right-click or row menu) uses [Secure Delete](#secure-delete).

## Screen C: Phase

Where you plan and record the work of a phase.

**Creating a phase**

- Click **New Phase**. Phase numbers are assigned automatically (01, 02, 03...). You can give a phase a name if you like.
- The Phase selector in the top bar switches between phases.

**Phase status** (one of three):

| Status | Meaning |
|---|---|
| **Awaiting for Task** | The phase exists but no task is being coded yet. This is the starting state. |
| **Coding In Progress** | A command was saved and your AI coder is working. Delete is blocked while a phase is in this state. |
| **Coding Completed** | The coder report is recorded. The phase is ready for review. |

**Tasks and re-fix rounds**

Use the task dropdown to choose what you are recording:

- **Coding**: the first build of the phase.
- **Re-Fix-1, Re-Fix-2, Re-Fix-3**: up to three repair rounds after a failed review.

Each task keeps its **own** command and report, so you can look back at exactly what was asked and what came back at every round.

**Step by step: recording a task**

1. Choose **Coding** in the task dropdown.
2. Write or paste the command for your AI coder.
3. Click **Save Command**. The status changes to **Coding In Progress**.
4. Click **Copy** to put the command on your clipboard, then paste it into your AI tool.
5. When the coder finishes, paste its report into the **Coder Report** section at the bottom.
6. Click **Save**, then the big **Completed** button. The status changes to **Coding Completed**.

**Work items:** you can keep a short list of work items for the phase and tick them off as they are done.

## Screen D: Project Review

Where you check the work. **Use a different AI tool for review than the one that built the code.**

**Review rounds:** choose **Review-1**, **Review-2**, **Review-3** or **Final Review** from the dropdown. Each round has its own records.

**Step by step: recording a review**

1. Choose the review round.
2. Write or paste the **Auditor Command** (the instructions for the reviewing AI) and save it. Use **Copy** to move it to your reviewing tool.
3. Paste the reviewer's answer into the **Auditor Report** and save. You can also attach the report as a file.
4. Fill in the findings and notes if you keep them.
5. Set the **Review Status** to **Passed** or **Failed**.
6. Read the **Recommendations** box at the bottom. After **Passed** it suggests moving to the **Next Phase**. After **Failed** it suggests a **Re-Fix** round (go back to Screen C and choose the next Re-Fix task).

**Rule of thumb:** a review passes only when it found no blocking problems. If you are unsure, mark it Failed and record why. Your reasoning is part of the record.

## Screen E: Baseline

A baseline is a recorded, approved checkpoint of your code.

**What you can do**

- **Select Repository** to read the Git branch, the latest commit and whether the working folder is clean.
- **Approve the baseline** once the review has passed. The app records the branch, commit, tree hash and clean/dirty state together with your approval note.
- **Browse the baseline history.** Approved baselines are **protected**: deleting one needs an extra tick box in [Secure Delete](#secure-delete).

**Best practice:** only approve a baseline when your working folder is clean (everything committed) and the review has passed. Then the baseline really is a known-good point you can return to.

## Screen F: Register

A safe place for things you must not forget: critical items, deferred problems, decisions you postponed.

- **Add** an item with a type, a description and, if you like, the phase it belongs to.
- **Edit** items as the situation changes.
- Register items are **edited, not deleted**. When a phase is deleted, its register items stay and simply lose the phase link.

## Screen G: Handoff

Packages everything you need to continue the project in a new session, with a new tool or with another person.

- **Load handoff data** to collect the current state.
- **Generate Summary** to create a readable Markdown summary of the project, phases and baselines.
- **Manifest** lists the documents and records included, with checksums.
- **Export Markdown** or **Export ZIP** saves the result to your exports folder (`%APPDATA%\SI-PhasePilot\exports\`).
- Choose which documents to include before exporting. If nothing is selected, the app tells you.

---

## Secure Delete

Most things in PhasePilot are archived, not removed. **Secure Delete** is the one way to remove something for good.

**What can be deleted**

| Item | What is removed with it |
|---|---|
| Project | All its phases, commands, records, documents and files. |
| Phase | Its commands, records and files. (Register items stay, without the phase link.) |
| Command | Its run records and report files. |
| Document | The document and its stored file versions. |
| Approved baseline | That baseline record (needs an extra tick box). |

**How to delete**

1. Delete is available **only** from a row menu or from the project **Danger Zone**. There is no shortcut and no bulk delete.
2. A window lists **everything that will be removed**. Read it.
3. **Type the exact name** of the item. Capital letters count. The Delete button stays disabled until it matches. The Enter key does nothing. **Cancel** is selected by default.
4. For a **project** or a **baseline**, also tick the confirmation box.
5. Click **Delete**.

**Rules and warnings**

- **It is permanent.** There is no trash and no undo.
- **It is blocked while a phase is Coding In Progress.** Finish or reset the run first.
- If a file cannot be removed from storage after the records are deleted, you will see a warning with the file path, and the problem is written to the log. No record is left pointing at a missing file.
- Your Git history is never touched.
- When in doubt, **archive** instead.

---

## Sync status and working offline

| Status | Meaning | What to do |
|---|---|---|
| **SYNCED** | Everything is saved on the server. | Carry on. |
| **SAVING** | A save is in progress. | Wait a moment. Buttons that change data are disabled. |
| **OFFLINE** | No connection to your database. | Restore your connection. Editing is blocked while offline. |
| **ERROR** | Something went wrong. | Check `%APPDATA%\SI-PhasePilot\logs\app.log`. |

PhasePilot is **online-first on purpose**. If you could edit offline on two PCs, the records could disagree. Waiting for a connection keeps your history trustworthy.

## Working on two PCs

- Set up the second PC as described in the Setup Guide ("Using a second PC").
- Sign in with the same account. All projects and documents are already there.
- Use **one PC at a time**. If two windows change the same item, the app shows a **conflict** message and nothing is overwritten. Reload the screen and apply your change again.

## Tips for a smooth workflow

- **One phase, one clear goal.** Small phases are easier to review.
- **Save the command first, then run it.** Then the record always matches what the coder was told.
- **Use a different AI for review** than for building.
- **Commit before you approve a baseline**, so the baseline is a clean checkpoint.
- **Use the Register** for every "we will fix that later". It is the cheapest insurance against forgetting.
- **Archive, do not delete,** unless you are sure.
- **Back up** your important documents outside the app as well. A cloud database is convenient, not a backup strategy.

## FAQ

**Does PhasePilot write code for me?**
No. It does not contain or call any AI service. It records the work you do with other tools.

**Is my data shared with anyone?**
No. It goes only to your own Supabase project. Privacy rules in the database restrict every row to its owner.

**Can I use it on Mac or Linux?**
Not in this version. It is built for Windows.

**Can several people use one project?**
This version is designed for one person (on one or two PCs). Each user's data is private to that user.

**What happens if my free Supabase project pauses?**
Free projects can pause after inactivity. Open the Supabase dashboard and restore the project. Your data is kept.

**I deleted something by mistake.**
Secure Delete is permanent. If you made your own database backup, restore from it. This is why archiving is the default.

**Where is my remembered sign-in stored?**
In Windows Credential Manager, not in a file. Signing out clears it.

**Why is a button greyed out?**
Usually because the app is SAVING or OFFLINE, because no project or phase is selected, or because a rule blocks it (for example, deleting during Coding In Progress). The status bar or a message explains why.

## Troubleshooting

| Problem | What to try |
|---|---|
| A popup says something failed to load | Check the sync status. Reload the screen by switching tabs. Look at the last lines of `%APPDATA%\SI-PhasePilot\logs\app.log`. |
| "permission denied for table ..." | A database SQL file was not run. Run all four files from `db/` in order (see Setup Guide, Part 6). |
| New Phase or Save does nothing | Make sure the status is **SYNCED**, not SAVING or OFFLINE. |
| Document will not upload | Check the bucket name `phasepilot-files` (Setup Guide, Part 7) and the file type and size. |
| Checkpoint shows a dash | Set the repository path on Screen A and make sure Git is installed. |
| Conflict message | You or another PC changed the same item. Reload and redo your change. |
| App will not start | Read `app.log` and see the Setup Guide troubleshooting table. |

## Glossary

| Word | Meaning |
|---|---|
| **Phase** | One planned chunk of work, numbered 01, 02, 03... |
| **Command** | The written task you give to an AI coder or reviewer. |
| **Coder / Auditor** | The AI that builds, and the different AI that reviews. |
| **Re-Fix** | A repair round after a failed review (up to three per task). |
| **Baseline** | An approved, recorded Git checkpoint. |
| **Register** | The list of critical and deferred items. |
| **Handoff** | An export that lets you continue in a new session. |
| **Archive** | Hide something without destroying it. |
| **Secure Delete** | Permanent, confirmed removal. |
| **Supabase** | The cloud service holding your database, login and files. |
| **Anon key** | The public key the app uses to reach your Supabase project. Safe to use in the app; never use the `service_role` key. |
