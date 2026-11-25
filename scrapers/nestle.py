import re
import time
import urllib.parse

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Nestlé's careers site (jobdetails.nestle.com) is a SuccessFactors Career
# Site Builder instance. The /search/ page is server-rendered and allowed by
# robots.txt; it pages 25 rows at a time via ?startrow=. Rows carry the
# location as "City, CL, postcode", so we keep only ", CL" rows. Detail
# pages expose the description and posting date via itemprop attributes.
BASE_URL = "https://jobdetails.nestle.com"
SEARCH_URL = f"{BASE_URL}/search/"
LOCATION_QUERY = "Chile"
COUNTRY_CODE = "CL"

PAGE_SIZE = 25
MAX_PAGES = 20
REQUEST_TIMEOUT = 30
SLEEP_SECONDS = 0.5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}


def clean_text(text):
    if not text:
        return None
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def is_chile(location):
    parts = [part.strip() for part in (location or "").split(",")]
    return COUNTRY_CODE in parts


def fetch_listing(session):
    rows = []

    for page in range(MAX_PAGES):
        response = session.get(
            SEARCH_URL,
            params={"q": "", "locationsearch": LOCATION_QUERY, "startrow": page * PAGE_SIZE},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        page_rows = soup.select("tr.data-row")

        for row in page_rows:
            link = row.select_one("a.jobTitle-link")
            location = row.select_one(".jobLocation")
            if not link:
                continue
            rows.append({
                "title": link.get_text(strip=True),
                "location": location.get_text(" ", strip=True) if location else None,
                "url": urllib.parse.urljoin(BASE_URL, link["href"]),
            })

        if len(page_rows) < PAGE_SIZE:
            break

        time.sleep(SLEEP_SECONDS)

    return rows


def fetch_detail(session, url):
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Nestlé: could not fetch {url}: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    description = soup.select_one('[itemprop="description"]')
    date_posted = soup.select_one('[itemprop="datePosted"]')

    posted = None
    if date_posted and date_posted.get("content"):
        date = pd.to_datetime(date_posted["content"], errors="coerce", utc=True)
        posted = date.strftime("%Y-%m-%d") if pd.notna(date) else None

    return {
        "description": clean_text(description.get_text("\n", strip=True)) if description else None,
        "posted_date": posted,
    }


def scrape_nestle():
    session = requests.Session()
    session.headers.update(HEADERS)

    listings = [row for row in fetch_listing(session) if is_chile(row["location"])]
    print(f"Nestlé: {len(listings)} jobs in Chile, fetching details")

    jobs = []

    for listing in listings:
        job_id = listing["url"].rstrip("/").rsplit("/", 1)[-1]
        detail = fetch_detail(session, listing["url"])
        city = (listing["location"] or "").split(",")[0].strip() or None

        jobs.append({
            "title": listing["title"],
            "location": city,
            "city": city,
            "country": "Chile",
            "posted_date": detail.get("posted_date"),
            "job_id": job_id,
            "source": "nestle",
            "company_name": "Nestlé",
            "url": listing["url"],
            "description_short": None,
            "description": detail.get("description"),
        })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("posted_date", ascending=False)
