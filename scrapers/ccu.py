import re
import time
import unicodedata
from html import unescape

import requests
import pandas as pd

BASE_URL = "https://www.trabajaenccu.cl"
SEARCH_URL = f"{BASE_URL}/api/searchjob"
DETAIL_URL = f"{BASE_URL}/api/ofertas"

DOMAIN_ID = 250
TARGET_COUNTRY = "Chile"

MAX_PAGES = 50

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
DETAIL_REQUEST_DELAY = 0.2  # seconds between job detail requests


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|ul|ol|div|h[1-6])>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def format_date(date_value, dayfirst=False):
    date = pd.to_datetime(date_value, errors="coerce", dayfirst=dayfirst)
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def slugify(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower())

    return text.strip("-")


def build_job_url(job_id, title):
    slug = slugify(title)
    return f"{BASE_URL}/trabajo/{job_id}-{slug}" if slug else (
        f"{BASE_URL}/trabajo/{job_id}"
    )


def format_location(location):
    if not location:
        return None

    values = [
        location.get("nombreComuna"),
        location.get("nombreRegion"),
        location.get("nombrePais"),
    ]

    values = [value for value in values if value]
    return ", ".join(values) if values else None


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


def fetch_listings(session):
    listings = []
    page = 1

    while page <= MAX_PAGES:
        params = {
            "palabraClave": "",
            "pagina": page,
            "orden": "FECHA_PUBLICACION",
            "tipoOrden": "DESC",
            "ofertaConfidencial": "false",
            "idDominio": DOMAIN_ID,
        }

        response = request_with_retry(
            session,
            "GET",
            SEARCH_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        data = response.json()
        current_jobs = data.get("ofertas", [])
        total_pages = data.get("cantidadPaginas", page)

        if not current_jobs:
            break

        print(f"CCU page {page}: {len(current_jobs)} jobs")

        listings.extend(current_jobs)

        if page >= total_pages:
            break

        page += 1

    return listings


def fetch_detail(session, job_id):
    try:
        response = request_with_retry(
            session,
            "GET",
            f"{DETAIL_URL}/{job_id}",
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        return response.json()
    except requests.exceptions.RequestException:
        print(f"CCU: could not fetch detail for job {job_id}; using listing data.")
        return {}


def scrape_ccu():
    jobs = []

    session = requests.Session()
    listings = fetch_listings(session)

    print(f"CCU: fetching details for {len(listings)} jobs")

    for listing in listings:
        job_id = listing.get("idOferta")

        if not job_id:
            continue

        detail = fetch_detail(session, job_id)
        time.sleep(DETAIL_REQUEST_DELAY)

        location = detail.get("ubicacion") or {}
        country = location.get("nombrePais")

        if country and country != TARGET_COUNTRY:
            continue

        title = detail.get("nombreCargo") or listing.get("nombreCargo")

        posted_date = format_date(
            detail.get("fechaPublicacionFormatoIngles")
            or listing.get("fechaPublicacion")
        )

        jobs.append({
            "title": title,
            "team": detail.get("nombreArea"),
            "location": (
                format_location(location) or listing.get("ubicacion")
            ),
            "city": location.get("nombreComuna"),
            "state": location.get("nombreRegion"),
            "country": country or TARGET_COUNTRY,
            "posted_date": posted_date,

            "job_id": job_id,
            "source": "ccu",

            "company_name": (
                detail.get("nombreEmpresaFantasia")
                or listing.get("nombreEmpresa")
            ),

            "job_category": detail.get("nombreTipoCargo"),
            "schedule_type": (
                detail.get("nombreJornada") or listing.get("nombreJornada")
            ),
            "worker_type": detail.get("tiempoContrato"),
            "education": detail.get("nombreNivelAcademico"),
            "experience_level": detail.get("aniosExperiencia"),
            "application_deadline": format_date(
                detail.get("fechaExpiracionFormatoIngles")
            ),

            "url": build_job_url(job_id, title),

            "description_short": None,
            "requirements": clean_html_text(detail.get("requisitosMinimos")),
            "description": clean_html_text(
                detail.get("descripcionOferta")
                or listing.get("descripcionOferta")
            ),
        })

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
