import json
import re

import requests
import pandas as pd

# careers.rappi.com is a Next.js site that server-renders every open
# vacancy into the React Server Components payload (self.__next_f.push
# chunks) of /es/careers. We decode those chunks, pull the jobs array and
# keep postings located in Chile. Corporate roles live here; Rappi's
# Workday board only carries store/picker roles.
BASE_URL = "https://careers.rappi.com"
LISTING_URL = f"{BASE_URL}/es/careers"
JOB_URL = f"{BASE_URL}/es/careers/{{vacancy_id}}"
TARGET_COUNTRY = "Chile"

REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}

RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')


def extract_jobs(html):
    payload = "".join(json.loads(f'"{chunk}"') for chunk in RSC_CHUNK.findall(html))
    start = payload.find('[{"jobId"')

    if start == -1:
        raise RuntimeError("Rappi: jobs array not found in page payload")

    jobs, _ = json.JSONDecoder().raw_decode(payload[start:])
    return jobs


def job_locations(job):
    locations = job.get("locations") or []
    return [
        (loc.get("country"), city)
        for loc in locations
        for city in (loc.get("cities") or [None])
    ] or [(job.get("country"), job.get("city"))]


def as_text(value):
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v)
    return value or None


def scrape_rappi():
    response = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    all_jobs = extract_jobs(response.text)
    print(f"Rappi: {len(all_jobs)} jobs in all countries")

    jobs = []

    for job in all_jobs:
        locations = job_locations(job)
        chile_cities = [city for country, city in locations if country == TARGET_COUNTRY]

        if not chile_cities or job.get("status") != "open":
            continue

        description = "\n".join(
            part for part in (
                as_text(job.get("description")),
                as_text(job.get("mission")),
                as_text(job.get("responsibilities")),
                as_text(job.get("requirements")),
                as_text(job.get("hardSkills")),
            ) if part
        )

        jobs.append({
            "title": job.get("title"),
            "team": job.get("jobFamily"),
            "location": "; ".join(f"{city}, {country}" for country, city in locations if city),
            "city": chile_cities[0],
            "country": TARGET_COUNTRY,
            "job_id": job.get("jobId"),
            "source": "rappi",
            "company_name": "Rappi",
            "level": job.get("grade"),
            "url": JOB_URL.format(vacancy_id=job.get("vacancyId")),
            "description_short": as_text(job.get("headline")),
            "description": description or None,
        })

    print(f"Rappi: {len(jobs)} jobs in Chile")

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("title")
