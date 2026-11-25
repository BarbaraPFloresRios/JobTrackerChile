import json
import re
import time
from html import unescape

import requests
import pandas as pd
from bs4 import BeautifulSoup

# postulawalmartchile.cl was rebuilt in Nov 2026 on Livewire v3. The catalog
# lives at /vacantes and is a Livewire component ("vacantes.catalogo"): we set
# its `tipo` filter to "corporativo" (the old "gerencial" listing) and keep
# calling `cargarMas` until no new cards appear. Detail pages are
# /vacantes/{id}; job ids kept the same numbering as the old site.
BASE_URL = "https://postulawalmartchile.cl"
LISTING_URL = f"{BASE_URL}/vacantes"
CATALOG_COMPONENT = "vacantes.catalogo"
JOB_TYPE = "corporativo"

MAX_LOAD_MORE = 40  # safety cap on pagination rounds (9 jobs per round)
REQUEST_TIMEOUT = 30  # seconds
SLEEP_SECONDS = 0.5  # politeness delay between detail-page requests

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


def clean_text(text):
    if not text:
        return None

    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def get_catalog_snapshot(session):
    response = session.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    html = response.text

    csrf_match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    update_match = re.search(r'data-update-uri="([^"]+)"', html)

    snapshot = None
    for raw in re.findall(r'wire:snapshot="([^"]+)"', html):
        candidate = unescape(raw)
        if json.loads(candidate).get("memo", {}).get("name") == CATALOG_COMPONENT:
            snapshot = candidate
            break

    if not (csrf_match and update_match and snapshot):
        return None, None, None

    return snapshot, csrf_match.group(1), update_match.group(1)


def call_livewire(session, update_url, csrf_token, snapshot, calls=(), updates=None):
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": snapshot,
                "updates": updates or {},
                "calls": [
                    {"path": "", "method": method, "params": params}
                    for method, params in calls
                ],
            }
        ],
    }

    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Livewire": "",
        "Referer": LISTING_URL,
    }

    response = session.post(
        update_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    component = response.json()["components"][0]

    return component["snapshot"], component.get("effects", {}).get("html", "")


def fetch_listing_html(session):
    snapshot, csrf_token, update_url = get_catalog_snapshot(session)

    if not snapshot:
        raise RuntimeError("Walmart: could not read Livewire catalog snapshot")

    snapshot, html = call_livewire(
        session, update_url, csrf_token, snapshot, updates={"tipo": JOB_TYPE}
    )

    # Each cargarMas response re-renders the whole list (all cards so far),
    # so the last HTML holds every job.
    seen = len(set(re.findall(r'data-id="(\d+)"', html)))

    for _ in range(MAX_LOAD_MORE):
        snapshot, next_html = call_livewire(
            session, update_url, csrf_token, snapshot, calls=[("cargarMas", [])]
        )

        count = len(set(re.findall(r'data-id="(\d+)"', next_html)))

        if not next_html or count <= seen:
            break

        html, seen = next_html, count

    return html


def parse_listing_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    cards_by_id = {}

    for card in soup.select("article.job[data-id]"):
        job_id = card["data-id"]

        title = card.find("h3", class_="job-title")
        area = card.find("span", class_="job-area")
        meta = [
            clean_text(li.get_text(" ", strip=True).split(" ", 1)[-1])
            for li in card.select("ul.job-meta li")
        ]
        # meta items are "<icon name> <value>"; drop the icon word.
        location = meta[0] if len(meta) > 0 else None
        schedule_type = meta[1] if len(meta) > 1 else None

        area_text = None
        if area:
            icon = area.find("span", class_="ms")
            if icon:
                icon.extract()
            area_text = clean_text(area.get_text(" ", strip=True))

        cards_by_id[job_id] = {
            "job_id": job_id,
            "title": clean_text(title.get_text(" ", strip=True)) if title else None,
            "team": area_text,
            "location": location,
            "schedule_type": schedule_type,
            "url": f"{BASE_URL}/vacantes/{job_id}",
        }

    return list(cards_by_id.values())


def get_section_text(soup, heading_text):
    heading = soup.find(
        lambda tag: tag.name == "h2" and heading_text in tag.get_text(strip=True)
    )

    if not heading:
        return None

    parts = []
    for sibling in heading.find_all_next():
        if sibling.name == "h2":
            break
        if sibling.name in ("p", "li"):
            parts.append(sibling.get_text(" ", strip=True))

    return clean_text("\n".join(parts))


def get_posted_date(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue

        if data.get("@type") == "JobPosting":
            date = pd.to_datetime(data.get("datePosted"), errors="coerce", utc=True)
            return date.strftime("%Y-%m-%d") if pd.notna(date) else None

    return None


def fetch_job_detail(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Walmart: failed to fetch {url}: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")

    return {
        "description": get_section_text(soup, "Funciones del cargo"),
        "requirements": get_section_text(soup, "Requerimientos del cargo"),
        "selection_process": get_section_text(soup, "Proceso de selección"),
        "posted_date": get_posted_date(soup),
    }


def scrape_walmart():
    session = requests.Session()

    html = fetch_listing_html(session)
    listings = parse_listing_cards(html)

    if not listings:
        return pd.DataFrame()

    print(f"Walmart: found {len(listings)} jobs, fetching details")

    jobs = []

    for listing in listings:
        detail = fetch_job_detail(session, listing["url"])

        jobs.append({
            "title": listing["title"],
            "team": listing["team"],
            "location": listing["location"],
            "city": listing["location"],
            "country": "Chile",

            "job_id": listing["job_id"],
            "source": "walmart",
            "company_name": "Walmart Chile",

            "job_category": listing["team"],
            "schedule_type": listing["schedule_type"],
            "posted_date": detail.get("posted_date"),

            "url": listing["url"],

            "description_short": None,
            "description": detail.get("description"),
            "requirements": detail.get("requirements"),
            "selection_process": detail.get("selection_process"),
        })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["job_id"], keep="first")
    df = df.sort_values("title")

    return df
