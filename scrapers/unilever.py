import time
import urllib.parse

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Unilever's global careers site (careers.unilever.com) runs on the
# TalentBrew/Radancy platform. robots.txt disallows /search-jobs/, so
# instead of that endpoint we use its country "location" landing pages,
# which are server-rendered, sitemap-listed, and allowed to crawl:
#   /en/location/{country-slug}-jobs/{orgId}/{countryFacetId}/2
#   /en/location/{country-slug}-jobs/{orgId}/{countryFacetId}/2/{page}  (page >= 2)
# ORG_ID is this career site's company id. CHILE_COUNTRY_FACET_ID is
# Chile's GeoNames id, which the site also uses as its stable country
# facet id (same id families as the location autocomplete API) -
# it doesn't change even when Chile currently has zero postings.
BASE_URL = "https://careers.unilever.com"
ORG_ID = "34155"
CHILE_COUNTRY_FACET_ID = "3895114"
COUNTRY_FACET_TYPE = "2"
SEARCH_URL_BASE = (
    f"{BASE_URL}/en/location/chile-jobs/"
    f"{ORG_ID}/{CHILE_COUNTRY_FACET_ID}/{COUNTRY_FACET_TYPE}"
)

TARGET_COUNTRY = "Chile"

MAX_PAGES = 20  # safety cap

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}


def build_page_url(page):
    if page == 1:
        return SEARCH_URL_BASE

    return f"{SEARCH_URL_BASE}/{page}"

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
REQUEST_DELAY = 0.5  # seconds between page requests


def request_with_retry(session, url, **kwargs):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
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


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")

    results_section = soup.find("section", id="search-results")
    total_pages = int(results_section["data-total-pages"]) if (
        results_section and results_section.has_attr("data-total-pages")
    ) else 1

    jobs = []

    for item in soup.select("ul.global-job-list li"):
        link = item.find("a")

        if not link or not link.has_attr("href"):
            continue

        job_id = link.get("data-job-id")
        title_el = link.find("h2", class_="global-job-list__title")
        location_el = link.find("span", class_="job-location")

        title = title_el.get_text(strip=True) if title_el else None
        location = location_el.get_text(strip=True) if location_el else None

        if not job_id or not title:
            continue

        jobs.append({
            "title": title,
            "location": location,
            "city": location,
            "state": None,
            "country": TARGET_COUNTRY,
            "posted_date": None,

            "job_id": job_id,
            "source": "unilever",

            "company_name": "Unilever",

            "team": None,
            "schedule_type": None,

            "url": urllib.parse.urljoin(BASE_URL, link["href"]),

            "description_short": None,
            "description": None,
        })

    return jobs, total_pages


def scrape_unilever():
    session = requests.Session()

    jobs = []
    seen_ids = set()
    total_pages = 1

    for page in range(1, MAX_PAGES + 1):
        response = request_with_retry(
            session,
            build_page_url(page),
            headers=HEADERS,
        )

        page_jobs, total_pages = parse_page(response.text)

        print(f"unilever page {page}/{total_pages}: {len(page_jobs)} jobs")

        for job in page_jobs:
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            jobs.append(job)

        if page >= total_pages:
            break

        time.sleep(REQUEST_DELAY)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")

    return df
