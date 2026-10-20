# Switching on accounts (Supabase)

The site works without this. Until these steps are done, the Account page says
"Accounts are not switched on yet" and nothing else changes.

Time needed: about 15 minutes. Everything below is free on Supabase's and Vercel's free plans.

## 1. Create the Supabase project

1. Sign in at <https://supabase.com> and choose **New project**.
2. Pick the region closest to your visitors (for India: **South Asia (Mumbai)**).
3. Save the database password somewhere safe. You need it for backups.

## 2. Create the table and its security rules

1. In the project, open **SQL Editor > New query**.
2. Paste the whole of [`supabase/schema.sql`](../supabase/schema.sql) and press **Run**.

This creates the `saved_runs` table with row level security (each account can only read and
delete its own rows), a limit of 30 saves per hour and 200 in total per account, and
automatic deletion of an account's rows when the account is deleted.

## 3. Configure sign-in

In **Authentication**:

1. **Sign In / Providers > Email**: keep Email enabled and **Confirm email** on.
   Set the minimum password length to **8**.
2. **URL Configuration**:
   * **Site URL**: `https://semaphore-two.vercel.app` (your Vercel address)
   * **Redirect URLs**: add `https://semaphore-two.vercel.app/**`
3. **Emails > SMTP Settings**: Supabase's built-in email sender only delivers to your own
   team's addresses and only a few emails per hour. For real visitors, connect a free SMTP
   provider (for example Resend or Brevo) here. Without it, sign-up confirmation and
   password reset emails will not reach other people.

## 4. Give the keys to Vercel (server side only)

In Supabase open **Project Settings > API Keys** and copy the project URL, the
**publishable** key and the **secret** key. (Older projects show `anon` and
`service_role` keys instead; those work too.)

In Vercel open the project, then **Settings > Environment Variables**, and add:

| Name | Value |
| --- | --- |
| `SUPABASE_URL` | `https://<your-project>.supabase.co` |
| `SUPABASE_ANON_KEY` | the publishable (or anon) key |
| `SUPABASE_SERVICE_ROLE_KEY` | the secret (or service_role) key |
| `SITE_URL` | `https://semaphore-two.vercel.app` |

Then open **Deployments**, choose the latest one and press **Redeploy**.

These keys are only read by the Python functions in `api/`. They are never sent to the
browser: the page talks to `/api/auth` and `/api/account`, and the session lives in
HttpOnly cookies that page scripts cannot read. Never put the secret key in `public/`.

## 5. Nightly encrypted backups

The workflow in [`.github/workflows/db-backup.yml`](../.github/workflows/db-backup.yml)
makes an encrypted `pg_dump` every night and keeps each one for 14 days.

1. In Supabase press **Connect** (top of the dashboard) and copy the **Session pooler**
   connection string. Put your database password into it.
2. In GitHub open the repository's **Settings > Secrets and variables > Actions** and add:
   * `SUPABASE_DB_URL`: the connection string
   * `BACKUP_PASSPHRASE`: a long random passphrase (store a copy in a password manager)
3. Open **Actions > Database backup > Run workflow** once to check that it works.

To restore a backup, download the artifact from the workflow run, then:

```bash
gpg -d semaphore-db-YYYY-MM-DD.sql.gz.gpg | gunzip | psql "<connection string>"
```

## 6. Check it

1. Open the site, go to **Account > Create account** and sign up with an address you can read.
2. Open the confirmation email. The link signs you in.
3. Run a demonstration and press **Save this result**. It appears under **Account**.
4. Try **Forgot your password?**, then **Delete my account**.
