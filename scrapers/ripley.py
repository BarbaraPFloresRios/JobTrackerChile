import re
import json
import time

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Ripley's official corporate career site (Cornerstone OnDemand).
# The SPA embeds a short-lived JWT in the page HTML (csod.context),
# which authorizes the career-site search and requisition APIs.
CAREER_SITE_URL = "https://ripley.csod.com/ux/ats/careersite/4/home?c=ripley"
SEARCH_URL = "https://ripley.csod.com/services/x/career-site/v1/search"
DETAIL_URL = (
    "https://ripley.csod.com/services/x/job-requisition/v2/requisitions/{job_id}"
)
JOB_URL = (
    "https://ripley.csod.com/ux/ats/careersite/4/home/requisition/{job_id}?c=ripley"
)

CAREER_SITE_ID = 4
TARGET_COUNTRY = "Chile"
TARGET_COUNTRY_CODE = "cl"

RESULTS_PER_PAGE = 25
MAX_PAGES = 50  # safety cap

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
REQUEST_DELAY = 0.3  # seconds between requests


def clean_text(text):
    if not text:
        return None

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = text.strip()

    return text or None


def html_to_text(html):
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    return clean_text(soup.get_text("\n"))


def parse_posted_date(text):
    if not text:
        return None

    date = pd.to_datetime(text, format="%d/%m/%Y", errors="coerce")

    if pd.isna(date):
        return None

    return date.strftime("%Y-%m-%d")


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


def fetch_context(session):
    response = request_with_retry(
        session,
        "GET",
        CAREER_SITE_URL,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    match = re.search(r"csod\.context=(\{.*?\});", response.text, re.DOTALL)

    if not match:
        raise RuntimeError("Ripley: could not find csod.context token in page.")

    return json.loads(match.group(1))


def fetch_search_page(session, context, auth_headers, page):
    body = {
        "careerSiteId": CAREER_SITE_ID,
        "careerSitePageId": CAREER_SITE_ID,
        "pageNumber": page,
        "pageSize": RESULTS_PER_PAGE,
        "cultureId": context["cultureID"],
        "cultureName": context["cultureName"],
        "searchText": "",
        "states": [],
        "countryCodes": [TARGET_COUNTRY_CODE],
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
        headers={**auth_headers, "Content-Type": "application/json"},
        json=body,
        timeout=REQUEST_TIMEOUT,
    )

    data = response.json()

    return data.get("data", data)


def parse_search_item(item):
    job_id = item.get("requisitionId")

    if not job_id:
        return None

    locations = item.get("locations") or [{}]
    location = locations[0]

    return {
        "title": clean_text(item.get("displayJobTitle")),
        "city": location.get("city"),
        "state": location.get("state"),
        "country": TARGET_COUNTRY,
        "posted_date": parse_posted_date(item.get("postingEffectiveDate")),

        "job_id": str(job_id),
        "source": "ripley",

        "company_name": "Ripley",

        "url": JOB_URL.format(job_id=job_id),

        "description_short": None,
        "description": None,
    }


def fetch_detail(session, context, auth_headers, job):
    url = DETAIL_URL.format(job_id=job["job_id"])

    try:
        response = request_with_retry(
            session,
            "GET",
            url,
            headers=auth_headers,
            params={"cultureId": context["cultureID"]},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        print(f"Ripley: could not fetch detail for job {job['job_id']}.")
        return job

    data = response.json()
    data = data.get("data", data)

    culture_id = str(context["cultureID"])
    descriptions = data.get("externalDescriptions") or {}
    qualifications = data.get("minQualifications") or {}

    def nested_title(field):
        value = data.get(field) or {}
        return clean_text(value.get("title"))

    job["requisition_id"] = data.get("ref")
    job["team"] = nested_title("division")
    job["location"] = nested_title("location")
    job["job_profile"] = nested_title("position")
    job["management_level"] = nested_title("grade")
    job["description"] = html_to_text(descriptions.get(culture_id))
    job["requirements"] = html_to_text(qualifications.get(culture_id))

    return job


def scrape_ripley():
    session = requests.Session()

    context = fetch_context(session)
    auth_headers = {
        **HEADERS,
        "Authorization": f"Bearer {context['token']}",
    }

    jobs = []
    seen_ids = set()

    for page in range(1, MAX_PAGES + 1):
        data = fetch_search_page(session, context, auth_headers, page)
        items = data.get("requisitions") or []

        if not items:
            break

        print(f"Ripley page {page}: {len(items)} jobs")

        for item in items:
            job = parse_search_item(item)

            if not job or job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            jobs.append(job)

        total = data.get("totalCount") or 0

        if page * RESULTS_PER_PAGE >= total:
            break

        time.sleep(REQUEST_DELAY)

    print(f"Ripley: fetching details for {len(jobs)} jobs")

    for job in jobs:
        fetch_detail(session, context, auth_headers, job)
        time.sleep(REQUEST_DELAY)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
