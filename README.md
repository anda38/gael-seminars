# GAEL seminars → calendar

Automatically builds an `.ics` calendar from the
[GAEL 2026–2027 seminar programme](https://gael.univ-grenoble-alpes.fr/fr/calendrier-2026-2027-0).

The feed is designed to stay useful even before GAEL publishes a full page for a future seminar.

## Event-title logic

For each seminar:

1. If GAEL has published an individual seminar page with the actual talk title, use:
   `GAEL — <presentation title>`
2. Otherwise, use the main keywords from the annual programme:
   `GAEL — <keywords>`
3. If neither is available, fall back to:
   `GAEL — <speaker>`

The UID is based only on **date + speaker**, so when a detail page appears later the existing calendar event is updated instead of duplicated.

## What goes into each calendar event

- actual talk title when available;
- speaker;
- institution;
- annual-programme keywords;
- abstract when a detailed page exposes one;
- exact published time and room when available;
- otherwise the 2026–2027 default seminar time of **11:15**;
- a link to the **main GAEL annual programme in every event**;
- a link to the individual seminar page when one exists.

The event's clickable `URL` field opens the individual seminar page when available, otherwise the annual programme. The annual programme URL is always also present in the event description.

## Automatic enrichment

GAEL often announces speakers on the annual programme before publishing their individual seminar pages.

The GitHub Action runs every day:

```text
annual programme
        ↓
date + speaker + institution + keywords
        ↓
find matching individual GAEL seminar page, if published
        ↓
title + abstract + exact time + room
        ↓
seminars.ics
```

If no detail page exists yet, the feed still contains the seminar using the keywords as its title. When GAEL later publishes the page, the same calendar event is enriched automatically.

## Subscribe to the calendar

After pushing this repository to GitHub, subscribe to the raw file rather than importing it once.

If your repository is:

```text
https://github.com/anda38/gael-seminars
```

the subscription URL will normally be:

```text
https://raw.githubusercontent.com/anda38/gael-seminars/main/seminars.ics
```

Use **Subscribe to calendar / Add calendar by URL** in your calendar app. Do not simply import the `.ics` file if you want future updates.

Note: calendar clients decide how often they refresh subscribed feeds, so GitHub may update before your phone/laptop calendar does.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generate_calendar.py
```

This writes:

```text
seminars.ics
```

## GitHub Actions

The workflow in `.github/workflows/update-calendar.yml`:

- runs every day;
- can also be run manually;
- regenerates `seminars.ics`;
- commits only when the feed actually changed.

For a public repository, the default `GITHUB_TOKEN` with `contents: write` is enough as long as repository settings allow Actions to write contents.

## Important assumptions

### Time

GAEL announced that the 2026–2027 seminar series moved to **11:15**. The scraper therefore uses 11:15 only as a fallback. If an individual seminar page publishes a different time, that time wins.

### Room

The scraper does **not** assume room 227 for every seminar. It uses a specific room only when it can find one on the individual page. Otherwise the location stays generic:

```text
GAEL, Université Grenoble Alpes
```

### Event duration

The default duration is 75 minutes because the annual programme does not provide an end time. Change `DEFAULT_DURATION_MINUTES` in `generate_calendar.py` if you prefer another duration.

### Academic year

The date parser assumes:

- September–December → 2026
- January–August → 2027

When GAEL publishes a 2027–2028 programme, update:

```python
CALENDAR_URL
ACADEMIC_YEAR_START
```

## Why detail-page discovery uses the sitemap

The annual programme does not consistently link each speaker to an individual seminar page. The scraper therefore:

1. reads the GAEL sitemap;
2. keeps `/fr/actualites/` pages;
3. narrows candidates using the speaker's name;
4. validates the page content before extracting details.

If the sitemap is unavailable, it falls back to links exposed by the GAEL home/seminar pages.

This avoids depending on Google or another external search engine.

## Files

```text
.
├── .github/
│   └── workflows/
│       └── update-calendar.yml
├── tests/
│   └── test_parser.py
├── .gitignore
├── generate_calendar.py
├── requirements.txt
├── README.md
└── seminars.ics
```
