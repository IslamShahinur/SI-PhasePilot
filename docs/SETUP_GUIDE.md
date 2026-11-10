# Setup Guide

This guide takes you from nothing to a working SI PhasePilot, one small step at a time. Plan for about **30 minutes** the first time. You do not need programming experience, but you will copy and paste a few commands.

**Contents**

- [Before you start](#before-you-start)
- [Part 1: Install Python](#part-1-install-python)
- [Part 2: Install Git (optional)](#part-2-install-git-optional)
- [Part 3: Get the app](#part-3-get-the-app)
- [Part 4: Install the app's packages](#part-4-install-the-apps-packages)
- [Part 5: Create your Supabase project](#part-5-create-your-supabase-project)
- [Part 6: Install the database (four SQL files)](#part-6-install-the-database-four-sql-files)
- [Part 7: Check file storage](#part-7-check-file-storage)
- [Part 8: Create your login user](#part-8-create-your-login-user)
- [Part 9: Connect the app to your database](#part-9-connect-the-app-to-your-database)
- [Part 10: Start the app](#part-10-start-the-app)
- [Part 11: Final checklist](#part-11-final-checklist)
- [Using a second PC](#using-a-second-pc)
- [Updating the app](#updating-the-app)
- [Troubleshooting](#troubleshooting)
- [Uninstalling](#uninstalling)

---

## Before you start

You will need:

- A Windows 10 or 11 PC.
- An internet connection.
- An email address (for a free Supabase account).

**What is PowerShell?** It is the text window where you type commands. Open it by pressing the Windows key, typing `PowerShell` and pressing Enter. Every grey code box in this guide is meant to be pasted there (right-click pastes in PowerShell).

---

## Part 1: Install Python

1. Go to **python.org**, open Downloads, and download Python **3.11 or newer**.
2. Run the installer. On the first screen, **tick "Add python.exe to PATH"**, then choose **Install Now**.
3. Open a **new** PowerShell window and check:
   ```powershell
   python --version
   ```
   You should see `Python 3.11.x` or higher. If you see an error, close all PowerShell windows, reopen one and try again. If it still fails, re-run the installer and make sure the PATH box is ticked.

---

## Part 2: Install Git (optional)

Git is only needed for the repository, checkpoint and baseline features, and for downloading the app with `git clone`. You can skip it and download the ZIP instead (Part 3, option B).

1. Download **Git for Windows** from git-scm.com and install it with the default options.
2. Check in a new PowerShell window:
   ```powershell
   git --version
   ```

---

## Part 3: Get the app

Choose **one** option.

**Option A: with Git (recommended, makes updating easy)**

```powershell
cd $HOME\Desktop
git clone https://github.com/YOUR-USERNAME/SI-PhasePilot.git
cd SI-PhasePilot
```

**Option B: ZIP download**

1. On the GitHub page, click the green **Code** button, then **Download ZIP**.
2. Right-click the ZIP and choose **Extract All** (for example to your Desktop).
3. In PowerShell, go into the extracted folder:
   ```powershell
   cd $HOME\Desktop\SI-PhasePilot-main
   ```

From now on, every command assumes PowerShell is **inside the app folder**.

---

## Part 4: Install the app's packages

The app keeps its packages in a private "virtual environment" folder called `.venv`, so it never interferes with other Python programs.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

When the environment is active you will see `(.venv)` at the start of the PowerShell line. This takes a minute or two.

> **If PowerShell says "running scripts is disabled":** run this once, then repeat the `Activate.ps1` line:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> Answer `Y` when asked.

---

## Part 5: Create your Supabase project

Supabase is the free cloud service that stores your data, handles your login and keeps your uploaded files.

1. Go to **supabase.com** and create a free account.
2. Click **New project**.
3. Fill in:
   - **Name:** anything, for example `phasepilot`.
   - **Database password:** create a strong one and save it in a password manager. You will rarely need it.
   - **Region:** pick the one nearest to you.
4. Click **Create new project** and wait until it finishes setting up (a minute or two).
5. Open **Project Settings** (gear icon), then **API**. Keep this page open. You need two values:
   - **Project URL**, which looks like `https://abcdefgh.supabase.co`
   - **anon public key**, a long text starting with `eyJ...`

> **Important:** use the **anon / public** key only. **Never** use the `service_role` or "secret" key. It bypasses all privacy rules and must never be put in this app, in a file, or on GitHub.

---

## Part 6: Install the database (four SQL files)

The `db/` folder contains four SQL files. They create the tables, privacy rules and safe-delete function. Run them **in this order**, one at a time:

| Order | File | What it does |
|---|---|---|
| 1 | `db/schema.sql` | Creates the tables, privacy rules and file-storage setup. |
| 2 | `db/schema_rev_4b.sql` | Adds the phase, task and review workflow. |
| 3 | `db/fix_audit_records_permissions.sql` | Gives the app permission to read and write review records. |
| 4 | `db/secure_delete.sql` | Adds the Secure Delete function and file-delete permission. |

For **each** file:

1. In Supabase, open **SQL Editor** in the left menu, then **New query**.
2. Open the file on your PC with Notepad or VS Code, press **Ctrl+A** then **Ctrl+C** to copy everything.
3. Paste it into the SQL Editor (**Ctrl+V**).
4. Click **Run**.
5. Wait for the message **"Success. No rows returned"** (or similar success). Then start the next file.

If a file shows a red error, stop, read the message, and see [Troubleshooting](#troubleshooting). Do not continue to the next file until it is fixed.

---

## Part 7: Check file storage

Uploaded documents are kept in a private storage bucket named **`phasepilot-files`**.

1. In Supabase, open **Storage** in the left menu.
2. You should see a bucket called `phasepilot-files`.
3. If it is missing, click **New bucket**, name it exactly `phasepilot-files`, leave **Public bucket OFF**, and save.

---

## Part 8: Create your login user

The app signs in with an email and password that exist in your Supabase project.

1. In Supabase, open **Authentication**, then **Users**.
2. Click **Add user**, then **Create new user**.
3. Enter your email and a password. Tick **Auto Confirm User** if shown.
4. Click **Create user**.

You will type exactly this email and password into the app's login window.

> **Tip:** if you work alone, it is a good idea to turn off public sign-ups so nobody else can create accounts on your project. In Authentication, open the sign-in/provider settings and disable "Allow new users to sign up".

---

## Part 9: Connect the app to your database

The app reads two settings from Windows environment variables: your project URL and your anon key. Set them once.

Replace the example values with yours from Part 5:

```powershell
setx SUPABASE_URL "https://YOUR-PROJECT.supabase.co"
setx SUPABASE_ANON_KEY "YOUR-ANON-KEY"
```

**Close PowerShell completely and open a new window**, then go back into the app folder and activate the environment again:

```powershell
cd $HOME\Desktop\SI-PhasePilot
.\.venv\Scripts\Activate.ps1
```

Check that the settings are visible (this prints the URL and only says whether the key exists, so the key is not shown):

```powershell
$env:SUPABASE_URL
$null -ne $env:SUPABASE_ANON_KEY
```

You should see your URL and then `True`.

**Just testing, and do not want to save anything permanently?** Use these instead. They last only until you close that PowerShell window:

```powershell
$env:SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
$env:SUPABASE_ANON_KEY = "YOUR-ANON-KEY"
```

---

## Part 10: Start the app

```powershell
python main.py
```

1. The login window opens.
2. Enter the email and password from Part 8.
3. Tick **Remember me** if you want to stay signed in on this PC.
4. The main window opens. The status at the bottom or top should show **SYNCED**.

Now continue with the **[User Guide](USER_GUIDE.md)** to create your first project.

---

## Part 11: Final checklist

Tick each one:

- [ ] `python --version` shows 3.11 or higher
- [ ] `(.venv)` shows in your PowerShell line
- [ ] All four SQL files ran with a success message
- [ ] Storage shows a private bucket named `phasepilot-files`
- [ ] You created a user in Authentication
- [ ] `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set (Part 9 check printed the URL and `True`)
- [ ] The app starts and you can sign in
- [ ] You can create a project and the status shows **SYNCED**

---

## Using a second PC

Repeat Parts 1 to 4 and Part 9 on the second PC (same URL, same anon key). **Do not** repeat Parts 5 to 8; the database and user already exist. Sign in with the same email and password and you will see the same projects.

Edit from **one PC at a time**. If you change the same item on two PCs, the app will warn you about a conflict instead of overwriting anything.

---

## Updating the app

If you used `git clone`:

```powershell
cd $HOME\Desktop\SI-PhasePilot
git pull
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you used the ZIP, download the new ZIP and extract it, keeping your own `.venv` or recreating it with Part 4. Your data is in Supabase, so it is not affected.

Read the **[Changelog](../CHANGELOG.md)** before updating. If a new version needs a new SQL file, the changelog will say which one and in what order.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| `python` is not recognized | Reinstall Python and tick **Add python.exe to PATH**. Open a new PowerShell window. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, then try again. |
| `pip install` fails | Check your internet connection. Make sure `(.venv)` is showing. Try `python -m pip install --upgrade pip` and run the install again. |
| App says **Missing environment variable(s)** | Part 9 was not done, or PowerShell was not reopened after `setx`. Close PowerShell, open a new one and check with the Part 9 commands. |
| Login fails with "Invalid login credentials" | The user does not exist or the password is wrong. Check Authentication, Users in Supabase. Make sure the user is confirmed. |
| Login fails but the credentials are right | The URL or anon key is wrong or has a stray space or quote. Set them again (Part 9). |
| Error: `permission denied for table ...` | One of the SQL files was skipped. Run all four, in order. Running a file twice is normally safe, but read the message first. |
| Status stays **OFFLINE** or **ERROR** | Check your internet connection. Check that the Supabase project is not paused (free projects pause after a period of inactivity; open the dashboard and click **Restore**). |
| Upload fails | Check Part 7: the bucket must be named exactly `phasepilot-files`. Large files may also be rejected; the app has a maximum file size and allowed file types. |
| Window looks blank or crashes at start | Open `%APPDATA%\SI-PhasePilot\logs\app.log` and read the last lines. Include them when you ask for help. Remove any passwords or keys first. |
| SQL file shows an error you do not understand | Copy the exact message, remove nothing secret (SQL error messages do not contain your keys), and open a GitHub issue. |

To turn on extra logging, set `SI_PHASEPILOT_DEBUG` to any value before starting the app:

```powershell
$env:SI_PHASEPILOT_DEBUG = "1"
python main.py
```

---

## Uninstalling

1. Delete the app folder.
2. Delete `%APPDATA%\SI-PhasePilot\`.
3. In Windows **Credential Manager**, remove the `SI-PhasePilot` entry if present.
4. Remove the environment variables:
   ```powershell
   [Environment]::SetEnvironmentVariable("SUPABASE_URL", $null, "User")
   [Environment]::SetEnvironmentVariable("SUPABASE_ANON_KEY", $null, "User")
   ```
5. Your data stays in Supabase until you delete the project there (Project Settings, General, Delete project).
