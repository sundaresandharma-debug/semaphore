# Launch checklist

Status of every launch item, where it lives and how it was checked.
**Done** means it is in the code and was tested in a browser.
**You** means it needs an action from the site owner before launch.

## Legal and trust

| Item | Status | Where / notes |
| --- | --- | --- |
| Privacy policy | Done | `public/privacy.html`, linked in every footer and on the sign-up form |
| Terms of service | Done | `public/terms.html`, accepted with a checkbox at sign-up |
| Refund policy | Done | `public/refunds.html`: the site is free, so there is nothing to refund |
| Cookie policy | Done | `public/cookies.html` lists every cookie and storage item |
| Cookie consent banner | Done | Two equal buttons, *Necessary only* and *Allow error reports*; reopened from *Cookie settings* in the footer |
| Form consents | Done | Sign-up requires unticked-by-default checkboxes for the terms and for age |
| Age consent for children's data | Done | Accounts need an 18+ confirmation (India's DPDP Act treats under-18s as children); the demos need no account |
| Business details | Done | Footer and legal pages: Sundaresan D, India, student project |
| Contact email | **You** | Replace `[your-email]` in `public/index.html` and `public/*.html` (search for `contact-email`) |
| No dark patterns or hidden fees | Done | No pre-ticked boxes, equal-weight consent buttons, no fees anywhere, deletion is one form |
| No fake reviews or unsupported claims | Done | No testimonials or ratings. Every claim on the site comes from a check the code runs and shows |
| Legal review | **You** | The policies describe exactly what the code does, but they are not legal advice |

## Privacy and data

| Item | Status | Where / notes |
| --- | --- | --- |
| Data minimisation | Done | Without an account nothing personal is stored. With one: email, password hash (inside Supabase), consent record, and only the results the user saves |
| Data deletion requests | Done | *Delete all saved results* and *Delete my account* on the Account page; email route described in the privacy policy |
| Delete account button | Done | Needs the password again, then removes the account and every saved row (`on delete cascade`) |
| Third-party SDK audit | Done | The browser loads no third-party code, enforced by `Content-Security-Policy: script-src 'self'` in `vercel.json`. The Python backend uses only the standard library and calls Supabase's REST API directly |
| API keys off the frontend | Done | Supabase keys live only in Vercel environment variables, read by `accounts.py`. `public/` contains no keys |
| Licensed fonts and images | Done | No web fonts are downloaded: the page uses the visitor's system fonts. There are no photos; the icons and the signal graphic are simple shapes drawn for this project in SVG |

## Accounts

| Item | Status | Where / notes |
| --- | --- | --- |
| Real login and logout | Done in code, **You** to switch on | `accounts.py` with Supabase Auth; follow `docs/SETUP_ACCOUNTS.md` |
| Password reset | Done | Email link, then a new-password form; the same answer is shown whether or not the address exists |
| Row level security | Done | `supabase/schema.sql`: select, insert and delete only where `auth.uid() = user_id`; no update policy |
| Rate limiting | Done | Per-client sliding window in `webcore.py` (10 sign-in actions, 30 demo runs per minute and so on), Supabase Auth's own limits, and a database trigger (30 saves per hour, 200 per account). The in-memory limit is per server instance |
| Database backups | Done in code, **You** to switch on | `.github/workflows/db-backup.yml`: nightly, AES-256 encrypted, kept 14 days; needs two GitHub secrets |
| Transactional email | **You** | Connect an SMTP provider in Supabase so confirmation and reset emails reach real users |

## Quality and accessibility

| Item | Status | Where / notes |
| --- | --- | --- |
| Loading states | Done | Live timer and overlay while the server runs a demo; buttons show *Signing in...*, *Saving...* and so on |
| Skeleton loaders | Done | First page load, test list and saved results |
| Empty states | Done | Saved results, test results, demo log, Playground queue |
| Clear error messages | Done | Every request goes through one function that turns failures into plain sentences, with a reference code for server errors |
| Form validation | Done | Per-field messages linked with `aria-describedby`, focus moves to the first problem; the server validates again |
| Alt text | Done | There are no `<img>` elements; meaningful SVGs have `role="img"` and an `aria-label`, decorative ones `aria-hidden` |
| Colour contrast | Done | Every text and background pair meets WCAG AA (4.5:1) in both light and dark themes, checked with a script |
| Keyboard navigation | Done | *Skip to content* link, visible focus outline, focus moves to each section's heading, the intro dialog closes with Esc |
| Mobile layout | Done | No horizontal scrolling at 390 px on every page, including the legal pages |
| Custom 404 page | Done | `public/404.html` |
| Error tracking | Done | Server errors are logged as JSON with a reference code (Vercel > Logs). Browser errors are reported only with consent |
| Analytics | Not installed | Left out on purpose: nothing tracks visitors |
| Onboarding flow | Done | Three-step introduction on the first visit, after the consent choice; *Show the introduction* in the footer replays it |
| Security headers | Done | CSP, `X-Frame-Options: DENY`, HSTS, `Referrer-Policy`, `Permissions-Policy` in `vercel.json` |
