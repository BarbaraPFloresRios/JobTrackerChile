import re
import time

import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://ripleychile.pandape.computrabajo.com"
SEARCH_URL = f"{BASE_URL}/ListVacancies"

TARGET_COUNTRY = "Chile"

# Pandapé category ids for professional/corporate roles. Store and
# operational categories are deliberately excluded: 11 Ventas,
# 16 Atención a clientes, 23 Servicios Generales/Aseo/Seguridad,
# 15 Almacén/Logística, 22 Producción/Operarios, 17 CallCenter,
# 20 Mantenimiento, 14 Otros (mostly guards and warehouse staff).
INCLUDED_CATEGORIES = {
    1: "Administración / Oficina",
    2: "Diseño / Artes gráficas",
    4: "Informática / Telecomunicaciones",
    5: "Dirección / Gerencia",
    6: "Contabilidad / Finanzas",
    9: "Ingeniería",
    13: "Recursos Humanos",
    18: "Compras / Comercio Exterior",
    21: "Mercadotecnia / Publicidad / Comunicación",
}

# Safety net for roles miscategorized under excluded categories
# (e.g. "Planificador" postings filed under Atención a clientes):
# keyword searches run across ALL categories, keeping only jobs
# whose title matches KEYWORD_TITLE_PATTERN, since the site search
# also matches descriptions and returns noise.
KEYWORD_SEARCHES = [
    "planificador",
    "planificacion",
    "demand",
    "forecast",
    "abastecimiento",
]

KEYWORD_TITLE_PATTERN = re.compile(
    r"planif|demand|forecast|s&op|abastecim", re.IGNORECASE
)

RESULTS_PER_PAGE = 20
MAX_PAGES = 100  # safety cap per category

# The site returns 403 for minimal user agents, so send
# full browser-like headers.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "es-CL,es;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
REQUEST_DELAY = 0.3  # seconds between requests

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

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = text.strip()

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


def parse_card(card, category_name):
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

    modality = (
        get_card_field(card, "icon-buildings")
        or get_card_field(card, "icon-building-house")
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
        "job_category": category_name,

        "schedule_type": get_card_field(card, "icon-clock"),
        "worker_type": get_card_field(card, "icon-sheet"),
        "job_location_type": modality,
        "vacancies": get_card_field(card, "icon-candidates"),

        "url": f"{BASE_URL}{href}",

        "description_short": None,
        "description": None,
    }


def fetch_listings(session, body_filter, label, category_name):
    jobs = []

    for page in range(1, MAX_PAGES + 1):
        body = {
            **body_filter,
            "PageNumber": page,
            "PageSize": RESULTS_PER_PAGE,
        }

        response = request_with_retry(
            session,
            "POST",
            SEARCH_URL,
            headers=HEADERS,
            data=body,
            timeout=REQUEST_TIMEOUT,
        )

        data = response.json()
        soup = BeautifulSoup(data.get("view", ""), "html.parser")
        cards = soup.select("a.card-vacancy")

        if not cards:
            break

        print(f"Ripley [{label}] page {page}: {len(cards)} jobs")

        for card in cards:
            job = parse_card(card, category_name)

            if job:
                jobs.append(job)

        if data.get("isLast"):
            break

        time.sleep(REQUEST_DELAY)

    return jobs


def fetch_description(session, job):
    try:
        response = request_with_retry(
            session,
            "GET",
            job["url"],
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        print(f"Ripley: could not fetch detail for job {job['job_id']}.")
        return job

    soup = BeautifulSoup(response.text, "html.parser")

    description = soup.select_one("#description")
    requirements = soup.select_one("#Requirements")
    studies = soup.select_one("#Studies")

    job["description"] = clean_text(
        description.get_text("\n") if description else None
    )
    job["requirements"] = clean_text(
        requirements.get_text("\n") if requirements else None
    )
    job["education"] = clean_text(
        studies.get_text("\n") if studies else None
    )

    return job


def scrape_ripley():
    jobs = []
    seen_ids = set()

    session = requests.Session()

    for category_id, category_name in INCLUDED_CATEGORIES.items():
        listings = fetch_listings(
            session,
            {"IdCategory1List": category_id},
            category_name,
            category_name,
        )

        for job in listings:
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            jobs.append(job)

        time.sleep(REQUEST_DELAY)

    for keyword in KEYWORD_SEARCHES:
        listings = fetch_listings(
            session,
            {"Keywords": keyword},
            f"keyword: {keyword}",
            None,
        )

        for job in listings:
            if job["job_id"] in seen_ids:
                continue

            if not job["title"]:
                continue

            if not KEYWORD_TITLE_PATTERN.search(job["title"]):
                continue

            seen_ids.add(job["job_id"])
            jobs.append(job)

        time.sleep(REQUEST_DELAY)

    print(f"Ripley: fetching details for {len(jobs)} jobs")

    for job in jobs:
        fetch_description(session, job)
        time.sleep(REQUEST_DELAY)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
