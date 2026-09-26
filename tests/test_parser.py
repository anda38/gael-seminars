from datetime import datetime

from bs4 import BeautifulSoup

from generate_calendar import (
    DetailPage,
    ProgrammeEntry,
    event_title,
    extract_presentation_title,
    parse_programme_date,
)


def test_parse_september_date():
    dt = parse_programme_date("Jeudi 03 sep")
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 3
    assert dt.hour == 11
    assert dt.minute == 15


def test_parse_january_date():
    dt = parse_programme_date("Jeudi 07 jan")
    assert dt.year == 2027
    assert dt.month == 1
    assert dt.day == 7


def test_parse_first_of_month():
    dt = parse_programme_date("Jeudi 1er oct")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 1


def test_extract_french_presentation_title():
    soup = BeautifulSoup(
        """
        <html><body>
        <p>Titre de sa présentation : Means-Tested Subsidies and Market Power:
        Evidence from a Heat Pump Program</p>
        </body></html>
        """,
        "html.parser",
    )
    assert (
        extract_presentation_title(soup)
        == "Means-Tested Subsidies and Market Power: Evidence from a Heat Pump Program"
    )


def test_title_priority_detail_then_keywords_then_speaker():
    entry = ProgrammeEntry(
        date_text="Jeudi 13 mai",
        date=parse_programme_date("Jeudi 13 mai"),
        speaker="Matthieu STIGLER",
        institution="Université de Genève",
        keywords="économie environnementale, changement climatique",
    )

    assert event_title(entry, None) == (
        "GAEL — économie environnementale, changement climatique"
    )

    detail = DetailPage(
        url="https://gael.example/seminar",
        title="An Actual Research Talk",
    )
    assert event_title(entry, detail) == "GAEL — An Actual Research Talk"
