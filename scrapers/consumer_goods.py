import json
import re
import time
from html import unescape

import requests
import pandas as pd
from requests.adapters import HTTPAdapter, Retry

# One-off scrapers for consumer-goods companies whose career sites don't fit
# the shared engines (Workday, SuccessFactors, SmartRecruiters, ...):
#   Colgate:    jobs.colgate.com/sitemap.xml is a Google-Base RSS feed with
#               every open job, including "City, Region, CC" locations.
#   PepsiCo:    pepsicojobs.com is a Jibe site with a public /api/jobs search;
#               its location filter is fuzzy, so we also check country_code.
#   Beiersdorf: beiersdorf.com/xml-sitemap lists every job page (hashed URLs,
#               no location), and each page carries JobPosting JSON-LD with
#               addressCountry, so we read all of them (~160).
TARGET_COUNTRY = "Chile"
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
    )))
    return session


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<(style|script)\b.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def to_frame(jobs):
    df = pd.DataFrame(jobs)
    if df.empty:
        return df
    return df.drop_duplicates(subset=["job_id"]).sort_values(
        "posted_date", ascending=False, na_position="last"
    )


# --- Colgate --------------------------------------------------------------

COLGATE_FEED_URL = "https://jobs.colgate.com/sitemap.xml"


def scrape_colgate():
    response = make_session().get(COLGATE_FEED_URL, timeout=60)
    response.raise_for_status()

    jobs = []

    for item in re.findall(r"<item>(.*?)</item>", response.text, re.S):
        def field(tag):
            match = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
            if not match:
                return None
            value = match.group(1).strip()
            value = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", value, flags=re.S)
            return value

        location = field("g:location") or ""
        if location.split(",")[-1].strip() != "CL":
            continue

        title = re.sub(r"\s*\([^)]*\)\s*$", "", unescape(field("title") or ""))

        jobs.append({
            "title": title or None,
            "team": field("g:job_function"),
            "location": location,
            "city": location.split(",")[0].strip() or None,
            "country": TARGET_COUNTRY,
            "posted_date": None,
            "job_id": field("g:id") or field("guid"),
            "source": "colgate",
            "company_name": "Colgate-Palmolive",
            "url": field("link"),
            "description_short": None,
            "description": clean_html_text(unescape(field("description") or "")),
        })

    print(f"Colgate: {len(jobs)} jobs in {TARGET_COUNTRY}")
    return to_frame(jobs)


# --- PepsiCo --------------------------------------------------------------

PEPSICO_API_URL = "https://www.pepsicojobs.com/api/jobs"
PEPSICO_JOB_URL = "https://www.pepsicojobs.com/main/jobs/{job_id}"
PEPSICO_PAGE_SIZE = 50
PEPSICO_MAX_PAGES = 20
PEPSICO_DELAY = 5  # robots.txt asks for crawl-delay: 5


def scrape_pepsico():
    session = make_session()
    postings = []

    for page in range(1, PEPSICO_MAX_PAGES + 1):
        response = session.get(
            PEPSICO_API_URL,
            params={"location": TARGET_COUNTRY, "limit": PEPSICO_PAGE_SIZE, "page": page},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        batch = [job.get("data", job) for job in data.get("jobs") or []]
        postings.extend(batch)

        if not batch or len(postings) >= data.get("totalCount", 0):
            break

        time.sleep(PEPSICO_DELAY)

    jobs = []

    for job in postings:
        if job.get("country_code") != "CL":
            continue

        posted = pd.to_datetime(job.get("posted_date"), errors="coerce", utc=True)
        description = "\n".join(
            part for part in (
                clean_html_text(job.get("description")),
                clean_html_text(job.get("responsibilities")),
                clean_html_text(job.get("qualifications")),
            ) if part
        )
        categories = job.get("categories") or []

        jobs.append({
            "title": job.get("title"),
            "team": categories[0].get("name") if categories else None,
            "location": job.get("full_location") or job.get("city"),
            "city": job.get("city"),
            "country": TARGET_COUNTRY,
            "posted_date": posted.strftime("%Y-%m-%d") if pd.notna(posted) else None,
            "job_id": job.get("req_id") or job.get("slug"),
            "source": "pepsico",
            "company_name": "PepsiCo",
            "employment_type": job.get("employment_type"),
            "url": PEPSICO_JOB_URL.format(job_id=job.get("slug") or job.get("req_id")),
            "description_short": None,
            "description": description or None,
        })

    print(f"PepsiCo: {len(jobs)} jobs in {TARGET_COUNTRY}")
    return to_frame(jobs)


# --- Beiersdorf -----------------------------------------------------------

BEIERSDORF_SITEMAP_URL = "https://www.beiersdorf.com/xml-sitemap"
BEIERSDORF_JOB_PATTERN = re.compile(
    r"https://www\.beiersdorf\.com/career/jobs/[0-9a-f]{32}"
)
BEIERSDORF_DELAY = 0.3


def read_job_posting(html):
    for block in re.findall(r"<script[^>]*ld\+json[^>]*>(.*?)</script>", html, re.S):
        try:
            data = json.loads(block, strict=False)
        except json.JSONDecodeError:
            continue
        for entry in data if isinstance(data, list) else [data]:
            if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                return entry
    return None


def scrape_beiersdorf():
    session = make_session()

    response = session.get(BEIERSDORF_SITEMAP_URL, timeout=60)
    response.raise_for_status()
    urls = sorted(set(BEIERSDORF_JOB_PATTERN.findall(response.text)))
    print(f"Beiersdorf: {len(urls)} jobs worldwide, checking locations")

    jobs = []

    for url in urls:
        try:
            page = session.get(url, timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Beiersdorf: could not fetch {url}: {e}")
            continue

        posting = read_job_posting(page.text)
        time.sleep(BEIERSDORF_DELAY)

        if not posting:
            continue

        addresses = [
            (location.get("address") or {})
            for location in posting.get("jobLocation") or []
            if isinstance(location, dict)
        ]
        if not any(a.get("addressCountry") == TARGET_COUNTRY for a in addresses):
            continue

        address = next(a for a in addresses if a.get("addressCountry") == TARGET_COUNTRY)
        organization = posting.get("hiringOrganization") or {}

        jobs.append({
            "title": posting.get("title"),
            "location": address.get("addressLocality"),
            "city": address.get("addressLocality"),
            "country": TARGET_COUNTRY,
            "posted_date": posting.get("datePosted"),
            "job_id": url.rsplit("/", 1)[-1],
            "source": "beiersdorf",
            "company_name": organization.get("name") or "Beiersdorf",
            "employment_type": posting.get("employmentType"),
            "url": url,
            "description_short": None,
            "description": clean_html_text(posting.get("description")),
        })

    print(f"Beiersdorf: {len(jobs)} jobs in {TARGET_COUNTRY}")
    return to_frame(jobs)
