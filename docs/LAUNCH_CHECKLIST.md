# Launch checklist

Status of every launch item, where it lives and how it was checked.
**Done** means it is in the code and was tested in a browser.
**You** means it needs an action from the site owner before launch.

## Legal and trust

| Item | Status | Where / notes |
| --- | --- | --- |
| Privacy policy | Done | `public/privacy.html`, linked in every footer |
| Terms of service | Done | `public/terms.html`, linked in every footer |
| Refund policy | Done | `public/refunds.html`: the site is free, so there is nothing to refund |
| Cookie policy | Done | `public/cookies.html`: the site sets no cookies; it lists the three browser-storage items |
| Cookie consent banner | Done | Two equal buttons, *Necessary only* and *Allow error reports*; reopened from *Cookie settings* in the footer |
| Form consents | Not applicable | The site has no forms that collect personal data |
| Age consent for children's data | Not applicable | No personal data is collected from anyone, so the site is safe at any age |
| Business details | Done | Footer and legal pages: Sundaresan D, India, student project |
| No dark patterns or hidden fees | Done | No pre-ticked boxes, equal-weight consent buttons, no fees anywhere |
| No fake reviews or unsupported claims | Done | No testimonials or ratings. Every claim on the site comes from a check the code runs and shows |
| Legal review | **You** | The policies describe exactly what the code does, but they are not legal advice |

## Privacy and data

| Item | Status | Where / notes |
| --- | --- | --- |
| Data minimisation | Done | Nothing that identifies a visitor is stored; rate limiting uses a salted hash of the IP address, in memory, for one minute |
| Data deletion requests | Done | Nothing is stored about visitors; the privacy policy gives an email route for any request |
| Delete account button | Not applicable | The site has no accounts |
| Third-party SDK audit | Done | The browser loads no third-party code, enforced by `Content-Security-Policy: script-src 'self'` in `vercel.json`. The Python backend uses only the standard library |
| API keys off the frontend | Done | The site uses no API keys at all; `public/` contains none |
| Licensed fonts and images | Done | No web fonts are downloaded: the page uses the visitor's system fonts. There are no photos; the icons and the signal graphic are simple shapes drawn for this project in SVG |

## Accounts

The site has no accounts, so login, logout, password reset, row level security, database backups and
transactional email are not applicable. Rate limiting still applies:

| Item | Status | Where / notes |
| --- | --- | --- |
| Rate limiting | Done | Per-client sliding window in `webcore.py` (30 demonstration runs, 120 Playground actions per minute and so on). The limit is per server instance |

## Quality and accessibility

| Item | Status | Where / notes |
| --- | --- | --- |
| Loading states | Done | Live timer and overlay while the server runs a demo; buttons show their state |
| Skeleton loaders | Done | First page load |
| Empty states | Done | Demo log, Playground queue |
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
