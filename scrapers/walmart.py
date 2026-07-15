import re
import time

import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://postulawalmartchile.cl"
LISTING_URL = f"{BASE_URL}/vacantes/external/gerencial"
LIVEWIRE_URL = f"{BASE_URL}/livewire/message/front.vacant.index"

MAX_LOAD_MORE = 30  # safety cap on pagination rounds
REQUEST_TIMEOUT = 30  # seconds
SLEEP_SECONDS = 0.5  # politeness delay between detail-page requests

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


def clean_text(text):
    if not text:
        return None

    text = text.strip()
    return text or None


def get_snapshot(session):
    response = session.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    html = response.text

    match = re.search(r'wire:initial-data="({.*?})"\s+wire:init', html)
    csrf_match = re.search(r'name="csrf-token" content="([^"]+)"', html)

    if not match or not csrf_match:
        return None, None, None

    import json
    from html import unescape

    data = json.loads(unescape(match.group(1)))

    return data["fingerprint"], data["serverMemo"], csrf_match.group(1)


def call_livewire(session, csrf_token, fingerprint, server_memo, method):
    payload = {
        "fingerprint": fingerprint,
        "serverMemo": server_memo,
        "updates": [
            {
                "type": "callMethod",
                "payload": {"id": method, "method": method, "params": []},
            }
        ],
    }

    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "X-Livewire": "true",
        "X-CSRF-TOKEN": csrf_token,
        "Accept": "application/json, text/html, */*; q=0.01",
        "Referer": LISTING_URL,
    }

    response = session.post(
        LIVEWIRE_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    result = response.json()

    updated_memo = dict(server_memo)
    updated_memo["data"] = {**server_memo["data"], **result["serverMemo"]["data"]}
    updated_memo["checksum"] = result["serverMemo"]["checksum"]
    updated_memo["htmlHash"] = result["serverMemo"].get(
        "htmlHash", server_memo.get("htmlHash")
    )

    html = result.get("effects", {}).get("html")

    return html, updated_memo


def fetch_listing_html(session):
    fingerprint, server_memo, csrf_token = get_snapshot(session)

    if not fingerprint:
        print("Walmart: could not read Livewire snapshot; skipping.")
        return []

    html_pages = []

    html, server_memo = call_livewire(
        session, csrf_token, fingerprint, server_memo, "loadData"
    )

    if not html:
        return []

    html_pages.append(html)
    seen_job_ids = set(re.findall(r"vacante/detalle/(\d+)/external", html))

    for _ in range(MAX_LOAD_MORE):
        html, server_memo = call_livewire(
            session, csrf_token, fingerprint, server_memo, "loadMore"
        )

        if not html:
            break

        job_ids = set(re.findall(r"vacante/detalle/(\d+)/external", html))

        if job_ids <= seen_job_ids:
            break

        seen_job_ids |= job_ids
        html_pages.append(html)

    return html_pages


def parse_listing_cards(html_pages):
    cards_by_id = {}

    for html in html_pages:
        soup = BeautifulSoup(html, "html.parser")

        for card in soup.select("div.card.card-fill"):
            link = card.find("a", href=True)

            if not link:
                continue

            match = re.search(r"/vacante/detalle/(\d+)/external", link["href"])

            if not match:
                continue

            job_id = match.group(1)

            body = card.find("div", class_="card-body")
            fields = list(body.stripped_strings) if body else []

            title = fields[0] if len(fields) > 0 else None
            team = fields[1] if len(fields) > 1 else None
            location = fields[2] if len(fields) > 2 else None
            schedule_type = fields[3] if len(fields) > 3 else None

            cards_by_id[job_id] = {
                "job_id": job_id,
                "title": clean_text(title),
                "team": clean_text(team),
                "location": clean_text(location),
                "schedule_type": clean_text(schedule_type),
                "url": f"{BASE_URL}/vacante/detalle/{job_id}/external",
            }

    return list(cards_by_id.values())


def get_accordion_text(soup, heading_text):
    heading = soup.find(
        lambda tag: tag.name == "div"
        and heading_text in tag.get_text(strip=True)
        and "col" in (tag.get("class") or [])
    )

    if not heading:
        return None

    card_header = heading.find_parent("div", class_="card-header")

    if not card_header:
        return None

    collapse_div = card_header.find_next_sibling("div")

    if not collapse_div:
        return None

    paragraph = collapse_div.find("p")

    return clean_text(paragraph.get_text(" ", strip=True)) if paragraph else None


def fetch_job_detail(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Walmart: failed to fetch {url}: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")

    description = None
    heading = soup.find(
        lambda tag: tag.name in ("h4", "h5")
        and "Funciones del cargo" in tag.get_text(strip=True)
    )

    if heading:
        container = heading.find_parent("div", class_="col-12")
        paragraph = container.find("p") if container else None
        description = clean_text(paragraph.get_text(" ", strip=True)) if paragraph else None

    requirements = get_accordion_text(soup, "Requerimientos del cargo")
    selection_process = get_accordion_text(soup, "Descripción del proceso de selección")

    return {
        "description": description,
        "requirements": requirements,
        "selection_process": selection_process,
    }


def scrape_walmart():
    session = requests.Session()

    html_pages = fetch_listing_html(session)

    if not html_pages:
        return pd.DataFrame()

    listings = parse_listing_cards(html_pages)

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
