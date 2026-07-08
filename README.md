# ORBIT — TravelTracker

A globe-first travel tracker. Show off every country you've set foot in on a big
interactive 3D globe, keep a wishlist of dream places, add friends with a share
code and overlay their map on yours, and turn any dream destination into a
shortlist of sights, activities, food and nights out.

![stack](https://img.shields.io/badge/stack-Flask%20%2B%20SQLite%20%2B%20globe.gl-3987e5)

## Run it

```
pip install -r requirements.txt
python app.py
```

then open **http://127.0.0.1:5000** — or just double-click `run.bat`.

## Features

- **Globe home screen** — dark, high-contrast 3D globe. Visited countries in
  blue, wishlist in amber. Click any country to log it; search box flies you there.
- **Drill-down zoom** — starts at continent level (click a continent to dive in),
  zoom for countries, keep zooming for cities, then towns (137,000+ places
  down to 1,000-person villages, bundled locally — browsing never costs an
  API call). A pill in the corner
  jumps between levels. Click any town to log it, dream-list it or plan a trip;
  visited towns glow blue on the globe, wishlisted ones amber.
- **Logbook** — your travels in depth: continents → countries → cities & towns,
  with counts per continent. Click anything to fly there; logging a city
  automatically marks its country visited.
- **Stats rail** — countries visited, % of the world, continents, dream-list count.
- **Friends** — every profile gets a 6-character share code. Add a friend's code
  and hit *Compare on globe*: only-you / both / only-them in three colours.
- **Wishlist** — free-text dream places ("Crete, Greece") that auto-match to
  countries on the globe.
- **Trip planner** — live top-rated places from Google Maps (see below), or 22
  hand-curated destination shortlists when no API key is set. Every item links
  straight to its Google Maps page so you can check it's real. Tick the picks
  you want, then save the shortlist as a planned trip.
- **My trips** — saved shortlists with progress tracking: check things off as
  you do them, drop the duds, follow the Maps links on the ground. Add your
  flight number and dates for airline context and closed-while-you're-there flags.
- **Plan with friends** — hit *Plan together* on a friend, save the trip, and
  it lands in both of your trip lists: shared check-offs, ♥ voting to pick the
  group's favourites, and a crew row to invite more people.
- **City search** — the globe search box also finds cities (free geocoder, no
  key needed) and flies you to them.

## Live results from Google Maps (optional)

Out of the box the planner uses the bundled curated lists. To get **live,
top-rated, filterable results** (rating + review counts, ranked best-first):

1. Get a key from [Google Cloud Console](https://console.cloud.google.com/) —
   create a project, enable the **Places API (New)**, create an API key.
   Google's free tier comfortably covers personal use.
2. Copy `config.example.json` to `config.json` and paste your key in
   (or set the `GOOGLE_MAPS_API_KEY` environment variable).
3. Restart the app. The planner badge switches from "Curated" to
   "Live · Google Maps". If the key ever fails, it falls back to the curated
   lists automatically.

`config.json` is gitignored so your key never gets committed.

## How it's put together

| Piece | What it is |
|---|---|
| `app.py` | Flask backend + SQLite (`traveltracker.db`), all JSON API |
| `data/activities.json` | curated destination shortlists for the planner |
| `static/js/app.js` | globe (globe.gl), views, all UI logic — no build step |
| `static/data/countries.geojson` | Natural Earth 110m country polygons (bundled, works offline) |
| `static/data/cities.json` | 137k cities, towns & villages (pop ≥ 1,000) from [GeoNames](https://www.geonames.org/) (CC BY 4.0), lazy-loaded when you zoom in |
| `Visited_Places.DB` | the original CLI's database — imported automatically into the first profile created |

Profiles are name-only (no passwords) — it's a self-hosted app for you and your
friends. Everyone who opens the site creates a profile, and friendships are
mutual via share codes.
