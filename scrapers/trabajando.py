import re
import time
import unicodedata
from html import unescape

import requests
import pandas as pd

# Shared scraper for company portals hosted on trabajando.cl
# (SMU, Coca-Cola Andina, Embonor, Forus). Each portal is a Nuxt app
# backed by two public JSON endpoints:
#   GET /api/searchjob?idDominio=...&pagina=N   -> paginated listings
#   GET /api/ofertas/{idOferta}                 -> full job detail
# The idDominio for each portal is embedded in the page payload and
# stable per site.

SEARCH_URL = "https://{host}/api/searchjob"
DETAIL_URL = "https://{host}/api/ofertas/{job_id}"
JOB_URL = "https://{host}/trabajo-empleo/{slug}/trabajo/{job_id}"

TARGET_COUNTRY = "Chile"

MAX_PAGES = 50  # safety cap; portals paginate 15 per page

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "es-CL,es;q=0.9",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
REQUEST_DELAY = 0.3  # seconds between requests

# Internship-type postings, dropped at the source. Title-based
# exclusions also run in the pipeline; this catches internships
# whose titles don't mention "práctica" (e.g. "Memoria/Tesis").
EXCLUDED_JOB_TYPES = {"práctica", "practica"}


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>|</li>|</div>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = text.strip()

    return text or None


def slugify(text):
    if not text:
        return "oferta"

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")

    return text or "oferta"


def format_date(date_value):
    date = pd.to_datetime(date_value, errors="coerce")
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def split_location(location):
    if not location:
        return None, None

    parts = [part.strip() for part in location.split(",", 1)]

    if len(parts) == 2:
        return parts[0], parts[1]

    return parts[0], None


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


def parse_listing(item, host, source, company_fallback):
    job_id = item.get("idOferta")

    if not job_id:
        return None

    title = item.get("nombreCargo")
    location = item.get("ubicacion")
    city, state = split_location(location)

    return {
        "title": title,
        "location": location,
        "city": city,
        "state": state,
        "country": TARGET_COUNTRY,
        "posted_date": format_date(item.get("fechaPublicacion")),

        "job_id": str(job_id),
        "source": source,

        "company_name": item.get("nombreEmpresa") or company_fallback,

        "schedule_type": item.get("nombreJornada"),

        "url": JOB_URL.format(
            host=host,
            slug=slugify(title),
            job_id=job_id,
        ),

        "description_short": clean_html_text(item.get("descripcionOferta")),
        "description": None,
    }


def fetch_detail(session, host, job):
    url = DETAIL_URL.format(host=host, job_id=job["job_id"])

    try:
        response = request_with_retry(
            session,
            "GET",
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        print(f"{host}: could not fetch detail for job {job['job_id']}.")
        return job

    data = response.json()

    experience_years = data.get("aniosExperiencia")

    job["team"] = data.get("nombreArea")
    job["worker_type"] = data.get("nombreTipoCargo")
    job["education"] = data.get("nombreNivelAcademico")
    job["experience_level"] = (
        f"{experience_years} años" if experience_years else None
    )
    job["vacancies"] = data.get("cantidadVacantes")
    job["application_deadline"] = format_date(data.get("fechaExpiracion"))
    job["company_name"] = (
        data.get("nombreEmpresaFantasia") or job["company_name"]
    )
    job["requirements"] = clean_html_text(data.get("requisitosMinimos"))
    job["description"] = clean_html_text(data.get("descripcionOferta"))

    return job


def scrape_trabajando_portal(host, id_dominio, source, company_fallback):
    session = requests.Session()

    jobs = []
    seen_ids = set()

    for page in range(1, MAX_PAGES + 1):
        response = request_with_retry(
            session,
            "GET",
            SEARCH_URL.format(host=host),
            headers=HEADERS,
            params={
                "idDominio": id_dominio,
                "ofertaConfidencial": "false",
                "orden": "FECHA_PUBLICACION",
                "tipoOrden": "DESC",
                "pagina": page,
            },
            timeout=REQUEST_TIMEOUT,
        )

        data = response.json()
        items = data.get("ofertas") or []

        if not items:
            break

        print(f"{source} page {page}: {len(items)} jobs")

        for item in items:
            job = parse_listing(item, host, source, company_fallback)

            if not job or job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            jobs.append(job)

        if page >= (data.get("cantidadPaginas") or page):
            break

        time.sleep(REQUEST_DELAY)

    print(f"{source}: fetching details for {len(jobs)} jobs")

    for job in jobs:
        fetch_detail(session, host, job)
        time.sleep(REQUEST_DELAY)

    jobs = [
        job for job in jobs
        if (job.get("worker_type") or "").lower() not in EXCLUDED_JOB_TYPES
    ]

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df


def scrape_smu():
    return scrape_trabajando_portal(
        host="smu.trabajando.cl",
        id_dominio=2858,
        source="smu",
        company_fallback="SMU",
    )


def scrape_andina():
    return scrape_trabajando_portal(
        host="koandina.trabajando.cl",
        id_dominio=4178,
        source="andina",
        company_fallback="Coca-Cola Andina",
    )


def scrape_embonor():
    return scrape_trabajando_portal(
        host="embonor.trabajando.cl",
        id_dominio=4204,
        source="embonor",
        company_fallback="Coca-Cola Embonor",
    )


def scrape_forus():
    return scrape_trabajando_portal(
        host="forus.trabajando.cl",
        id_dominio=260,
        source="forus",
        company_fallback="Forus",
    )
