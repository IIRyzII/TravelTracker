# ORBIT — TravelTracker

A globe-first travel tracker. Show off every country you've set foot in on a big
interactive 3D globe, keep a wishlist of dream places, add friends and overlay
their map on yours, and turn any dream destination into a shortlist of sights,
activities, food and nights out. Works on phones and installs to the home screen.

![stack](https://img.shields.io/badge/stack-Flask%20%2B%20SQLite%20%2B%20globe.gl-3987e5)

## Run it

```
pip install -r requirements.txt
python app.py
```

then open **http://127.0.0.1:5000** — or just double-click `run.bat` on Windows.
To put it online, see **[DEPLOY.md](DEPLOY.md)**.

## Features

- **Accounts** — email + password or "Continue with Google". Password reset by
  email, change password (signs out other devices), download all your data,
  delete your account.
- **Globe home screen** — dark, high-contrast 3D globe. Visited countries in
  blue, wishlist in amber. Tap any country to log it; search flies you there.
- **Drill-down zoom** — continents → countries → cities → towns (137,000+ places
  down to 1,000-person villages, bundled locally and loaded in stages).
- **Logbook** — continents → countries → cities & towns, with counts. Logging
  a city automatically marks its country visited.
- **Friends** — share an invite link or a 6-character code, then *Compare on
  globe*: only-you / both / only-them in three colours.
- **Trip planner** — live top-rated places from Google Maps (a daily allowance
  per user), or 23 hand-curated destination shortlists. Tick your picks and save
  them as a trip.
- **My trips** — check things off, add flight and dates (places closed while
  you're there get flagged), plan with friends with shared check-offs and ♥ votes.
- **Phone-first** — bottom tab bar, bottom sheets, touch-sized controls,
  installable app (PWA) that opens offline.

## How it's put together

| Piece | What it is |
|---|---|
| `orbit/` | Flask app: `auth` (sessions, email/Google sign-in, resets), `account`, `travel`, `social`, `trips`, `planner`, `pages`, `plans` (free/pro limits), `db` (SQLite + migrations) |
| `app.py` / `wsgi.py` | local dev entry / production entry (`gunicorn wsgi:app`) |
| `static/js/` | ES modules, no build step: `main.js` boots, `globe.js` draws, `views/*` render each tab, `sw.js` is the service worker |
| `static/css/app.css` | all styling — desktop first, phone layout under `max-width: 720px` |
| `static/data/` | Natural Earth country borders; GeoNames places split into `cities-1.json` (≥15k people) and `cities-2.json` (smaller towns) |
| `data/activities.json` | curated destination shortlists for the planner |
| `data/geonames-cities.json` | source for the city files (`scripts/split_cities.py`) |
| `tests/` | pytest suite + `e2e/smoke.py` real-browser check at phone and desktop sizes |
| `Dockerfile`, `render.yaml` | production image and one-click Render setup |

Place data © [GeoNames](https://www.geonames.org/) (CC BY 4.0), borders ©
[Natural Earth](https://www.naturalearthdata.com/), globe by
[globe.gl](https://github.com/vasturiano/globe.gl), city search by
[Open-Meteo](https://open-meteo.com/).

## What's next

- **ORBIT Pro** — Stripe subscription. Plans already exist in the database
  (`users.plan`) and `orbit/plans.py` decides what each plan gets (e.g. more
  live Google Maps shortlists).
- **Travel map poster** — a print-ready map of your visited countries, sold as a
  download first, then printed on demand.
- **App stores** — wrap the installable app for Google Play (Trusted Web
  Activity) and the App Store (Capacitor).
