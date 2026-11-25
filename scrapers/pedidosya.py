import re
import time
from html import unescape

import requests
import pandas as pd

# PedidosYa hires through its parent Delivery Hero, whose SmartRecruiters
# board has a public postings API. We list Chile postings and keep the ones
# tagged with the PedidosYa brand (custom field "Brands").
COMPANY_ID = "DeliveryHero"
LIST_URL = f"https://api.smartrecruiters.com/v1/companies/{COMPANY_ID}/postings"
DETAIL_URL = LIST_URL + "/{job_id}"
JOB_URL = f"https://jobs.smartrecruiters.com/{COMPANY_ID}/{{job_id}}"
COUNTRY = "cl"
BRAND = "PedidosYa"

PAGE_SIZE = 100
MAX_PAGES = 20
REQUEST_TIMEOUT = 30
SLEEP_SECONDS = 0.3

HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def format_date(value):
    date = pd.to_datetime(value, errors="coerce", utc=True)
    return date.strftime("%Y-%m-%d") if pd.notna(date) else None


def custom_field(posting, label):
    for field in posting.get("customField") or []:
        if field.get("fieldLabel") == label:
            return field.get("valueLabel")
    return None


def fetch_postings(session):
    postings = []

    for page in range(MAX_PAGES):
        response = session.get(
            LIST_URL,
            params={"country": COUNTRY, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        batch = data.get("content") or []
        postings.extend(batch)

        if len(postings) >= data.get("totalFound", 0) or not batch:
            break

    return postings


def fetch_description(session, job_id):
    try:
        response = session.get(DETAIL_URL.format(job_id=job_id), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"PedidosYa: could not fetch detail for job {job_id}: {e}")
        return None

    sections = (response.json().get("jobAd") or {}).get("sections") or {}
    parts = [
        clean_html_text((sections.get(key) or {}).get("text"))
        for key in ("jobDescription", "qualifications", "additionalInformation")
    ]
    return "\n".join(part for part in parts if part) or None


def scrape_pedidosya():
    session = requests.Session()
    session.headers.update(HEADERS)

    postings = [
        p for p in fetch_postings(session)
        if custom_field(p, "Brands") == BRAND
    ]
    print(f"PedidosYa: {len(postings)} jobs in Chile")

    jobs = []

    for posting in postings:
        job_id = posting["id"]
        location = posting.get("location") or {}

        jobs.append({
            "title": posting.get("name"),
            "team": custom_field(posting, "Job Family"),
            "location": location.get("city"),
            "city": location.get("city"),
            "country": "Chile",
            "posted_date": format_date(posting.get("releasedDate")),
            "job_id": job_id,
            "source": "pedidosya",
            "company_name": BRAND,
            "level": (posting.get("experienceLevel") or {}).get("label"),
            "employment_type": (posting.get("typeOfEmployment") or {}).get("label"),
            "url": JOB_URL.format(job_id=job_id),
            "description_short": None,
            "description": fetch_description(session, job_id),
        })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("posted_date", ascending=False)
