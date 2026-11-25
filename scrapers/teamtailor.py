import re
import xml.etree.ElementTree as ET
from html import unescape

import requests
import pandas as pd

# Shared engine for Teamtailor career sites. Every site publishes a public
# RSS feed at /jobs.rss with the full description, publish date and
# structured locations (tt: namespace), so one request covers the board.
TT_NS = {"tt": "https://teamtailor.com/locations"}
TARGET_COUNTRY = "Chile"
REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0"}


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def child_text(element, tag):
    found = element.find(tag, TT_NS)
    return found.text.strip() if found is not None and found.text else None


def scrape_teamtailor_site(host, source, company_name):
    response = requests.get(
        f"https://{host}/jobs.rss", headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    # Teamtailor's namespace URI can vary; pick it up from the document.
    match = re.search(rb'xmlns:tt="([^"]+)"', response.content)
    if match:
        TT_NS["tt"] = match.group(1).decode()

    jobs = []

    for item in root.iter("item"):
        locations = item.findall("tt:locations/tt:location", TT_NS)
        countries = {child_text(loc, "tt:country") for loc in locations}
        cities = [child_text(loc, "tt:city") for loc in locations]
        cities = [city for city in cities if city]

        # Boards with no structured location are assumed local (Chile).
        if locations and TARGET_COUNTRY not in countries:
            continue

        link = child_text(item, "link")
        job_id = re.search(r"/jobs/(\d+)", link or "")
        posted = pd.to_datetime(child_text(item, "pubDate"), errors="coerce", utc=True)

        jobs.append({
            "title": child_text(item, "title"),
            "team": child_text(item, "tt:department"),
            "location": "; ".join(dict.fromkeys(cities)) or None,
            "city": cities[0] if cities else None,
            "country": TARGET_COUNTRY,
            "posted_date": posted.strftime("%Y-%m-%d") if pd.notna(posted) else None,
            "job_id": job_id.group(1) if job_id else child_text(item, "guid"),
            "source": source,
            "company_name": company_name,
            "url": link,
            "description_short": None,
            "description": clean_html_text(child_text(item, "description")),
        })

    print(f"{company_name}: {len(jobs)} jobs in {TARGET_COUNTRY}")

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("posted_date", ascending=False)


def scrape_tenpo():
    return scrape_teamtailor_site(
        host="tenpo.teamtailor.com",
        source="tenpo",
        company_name="Tenpo",
    )
