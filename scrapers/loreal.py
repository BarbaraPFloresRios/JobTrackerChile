import json
import re
import time
from html import unescape

import requests
import pandas as pd
from requests.adapters import HTTPAdapter, Retry

# careers.loreal.com runs on Radancy/TalentBrew. Its robots.txt disallows
# /search-jobs and /location/, so we read the sitemap (allowed) instead:
# every job URL is /en/job/{city-slug}/{title-slug}/3456/{id}. We keep URLs
# whose city slug is a Chilean city and confirm the country from each job
# page's JSON-LD (addressCountry), since slugs like "santiago" are shared.
BASE_URL = "https://careers.loreal.com"
SITEMAP_URL = f"{BASE_URL}/en/sitemap.xml"
TARGET_COUNTRY_CODES = {"CL", "CHL", "CHILE"}

CHILE_CITY_SLUGS = {
    "santiago", "las-condes", "vitacura", "providencia", "nunoa", "huechuraba",
    "quilicura", "pudahuel", "renca", "maipu", "lo-barnechea", "colina",
    "lampa", "san-bernardo", "puente-alto", "la-florida", "estacion-central",
    "cerrillos", "valparaiso", "vina-del-mar", "concepcion", "antofagasta",
    "temuco", "puerto-montt", "la-serena", "rancagua", "talca", "iquique",
}

REQUEST_TIMEOUT = 30
SLEEP_SECONDS = 0.5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
}

JOB_URL_PATTERN = re.compile(
    r"<loc>(https://careers\.loreal\.com/en/job/([^/<]+)/[^/<]+/\d+/(\d+))</loc>"
)


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def read_job_posting(html):
    for block in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "JobPosting":
            return data
    return None


def posting_country(posting):
    locations = posting.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    for location in locations:
        country = (location.get("address") or {}).get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        if country:
            return str(country).strip().upper()
    return None


def scrape_loreal():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
    )))

    response = session.get(SITEMAP_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    candidates = [
        (url, job_id)
        for url, city_slug, job_id in JOB_URL_PATTERN.findall(response.text)
        if city_slug in CHILE_CITY_SLUGS
    ]
    print(f"L'Oréal: {len(candidates)} candidate jobs in Chilean cities")

    jobs = []

    for url, job_id in candidates:
        try:
            page = session.get(url, timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"L'Oréal: could not fetch {url}: {e}")
            continue

        posting = read_job_posting(page.text)

        if not posting or posting_country(posting) not in TARGET_COUNTRY_CODES:
            continue

        locations = posting.get("jobLocation") or []
        if isinstance(locations, dict):
            locations = [locations]
        address = (locations[0].get("address") or {}) if locations else {}
        identifier = posting.get("identifier") or {}

        jobs.append({
            "title": posting.get("title"),
            "location": ", ".join(
                v for v in (address.get("addressLocality"), address.get("addressRegion")) if v
            ) or None,
            "city": address.get("addressLocality"),
            "country": "Chile",
            "posted_date": posting.get("datePosted"),
            "job_id": identifier.get("value") or job_id,
            "source": "loreal",
            "company_name": "L'Oréal",
            "employment_type": posting.get("employmentType"),
            "url": url,
            "description_short": None,
            "description": clean_html_text(posting.get("description")),
        })

        time.sleep(SLEEP_SECONDS)

    print(f"L'Oréal: {len(jobs)} jobs in Chile")

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("posted_date", ascending=False)
