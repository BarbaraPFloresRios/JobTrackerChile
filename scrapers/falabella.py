import re
from html import unescape

import requests
import pandas as pd

BASE_URL = "https://muevete.falabella.com"
SEARCH_URL = (
    "https://ftc-hr-tama-atrc.falabella.tech"
    "/bff-sgdt-job-offer/api/ofertalaboral/filter"
)

TARGET_COUNTRY = "Chile"

MAX_PAGES = 30
RESULTS_PER_PAGE = 100

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}

REQUEST_TIMEOUT = 30  # seconds


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def format_date(date_value):
    date = pd.to_datetime(date_value, errors="coerce")
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def format_location(job):
    values = [
        job.get("city"),
        job.get("state"),
        job.get("country"),
    ]

    values = [value for value in values if value]
    return ", ".join(values) if values else None


def scrape_falabella():
    jobs = []

    for page in range(1, MAX_PAGES + 1):
        body = {
            "country": [TARGET_COUNTRY],
            "area": [],
            "company": [],
            "jobtype": [],
            "page": page,
            "perPage": RESULTS_PER_PAGE,
            "type": "external",
        }

        response = requests.post(
            SEARCH_URL,
            headers=HEADERS,
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json().get("data", {})
        current_jobs = data.get("list", [])
        total_pages = data.get("totalPages", page)

        if not current_jobs:
            break

        print(f"Falabella page {page}: {len(current_jobs)} jobs")

        for job in current_jobs:
            job_id = job.get("offer_id")
            country = job.get("country")

            if not job_id:
                continue

            if country != TARGET_COUNTRY:
                continue

            jobs.append({
                "title": job.get("title"),
                "team": job.get("area"),
                "location": format_location(job),
                "city": job.get("city"),
                "state": job.get("state"),
                "country": job.get("country"),
                "posted_date": format_date(job.get("date")),

                "job_id": job_id,
                "source": "falabella",

                "company_name": job.get("company"),
                "company_code": job.get("company_code"),
                "requisition_company": job.get("requisition_company"),
                "requisition_company_code": job.get("requisition_company_code"),
                "requisition_id": job.get("referencenumber"),

                "job_category": job.get("area"),
                "job_function": job.get("job_function"),
                "job_family": job.get("job_family"),

                "schedule_type": job.get("jobtype"),
                "worker_type": job.get("contracttype"),
                "job_location_type": job.get("job_location_type"),
                "search_type": job.get("search_type"),

                "education": job.get("education"),
                "tags": job.get("tags") or None,
                "handicap_allowed": job.get("handicap_allowed"),

                "url": job.get("url"),

                "description_short": None,
                "requirements": clean_html_text(job.get("requirements")),
                "benefits": clean_html_text(job.get("benefits")),
                "process": clean_html_text(job.get("process")),
                "description": clean_html_text(job.get("description")),
            })

        if page >= total_pages:
            break

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df
