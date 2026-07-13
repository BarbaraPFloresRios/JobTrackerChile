import re
import time
from html import unescape

import requests
import pandas as pd

HOME_URL = "https://cencosud.csod.com/ux/ats/careersite/5/home?c=cencosud"
SEARCH_URL = "https://us.api.csod.com/rec-job-search/external/jobs"

CAREER_SITE_ID = 5
TARGET_COUNTRY = "CL"
RESULTS_PER_PAGE = 100

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def format_date(date_value, dayfirst=False):
    date = pd.to_datetime(date_value, errors="coerce", dayfirst=dayfirst)
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def format_location(location):
    if not location:
        return None

    values = [
        location.get("city"),
        location.get("state"),
        location.get("country"),
    ]

    values = [value for value in values if value]
    return ", ".join(values) if values else None


def get_token(session):
    response = session.get(HOME_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    match = re.search(r'"token":"(eyJ[^"]+)"', response.text)
    return match.group(1) if match else None


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


def fetch_listings(session, api_headers):
    listings = []
    page = 1

    while True:
        body = {
            "careerSiteId": CAREER_SITE_ID,
            "careerSitePageId": CAREER_SITE_ID,
            "pageNumber": page,
            "pageSize": RESULTS_PER_PAGE,
            "cultureId": 14,
            "searchText": "",
            "cultureName": "es-MX",
            "states": [],
            "countryCodes": [],
            "cities": [],
            "placeID": "",
            "radius": None,
            "postingsWithinDays": None,
            "customFieldCheckboxKeys": [],
            "customFieldDropdowns": [],
            "customFieldRadios": [],
        }

        response = request_with_retry(
            session,
            "POST",
            SEARCH_URL,
            headers=api_headers,
            json=body,
            timeout=REQUEST_TIMEOUT,
        )

        data = response.json().get("data", {})
        current_jobs = data.get("requisitions", [])
        total_count = data.get("totalCount", 0)

        if not current_jobs:
            break

        print(f"Cencosud page {page}: {len(current_jobs)} jobs")

        listings.extend(current_jobs)

        if len(listings) >= total_count:
            break

        page += 1

    return listings


def scrape_cencosud():
    jobs = []

    session = requests.Session()
    token = get_token(session)

    if not token:
        print("Cencosud: could not obtain auth token; skipping.")
        return pd.DataFrame()

    api_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {token}",
    }

    listings = fetch_listings(session, api_headers)

    for job in listings:
        job_id = job.get("requisitionId")
        locations = job.get("locations") or [{}]
        location = locations[0]
        country = location.get("country")

        if not job_id:
            continue

        if country != TARGET_COUNTRY:
            continue

        jobs.append({
            "title": job.get("displayJobTitle"),
            "location": format_location(location),
            "city": location.get("city"),
            "state": location.get("state"),
            "country": country,
            "posted_date": format_date(
                job.get("postingEffectiveDate"), dayfirst=True
            ),

            "job_id": job_id,
            "source": "cencosud",

            "url": (
                f"https://cencosud.csod.com/ux/ats/careersite/"
                f"{CAREER_SITE_ID}/home/requisition/{job_id}?c=cencosud"
            ),

            "description_short": None,
            "description": clean_html_text(job.get("externalDescription")),
        })

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
