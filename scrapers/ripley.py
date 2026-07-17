import re
import time

import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://ripleychile.pandape.computrabajo.com"
SEARCH_URL = f"{BASE_URL}/Vacancies"

TARGET_COUNTRY = "Chile"

MAX_PAGES = 400  # safety cap; ~185 pages of 20 jobs as of 2026-07

# The site returns 403 for minimal user agents, so send
# full browser-like headers.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
PAGE_REQUEST_DELAY = 0.2  # seconds between listing page requests

SPANISH_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def clean_text(text):
    if not text:
        return None

    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_posted_date(text):
    if not text:
        return None

    match = re.match(r"(\d{1,2})\s+([a-záéíóúñ]+)", text.strip().lower())

    if not match:
        return None

    day = int(match.group(1))
    month = SPANISH_MONTHS.get(match.group(2)[:3])

    if not month:
        return None

    today = pd.Timestamp.today().normalize()

    try:
        date = pd.Timestamp(year=today.year, month=month, day=day)
    except ValueError:
        return None

    # Dates come without a year; a "future" date belongs to last year.
    if date > today + pd.Timedelta(days=2):
        date = pd.Timestamp(year=today.year - 1, month=month, day=day)

    return date.strftime("%Y-%m-%d")


def split_location(location):
    if not location:
        return None, None

    parts = [part.strip() for part in location.split(" - ", 1)]

    if len(parts) == 2:
        return parts[0], parts[1]

    return None, parts[0]


def request_with_retry(session, method, url, **kwargs):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            is_client_error = (
                e.response is not None and e.response.status_code < 500
            )
            if is_client_error or attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF * attempt)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF * attempt)


def get_card_field(card, icon_class):
    icon = card.select_one(f"i.{icon_class}")

    if not icon:
        return None

    # The icon sits inside an "icon-container" div; the field text
    # lives in that container's parent.
    icon_container = icon.find_parent("div", class_="icon-container")

    if not icon_container or not icon_container.parent:
        return None

    return clean_text(icon_container.parent.get_text())


def parse_card(card):
    href = card.get("href", "")
    match = re.search(r"/Detail/(\d+)", href)

    if not match:
        return None

    job_id = match.group(1)

    title_tag = card.select_one("h3")
    title = clean_text(title_tag.get_text()) if title_tag else None

    location = get_card_field(card, "icon-location-pin-1")
    state, city = split_location(location)

    date_tag = card.select_one(".vacancy-date")
    posted_date = parse_posted_date(
        date_tag.get_text() if date_tag else None
    )

    return {
        "title": title,
        "location": location,
        "city": city,
        "state": state,
        "country": TARGET_COUNTRY,
        "posted_date": posted_date,

        "job_id": job_id,
        "source": "ripley",

        "company_name": "Ripley",

        "schedule_type": get_card_field(card, "icon-clock"),
        "worker_type": get_card_field(card, "icon-sheet"),
        "job_location_type": get_card_field(card, "icon-buildings"),
        "vacancies": get_card_field(card, "icon-candidates"),

        "url": f"{BASE_URL}{href}",

        "description_short": None,
        "description": None,
    }


def scrape_ripley():
    jobs = []

    session = requests.Session()

    for page in range(1, MAX_PAGES + 1):
        params = {
            "PageNumber": page,
            "PageSize": 20,
        }

        response = request_with_retry(
            session,
            "GET",
            SEARCH_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select("a.card-vacancy")

        if not cards:
            break

        print(f"Ripley page {page}: {len(cards)} jobs")

        for card in cards:
            job = parse_card(card)

            if job:
                jobs.append(job)

        time.sleep(PAGE_REQUEST_DELAY)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
