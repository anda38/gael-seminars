#!/usr/bin/env python3
"""
Generate an iCalendar feed from the GAEL 2026-2027 seminar programme.

Source calendar:
https://gael.univ-grenoble-alpes.fr/fr/calendrier-2026-2027-0

Enrichment strategy:
1. Read date / speaker / institution / keywords from the annual programme.
2. Try to find an individual GAEL seminar page for that speaker.
3. If found, extract the presentation title, abstract, exact time and room.
4. If not found yet, use the programme keywords as the event title.
5. Keep a stable UID based on date + speaker, so events are updated instead
   of duplicated when GAEL later publishes more information.

Every event includes a direct link back to the GAEL annual programme.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urljoin, urlparse

import pytz
import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event

CALENDAR_URL = "https://gael.univ-grenoble-alpes.fr/fr/calendrier-2026-2027-0"
GAEL_BASE = "https://gael.univ-grenoble-alpes.fr"
GAEL_HOME = f"{GAEL_BASE}/fr"
GAEL_SEMINARS = f"{GAEL_BASE}/fr/activites-scientifiques/seminaires"

OUTPUT_FILE = "seminars.ics"

ACADEMIC_YEAR_START = 2026
TIMEZONE = pytz.timezone("Europe/Paris")

# GAEL announced that the 2026-2027 seminar series moved to 11:15.
# Individual pages override this whenever they publish an exact time.
DEFAULT_TIME = "11:15"
DEFAULT_DURATION_MINUTES = 75

# Keep the location conservative unless an individual page confirms a room.
DEFAULT_LOCATION = "GAEL, Université Grenoble Alpes"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; gael-seminars-calendar/1.0; "
        "+https://github.com/anda38/gael-seminars)"
    )
}
REQUEST_TIMEOUT = 30

MONTHS = {
    "jan": 1, "janv": 1, "janvier": 1,
    "fev": 2, "fevr": 2, "fevrier": 2,
    "fév": 2, "févr": 2, "février": 2,
    "mar": 3, "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7, "juillet": 7,
    "aou": 8, "aout": 8, "août": 8,
    "sep": 9, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "déc": 12, "decembre": 12, "décembre": 12,
}


@dataclass
class ProgrammeEntry:
    date_text: str
    date: datetime
    speaker: str
    institution: str
    keywords: str


@dataclass
class DetailPage:
    url: str
    title: str | None = None
    abstract: str | None = None
    exact_time: str | None = None
    location: str | None = None


def clean_text(value: str) -> str:
    """Collapse whitespace and decode common HTML entities."""
    return " ".join(html.unescape(value or "").replace("\xa0", " ").split())


def ascii_key(value: str) -> str:
    """Accent/case-insensitive key used only for matching."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())


def surname_tokens(speaker: str) -> list[str]:
    """
    Return useful surname-ish tokens for URL matching.

    The GAEL programme tends to put surnames in uppercase, but HTML extraction
    may lose that formatting, so we use the last meaningful tokens.
    """
    tokens = ascii_key(speaker).split()
    stop = {"de", "du", "des", "le", "la", "van", "von"}
    useful = [t for t in tokens if len(t) >= 3 and t not in stop]
    return useful[-2:] if len(useful) >= 2 else useful


def stable_uid(date_value: datetime, speaker: str) -> str:
    """Do not include title/time: they may change when a detail page appears."""
    base = f"{date_value.date().isoformat()}::{ascii_key(speaker)}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
    return f"{digest}@gael-seminars"


def parse_programme_date(text: str) -> datetime:
    """
    Parse GAEL programme dates such as:
      'Jeudi 03 sep'
      'Jeudi 1er oct'
      'Mardi 02 fév'

    The academic year is Sep-Dec 2026, Jan-Aug 2027.
    """
    normalized = clean_text(text).lower()
    normalized = (
        normalized.replace("1^{er}", "1")
        .replace("1er", "1")
        .replace("1 er", "1")
        .replace(".", " ")
    )

    # Ignore weekday names and retain first day/month pair.
    match = re.search(
        r"\b(\d{1,2})\s+([a-zàâäéèêëîïôöùûüç]+)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not parse GAEL date: {text!r}")

    day = int(match.group(1))
    month_raw = ascii_key(match.group(2)).replace(" ", "")

    month = None
    for key, value in MONTHS.items():
        if ascii_key(key).replace(" ", "") == month_raw or month_raw.startswith(
            ascii_key(key).replace(" ", "")
        ):
            month = value
            break

    if month is None:
        raise ValueError(f"Unknown month in GAEL date: {text!r}")

    year = ACADEMIC_YEAR_START if month >= 9 else ACADEMIC_YEAR_START + 1
    hour, minute = map(int, DEFAULT_TIME.split(":"))
    naive = datetime(year, month, day, hour, minute)
    return TIMEZONE.localize(naive)


def get(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def scrape_programme() -> list[ProgrammeEntry]:
    """Read the annual GAEL table."""
    soup = BeautifulSoup(get(CALENDAR_URL).text, "html.parser")

    table = soup.find("table")
    if table is None:
        raise RuntimeError("Could not find the seminar table on the GAEL calendar page.")

    entries: list[ProgrammeEntry] = []

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        date_text = clean_text(cells[0].get_text(" ", strip=True))
        speaker = clean_text(cells[1].get_text(" ", strip=True))
        institution = clean_text(cells[2].get_text(" ", strip=True))
        keywords = clean_text(cells[3].get_text(" ", strip=True))

        # Header row / separators / multi-day events that are not a single seminar.
        if ascii_key(date_text) in {"date"} or ascii_key(speaker) in {"invite e", "speaker"}:
            continue
        if not speaker:
            continue

        # The AEE workshop is a 2-day event, not one of the ordinary GAEL seminars.
        # Keep it out of this feed rather than guessing a time.
        if "25&26" in date_text.replace(" ", "") or "25 & 26" in date_text:
            continue

        try:
            date_value = parse_programme_date(date_text)
        except ValueError:
            print(f"[skip] Unparsed date: {date_text!r} — {speaker}")
            continue

        entries.append(
            ProgrammeEntry(
                date_text=date_text,
                date=date_value,
                speaker=speaker,
                institution=institution,
                keywords=keywords,
            )
        )

    if not entries:
        raise RuntimeError("GAEL table was found, but no seminar entries were parsed.")

    return entries


def sitemap_urls() -> list[str]:
    """
    Discover GAEL URLs from sitemap.xml if available.

    We only keep French news/event pages; speaker names are then used to narrow
    the candidates, so we do not crawl the whole website.
    """
    seeds = [
        f"{GAEL_BASE}/sitemap.xml",
        f"{GAEL_BASE}/sitemap_index.xml",
    ]
    seen: set[str] = set()
    collected: set[str] = set()

    def parse_sitemap(url: str, depth: int = 0) -> None:
        if url in seen or depth > 2:
            return
        seen.add(url)
        try:
            response = get(url)
        except requests.RequestException:
            return

        soup = BeautifulSoup(response.text, "xml")
        locs = [clean_text(x.get_text()) for x in soup.find_all("loc")]

        for loc in locs:
            if not loc:
                continue
            if loc.endswith(".xml"):
                parse_sitemap(loc, depth + 1)
            elif "/fr/actualites/" in loc:
                collected.add(loc)

    for seed in seeds:
        parse_sitemap(seed)

    return sorted(collected)


def crawl_known_listing_links() -> list[str]:
    """
    Fallback discovery from GAEL pages that expose recent/upcoming seminar links.
    """
    links: set[str] = set()

    for url in [GAEL_HOME, GAEL_SEMINARS, CALENDAR_URL]:
        try:
            soup = BeautifulSoup(get(url).text, "html.parser")
        except requests.RequestException:
            continue

        for a in soup.find_all("a", href=True):
            absolute = urljoin(GAEL_BASE, a["href"])
            if "/fr/actualites/" in absolute:
                links.add(absolute.split("#")[0])

    return sorted(links)


def candidate_detail_urls(entry: ProgrammeEntry, all_urls: Iterable[str]) -> list[str]:
    """
    Rank likely individual pages by speaker-name overlap in the URL.
    """
    tokens = surname_tokens(entry.speaker)
    if not tokens:
        return []

    scored: list[tuple[int, str]] = []
    for url in all_urls:
        path_key = ascii_key(urlparse(url).path.replace("-", " "))
        score = sum(1 for token in tokens if token in path_key)
        if score:
            scored.append((score, url))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in scored[:8]]


def looks_like_same_speaker(soup: BeautifulSoup, speaker: str) -> bool:
    """Avoid enriching an event from a false URL match."""
    page_text = ascii_key(soup.get_text(" ", strip=True))
    tokens = surname_tokens(speaker)
    return bool(tokens) and all(token in page_text for token in tokens[-1:])


def extract_presentation_title(soup: BeautifulSoup) -> str | None:
    """
    GAEL currently uses phrases such as:
      'Titre de sa présentation : ...'
      'Titre de la présentation : ...'
    """
    text = clean_text(soup.get_text("\n", strip=True))

    patterns = [
        r"Titre de (?:sa|la) présentation\s*:\s*(.+?)(?=\n|Résumé|Abstract|Le \d|$)",
        r"Title of (?:his|her|the) presentation\s*:\s*(.+?)(?=\n|Abstract|On \w|$)",
        r"Titre\s*:\s*(.+?)(?=\n|Résumé|Abstract|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            title = clean_text(match.group(1))
            if 4 <= len(title) <= 300:
                return title

    # Sometimes the label and value are in neighbouring HTML blocks.
    label_re = re.compile(r"titre.*présentation", re.IGNORECASE)
    label = soup.find(string=label_re)
    if label:
        parent = label.parent
        if parent:
            candidate = clean_text(parent.get_text(" ", strip=True))
            candidate = re.sub(
                r"^.*?titre.*?présentation\s*:\s*", "", candidate,
                flags=re.IGNORECASE
            )
            if 4 <= len(candidate) <= 300:
                return candidate

            nxt = parent.find_next()
            if nxt:
                candidate = clean_text(nxt.get_text(" ", strip=True))
                if 4 <= len(candidate) <= 300:
                    return candidate

    return None


def extract_abstract(soup: BeautifulSoup) -> str | None:
    """
    Extract a nearby abstract when GAEL labels it Résumé/Abstract.
    Conservative on purpose: a wrong abstract is worse than no abstract.
    """
    text = clean_text(soup.get_text("\n", strip=True))

    patterns = [
        r"(?:Résumé|Abstract)\s*:\s*(.+?)(?=(?:\nLe\s+\d|\nLocalisation|\nPublié|\nMis à jour|$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            abstract = clean_text(match.group(1))
            if len(abstract) >= 30:
                return abstract[:4000]

    return None


def extract_time(soup: BeautifulSoup) -> str | None:
    """Find the first plausible time such as 11h15 or 11:15."""
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:)\s*([0-5]\d)\b", text, re.IGNORECASE)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return None


def extract_location(soup: BeautifulSoup) -> str | None:
    """
    Prefer an explicit room reference. GAEL detail pages often mention 'salle 227'.
    """
    text = clean_text(soup.get_text(" ", strip=True))
    room = re.search(
        r"\b(?:salle|amphi(?:théâtre)?|room)\s+[A-Za-z0-9._-]+\b",
        text,
        flags=re.IGNORECASE,
    )
    if room:
        return f"GAEL, {clean_text(room.group(0))}"

    # Do not invent a room from the lab's postal address.
    return None


def fetch_detail(entry: ProgrammeEntry, all_urls: list[str]) -> DetailPage | None:
    """Find and parse the best individual seminar page, if one exists yet."""
    for url in candidate_detail_urls(entry, all_urls):
        try:
            soup = BeautifulSoup(get(url).text, "html.parser")
        except requests.RequestException:
            continue

        if not looks_like_same_speaker(soup, entry.speaker):
            continue

        # Strong signal that this really is a seminar/event page.
        page_text = ascii_key(soup.get_text(" ", strip=True))
        if "seminaire" not in page_text and "presentation" not in page_text:
            continue

        title = extract_presentation_title(soup)
        exact_time = extract_time(soup)
        location = extract_location(soup)
        abstract = extract_abstract(soup)

        # We still accept a matching seminar page without a published title:
        # it may contain exact room/time and get its title later.
        return DetailPage(
            url=url,
            title=title,
            abstract=abstract,
            exact_time=exact_time,
            location=location,
        )

    return None


def with_time(date_value: datetime, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    naive = datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
    )
    return TIMEZONE.localize(naive)


def event_title(entry: ProgrammeEntry, detail: DetailPage | None) -> str:
    """
    Priority requested by the user:
      1. actual talk title
      2. annual-programme keywords
      3. speaker name
    """
    if detail and detail.title:
        return detail.title
    if entry.keywords and "venir" not in ascii_key(entry.keywords):
        return entry.keywords
    return entry.speaker


def build_event(entry: ProgrammeEntry, detail: DetailPage | None) -> Event:
    event = Event()
    event.name = event_title(entry, detail)

    hhmm = detail.exact_time if detail and detail.exact_time else DEFAULT_TIME
    event.begin = with_time(entry.date, hhmm)
    event.duration = timedelta(minutes=DEFAULT_DURATION_MINUTES)

    event.location = (
        detail.location if detail and detail.location else DEFAULT_LOCATION
    )

    detail_url = detail.url if detail else None

    lines = [
        f"Intervenant·e : {entry.speaker}",
        f"Établissement : {entry.institution or 'Non indiqué'}",
    ]

    if entry.keywords:
        lines.append(f"Mots-clés : {entry.keywords}")

    if detail and detail.abstract:
        lines.extend(["", "Résumé :", detail.abstract])

    lines.extend(
        [
            "",
            f"Programme GAEL : {CALENDAR_URL}",
        ]
    )

    if detail_url:
        lines.append(f"Page du séminaire : {detail_url}")
    else:
        lines.append(
            "Page détaillée : pas encore publiée au moment de la dernière mise à jour."
        )

    event.description = "\n".join(lines)

    # Clicking the event URL opens the most useful page available.
    # The annual programme link is always also present in DESCRIPTION.
    event.url = detail_url or CALENDAR_URL

    event.uid = stable_uid(entry.date, entry.speaker)

    return event


def generate_calendar() -> tuple[Calendar, int, int]:
    entries = scrape_programme()

    urls = sitemap_urls()
    if not urls:
        urls = crawl_known_listing_links()
    else:
        # Also include currently exposed listing links in case the sitemap lags.
        urls = sorted(set(urls) | set(crawl_known_listing_links()))

    calendar = Calendar()
    enriched = 0

    for entry in entries:
        detail = fetch_detail(entry, urls)
        if detail:
            enriched += 1
        calendar.events.add(build_event(entry, detail))

    return calendar, len(entries), enriched


def main() -> None:
    calendar, total, enriched = generate_calendar()

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as handle:
        handle.writelines(calendar)

    print(f"Wrote {OUTPUT_FILE}")
    print(f"Parsed {total} programme entries")
    print(f"Enriched {enriched} entries with individual GAEL pages")


if __name__ == "__main__":
    main()
