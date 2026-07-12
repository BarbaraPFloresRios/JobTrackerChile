import re
from html import unescape

import requests
import pandas as pd


BASE_URL = "https://www.uber.com"
SEARCH_URL = f"{BASE_URL}/api/loadSearchJobsResults"
TARGET_COUNTRIES = {"CHL"}


HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "x-csrf-token": "x",
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


def format_location(location):
    if not location:
        return None

    values = [
        location.get("city"),
        location.get("region"),
        location.get("countryName"),
    ]

    values = [value for value in values if value]
    return ", ".join(values) if values else None


def format_all_locations(locations):
    if not locations:
        return None

    formatted_locations = [
        format_location(location)
        for location in locations
        if format_location(location)
    ]

    return "; ".join(formatted_locations) if formatted_locations else None


def scrape_uber():
    jobs = []

    response = requests.post(
        SEARCH_URL,
        headers=HEADERS,
        json={},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    current_jobs = response.json().get("data", {}).get("results", [])

    print(f"Uber: {len(current_jobs)} jobs")

    
    for job in current_jobs:
        job_id = job.get("id")
        location = job.get("location") or {}
        country_code = location.get("country")

        if not job_id:
            continue

        if country_code not in TARGET_COUNTRIES:
            continue

        jobs.append({
            "title": job.get("title"),
            "team": job.get("team"),
            "location": format_all_locations(job.get("allLocations")) or format_location(location),
            "posted_date": format_date(job.get("creationDate")),
            "job_id": job_id,
            "source": "uber",
            "country_code": country_code,
            "department": job.get("department"),
            "level": job.get("level"),
            "city": location.get("city"),
            "region": location.get("region"),
            "country": location.get("countryName"),
            "primary_location": format_location(location),
            "all_locations": format_all_locations(job.get("allLocations")),
            "employment_type": job.get("timeType"),
            "job_type": job.get("type"),
            "program_and_platform": job.get("programAndPlatform"),
            "unique_skills": job.get("uniqueSkills"),
            "featured": job.get("featured"),
            "is_pipeline": job.get("isPipeline"),
            "portal_id": job.get("portalID"),
            "status_id": job.get("statusID"),
            "status_name": job.get("statusName"),
            "other_levels": job.get("otherLevels"),
            "updated_date": format_date(job.get("updatedDate")),

            "url": f"{BASE_URL}/global/en/careers/list/{job_id}/",
            "description_short": None,
            "description": clean_html_text(job.get("description")),
        })

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df