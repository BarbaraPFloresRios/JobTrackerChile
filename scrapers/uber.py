import re
import time
from html import unescape

import requests
import pandas as pd
from requests.adapters import HTTPAdapter, Retry

# Uber moved its careers site to jobs.uber.com (bot-protected, 403 for plain
# requests), backed by Oracle Recruiting Cloud. The Oracle candidate REST API
# is public, so we read the full requisition list from there, keep jobs whose
# primary or secondary location is in Chile, and fetch each one's description.
# Requisition ids kept the same numbering as the old uber.com/careers site.
ORACLE_HOST = "https://iaziqy.fa.ocs.oraclecloud.com"
SITE_NUMBER = "CX_1"
LIST_URL = f"{ORACLE_HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_URL = f"{ORACLE_HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
JOB_URL = "https://jobs.uber.com/en/jobs/{job_id}/"
TARGET_COUNTRIES = {"CL"}

PAGE_SIZE = 200
MAX_PAGES = 20  # safety cap (~4,000 jobs)
REQUEST_TIMEOUT = 60  # seconds
SLEEP_SECONDS = 0.3  # politeness delay between detail requests

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def make_session():
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session


def clean_html_text(text):
    if not text:
        return None

    # Oracle wraps some descriptions in a full HTML document with a <title>.
    text = re.sub(r"<(head|title|style|script)\b.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)

    return text.strip() or None


def format_date(date_value):
    date = pd.to_datetime(date_value, errors="coerce", utc=True)
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def job_countries(job):
    countries = {job.get("PrimaryLocationCountry")}
    for location in job.get("secondaryLocations") or []:
        countries.add(location.get("CountryCode"))
    return countries


def format_all_locations(job):
    locations = [job.get("PrimaryLocation")]
    locations += [loc.get("Name") for loc in job.get("secondaryLocations") or []]
    locations = [loc for loc in dict.fromkeys(locations) if loc]
    return "; ".join(locations) if locations else None


def fetch_all_requisitions(session):
    requisitions = []

    for page in range(MAX_PAGES):
        params = {
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": (
                f"findReqs;siteNumber={SITE_NUMBER},limit={PAGE_SIZE},"
                f"offset={page * PAGE_SIZE},sortBy=POSTING_DATES_DESC"
            ),
        }

        response = session.get(LIST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        items = response.json().get("items") or [{}]
        batch = items[0].get("requisitionList") or []

        if not batch:
            break

        requisitions.extend(batch)

    return requisitions


def fetch_job_detail(session, job_id):
    params = {
        "expand": "all",
        "onlyData": "true",
        "finder": f'ById;Id="{job_id}",siteNumber={SITE_NUMBER}',
    }

    try:
        response = session.get(DETAIL_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        items = response.json().get("items") or []
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Uber: could not fetch detail for job {job_id}: {e}")
        return {}

    return items[0] if items else {}


def scrape_uber():
    session = make_session()

    requisitions = fetch_all_requisitions(session)
    print(f"Uber: {len(requisitions)} jobs worldwide")

    chile_jobs = [
        job for job in requisitions
        if job.get("Id") and job_countries(job) & TARGET_COUNTRIES
    ]
    print(f"Uber: {len(chile_jobs)} jobs in Chile, fetching details")

    jobs = []

    for job in chile_jobs:
        job_id = job["Id"]
        detail = fetch_job_detail(session, job_id)

        jobs.append({
            "title": job.get("Title"),
            "team": detail.get("Category"),
            "location": format_all_locations(job),
            "posted_date": format_date(job.get("PostedDate")),
            "job_id": job_id,
            "source": "uber",
            "country_code": job.get("PrimaryLocationCountry"),
            "level": detail.get("JobShift"),
            "primary_location": job.get("PrimaryLocation"),
            "all_locations": format_all_locations(job),
            "employment_type": detail.get("JobSchedule"),
            "job_type": detail.get("RequisitionType"),

            "url": JOB_URL.format(job_id=job_id),
            "description_short": clean_html_text(job.get("ShortDescriptionStr")),
            "description": clean_html_text(detail.get("ExternalDescriptionStr")),
        })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
