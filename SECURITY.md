# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

1. Go to the **Security** tab of this repository on GitHub.
2. Click **Report a vulnerability** (private vulnerability reporting).
3. Describe what you found, how to reproduce it, and what you think the impact is.

You can expect an acknowledgement within a reasonable time. Please allow time for a fix before sharing details publicly.

## What to include (and what not to)

Include: steps to reproduce, the app version, and what you expected to happen.

**Never include** your Supabase `service_role` key, database password, user passwords or session tokens in a report, an issue or a log you share.

## How this app handles security

- The app talks to **your own** Supabase project using only the public **anon** key.
- Access to data is limited by row-level security rules in the database: each signed-in user can only read and change their own rows.
- Uploaded files go to a **private** storage bucket, in a folder named after the user's ID.
- The "Remember me" sign-in is stored in Windows Credential Manager, not in a plain file.
- No secrets are written to logs or reports.
- Secure Delete runs as a database function that checks ownership on every query; the app is not given direct delete rights on its tables.

## Your responsibilities when running your own copy

- **Never** put the `service_role` or "secret" key in this app, in an environment variable used by the app, or in any file in this repository.
- Use a strong password for your Supabase account and for your app login.
- Consider turning off public sign-ups on your Supabase project if only you will use it.
- Keep your Python packages up to date (see the Changelog before updating).
- Make your own backups of important documents.

## If you accidentally published a key

1. Rotate the key immediately in the Supabase dashboard (Project Settings, API).
2. Remove it from the repository history, not just the latest commit.
3. Check your Supabase logs for activity you do not recognise.
