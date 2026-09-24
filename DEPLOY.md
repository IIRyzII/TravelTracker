# Putting ORBIT online

This guide takes ORBIT from your computer to a public website that people can
sign up to and install on their phones. The core (accounts, globe, friends,
trips) only needs steps 1–2. Steps 3–5 add Google sign-in, live Google Maps
results in the planner, and password-reset emails.

Prices below are rough and change often — check each provider's pricing page.

## 1. Deploy on Render (about $7–8/month)

ORBIT keeps its data in a SQLite file, so it needs a host with a **persistent
disk**. The repo includes a `Dockerfile` that runs on any container host, and a
`render.yaml` Blueprint that sets up [Render](https://render.com) for you.

1. Create a Render account and connect your GitHub.
2. **New → Blueprint** → choose this repository. Render reads `render.yaml` and
   creates a web service called `orbit` with a 5 GB disk at `/data`
   (Starter instance, since disks need a paid instance). The disk holds the
   databases, including the every-place one (see below).
3. When it asks for environment variables, set `APP_URL` to the address Render
   gives the service (e.g. `https://orbit-abcd.onrender.com`). Leave the
   optional ones blank for now. `SECRET_KEY` is generated for you.
4. Deploy. When it's live, `https://…/healthz` returns `{"ok": true}`.

Render snapshots persistent disks daily, which covers backups (see Render's
disk docs for how long snapshots are kept and how to restore one).

**Your own domain** (≈ $10–15/year from any registrar): in Render open the
service → Settings → Custom Domains → add `yourdomain.com`, create the DNS
record it shows you, then change `APP_URL` to `https://yourdomain.com`.
HTTPS certificates are automatic.

## 2. Check the legal pages still match

`/privacy` and `/terms` (`static/legal/`) describe ORBIT as it runs today:
hosted on Render in Frankfurt, emails through Resend, live planner results from
Google Maps, city search on ORBIT's own data, no Google sign-in, accounts
deleted after 3 months without use.
If you change any of that, update the pages too (each has a comment listing
what to watch). It's worth having them checked by someone qualified.

Also check with the ICO whether you need to pay the data protection fee
(ico.org.uk has a short self-assessment). Most people running a service like
this from the UK do.

## 3. "Continue with Google" (optional, free)

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project.
2. **APIs & Services → OAuth consent screen**: External, app name "ORBIT",
   your support email, and the privacy/terms URLs from step 2. Publish it
   ("In production"). ORBIT only asks for the basic email and profile scopes.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   type *Web application*. Under **Authorized JavaScript origins** add
   `https://yourdomain.com` (and your `onrender.com` address). For local
   testing also add `http://localhost` and `http://localhost:5000`.
   No redirect URI is needed.
4. Copy the **Client ID** into Render as `GOOGLE_CLIENT_ID`. The button appears
   on the sign-in card automatically.
5. Update the privacy policy. With Google sign-in on, the sign-in screen loads
   Google's script, so Google receives visitors' IP addresses and may set
   cookies. Say so in the "Services we use" and "Cookies" sections.

## 4. Live Google Maps results in the planner (optional, pay-per-use)

Without a key the planner uses the curated lists and starter shortlists. With
one, it shows live top-rated places.

1. In the same Google Cloud project, enable **Places API (New)** and set up
   billing.
2. **Credentials → Create credentials → API key**. Edit the key → **API
   restrictions → Restrict key → Places API (New)** only.
3. **Protect your bill:**
   - Each live shortlist makes **4** Places requests (one per category).
     Google's terms only allow keeping a place's ID, so ORBIT doesn't cache
     results: every live shortlist, including changing the radius, is a fresh
     lookup. For the same reason, saved trips keep each place's name, place ID
     and Maps link, but not its rating, address or opening hours.
   - ORBIT limits each user to `PLACES_FREE_DAILY` live shortlists a day
     (default 3) and the whole site to `PLACES_GLOBAL_DAILY_CAP` (default 300,
     which is about 1,200 requests a day). Once a limit is hit, the planner
     quietly falls back to the curated lists.
   - Also set a daily request quota for the API in Cloud Console (APIs &
     Services → Places API (New) → Quotas), plus a **budget alert** under
     Billing.
4. Put the key in Render as `GOOGLE_MAPS_API_KEY`.

## 5. Emails (needed before launch)

ORBIT sends two kinds of email: password resets, and a warning a week before
deleting an account that hasn't been used for 3 months. Without an email
service, "Forgot your password?" can't reach anyone, and unused accounts are
never deleted, because ORBIT won't delete an account without warning its owner first.
[Resend](https://resend.com) has a free tier that covers a small app.

1. Create a Resend account → **Domains → Add domain** → add the DNS records it
   shows (they prove you own the domain and keep emails out of spam).
2. **API Keys → Create** → put it in Render as `RESEND_API_KEY`.
3. Set `MAIL_FROM` to e.g. `ORBIT <noreply@yourdomain.com>` (it must be on the
   verified domain).

Locally, with no key, the reset link is printed in the server log instead.

## Every place on Earth (automatic)

City search and the globe's Town zoom use a database of every populated place
in GeoNames' free list: about 4–5 million towns, villages and hamlets. It
lives on the server's disk as `places.db` (about 0.5 GB), next to ORBIT's main
database.

- **On Render it builds itself.** On first start the server downloads
  GeoNames' full list (about 400 MB) and builds the database in the background.
  That takes roughly 10–30 minutes on a small instance. Until it's ready,
  search uses the list that ships with the app (towns of 1,000+ people), and
  the globe shows no villages. It only happens once, because the database
  stays on the disk.
- **To refresh it** (GeoNames updates daily, but once a year is plenty), delete
  `/data/places.db` in Render's Shell and restart, or run
  `flask --app wsgi build-places` there.
- **Locally** it's optional: `flask --app wsgi build-places` builds it next to
  `traveltracker.db`.

`scripts/build_places.py` is separate and also optional. It refreshes the
smaller list that ships with the app (towns of 1,000+, used for the globe's
city and town labels). Commit its output if you run it.

## Settings reference

| Variable | Needed? | What it does |
|---|---|---|
| `ORBIT_ENV` | yes (`production`) | Secure cookies, HSTS, refuses to start without `SECRET_KEY` |
| `SECRET_KEY` | yes | Signs sessions and reset links. Changing it signs everyone out |
| `APP_URL` | yes | Public address, used in reset emails, link previews and the sitemap |
| `DATABASE_PATH` | set by the Dockerfile | `/data/traveltracker.db` |
| `GOOGLE_CLIENT_ID` | optional | Turns on Google sign-in |
| `GOOGLE_MAPS_API_KEY` | optional | Live planner results (or `config.json` locally) |
| `RESEND_API_KEY`, `MAIL_FROM` | for resets | Password-reset emails |
| `PLACES_FREE_DAILY` / `PLACES_PRO_DAILY` | optional | Live shortlists per user per day (default 3 / 40) |
| `PLACES_GLOBAL_DAILY_CAP` | optional | Site-wide live shortlists per day (default 300) |
| `TRUST_PROXY` | optional | Trust one proxy's `X-Forwarded-*` headers (on by default in production) |
| `PLACES_DB_PATH` | optional | Where the every-place database lives (default: next to `DATABASE_PATH`) |
| `PLACES_AUTO_BUILD` | optional | Build that database on first start (on by default in production) |
| `ACCOUNT_INACTIVE_DAYS` | optional | Delete accounts unused for this many days (default 90, `0` = never). A warning email goes out a week before |
| `RATELIMIT_ENABLED` | optional | Set `0` only for local testing |

## Running it locally

```
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python app.py                                         # http://127.0.0.1:5000
```

Checks:

```
pytest                                                # API, auth, security, planner
RATELIMIT_ENABLED=0 gunicorn wsgi:app -b 127.0.0.1:5055 &
python tests/e2e/smoke.py http://127.0.0.1:5055 screenshots   # real browser, phone + desktop
```

GitHub Actions (`.github/workflows/ci.yml`) runs both on every push.

### Keeping your old local profile

Profiles made before accounts existed have no email or password. To claim
yours in a local database:

```
flask --app wsgi claim-profile "Your name" you@example.com
```

It asks for a new password, then you can sign in with that email. A fresh
deployment starts with an empty database.

## Regenerating assets

| Script | When |
|---|---|
| `scripts/build_places.py` | optional: refresh the bundled list of towns (see "Every place on Earth") |
| `scripts/split_cities.py` | after editing `data/geonames-cities.json` by hand (`build_places.py` runs it for you) |
| `scripts/make_icons.py` | after changing the logo |
| `scripts/make_og_image.py URL` | to refresh the link-preview image |

If you add a JavaScript module, list it in `SHELL` in `static/js/sw.js` (a test
checks this) and bump `VERSION` there.
