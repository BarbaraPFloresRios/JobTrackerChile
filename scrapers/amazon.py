import re
from html import unescape

import requests
import pandas as pd

BASE_URL = "https://www.amazon.jobs"
SEARCH_URL = "https://www.amazon.jobs/en/search.json"

MAX_PAGES = 5
RESULTS_PER_PAGE = 10

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Mozilla/5.0",
}


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"\n+", "\n", text)

    return text.strip()


def extract_amazon_job_id(job_path):
    match = re.search(r"/jobs/(\d+)", job_path)
    return match.group(1) if match else None


def format_date(date_value):
    date = pd.to_datetime(date_value, errors="coerce")
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def scrape_amazon():
    jobs = []

    for page in range(MAX_PAGES):
        offset = page * RESULTS_PER_PAGE

        params = {
            "country": "CHL",
            "sort": "recent",
            "offset": offset,
            "result_limit": RESULTS_PER_PAGE,
        }

        response = requests.get(
            SEARCH_URL,
            params=params,
            headers=HEADERS,
        )
        response.raise_for_status()

        data = response.json()
        current_jobs = data.get("jobs", [])

        if not current_jobs:
            break

        print(f"Amazon page {page + 1}: {len(current_jobs)} jobs")

        for job in current_jobs:
            job_path = job.get("job_path")

            if not job_path:
                continue

            job_id = extract_amazon_job_id(job_path)

            jobs.append({

                "title": job.get("title"),
                "team": job.get("primary_search_label"),
                "location": job.get("location"),
                "city": job.get("city"),
                "state": job.get("state"),
                "posted_date": format_date(job.get("posted_date")),

                "job_id": job_id,
                "source": "amazon",

                "job_category": job.get("job_category"),
                "job_family": job.get("job_family"),
                "schedule_type": job.get("job_schedule_type"),
                "updated_time": job.get("updated_time"),

                "url": BASE_URL + job_path,

                "description_short": clean_html_text(job.get("description_short")),
                "basic_qualifications": clean_html_text(job.get("basic_qualifications")),
                "preferred_qualifications": clean_html_text(job.get("preferred_qualifications")),
                "description": clean_html_text(job.get("description")),

            })

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(
        subset=["job_id"],
        keep="first",
    )

    df = df.sort_values(
        "posted_date",
        ascending=False,
    )

    return df