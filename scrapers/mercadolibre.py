import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry


BASE_URL = "https://mercadolibre.eightfold.ai"
SEARCH_URL = f"{BASE_URL}/api/pcsx/search"

# Search is filtered server-side by location=Chile (~100 jobs); before,
# we scanned only the 50 newest jobs worldwide and kept the Chilean ones.
LOCATION = "Chile"
MAX_PAGES = 40  # safety cap (400 jobs)
RESULTS_PER_PAGE = 10
SLEEP_SECONDS = 1

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def format_date(timestamp):
    date = pd.to_datetime(timestamp, unit="s", errors="coerce")
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def is_chile_job(standardized_locations):
    if not standardized_locations:
        return False

    return any(
        str(location).upper().split(",")[-1].strip() == "CL"
        for location in standardized_locations
    )



def scrape_mercadolibre():
    jobs = []

    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
    )))

    for page in range(MAX_PAGES):
        start = page * RESULTS_PER_PAGE

        try:
            response = session.get(
                SEARCH_URL,
                params={
                    "domain": "mercadolibre.com",
                    "start": start,
                    "sort_by": "date",
                    "location": LOCATION,
                },
                headers=HEADERS,
                timeout=30,
            )
            response.raise_for_status()
        except Exception as e:
            print(f"MercadoLibre page {page + 1} failed: {e}")
            break

        current_jobs = response.json().get("data", {}).get("positions", [])

        if not current_jobs:
            break

        print(f"MercadoLibre page {page + 1}: {len(current_jobs)} jobs")

        for job in current_jobs:
            position_id = job.get("id")
            locations = job.get("locations", [])
            standardized_locations = job.get("standardizedLocations", [])


            if not is_chile_job(standardized_locations):
                continue

            jobs.append({
                "title": job.get("name"),
                "team": job.get("department"),
                "location": "; ".join(locations) if locations else None,
                "posted_date": format_date(job.get("postedTs")),
                "job_id": str(position_id),
                "source": "mercadolibre",
                "workplace_type": job.get("workLocationOption"),
                "url": BASE_URL + job.get("positionUrl", ""),
                "description": None,
            })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("posted_date", ascending=False, na_position="last")

    return df