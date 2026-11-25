import re
import time
from html import unescape

import requests
import pandas as pd

# Shared engine for Workday candidate sites (myworkdayjobs.com). Each site
# exposes public JSON endpoints:
#   POST /wday/cxs/{tenant}/{site}/jobs            -> paginated listings + facets
#   GET  /wday/cxs/{tenant}/{site}{externalPath}   -> full job detail
# We look up the "Chile" country facet by name (ids are per tenant) and
# list only those postings.
REQUEST_TIMEOUT = 30
PAGE_SIZE = 20  # Workday caps page size at 20
MAX_PAGES = 50
SLEEP_SECONDS = 0.3
TARGET_COUNTRY = "Chile"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def clean_html_text(text):
    if not text:
        return None

    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip() or None


def find_country_facet(facets, country):
    for facet in facets or []:
        stack = [(facet.get("facetParameter"), facet.get("values") or [])]
        while stack:
            parameter, values = stack.pop()
            for value in values:
                if "values" in value:
                    stack.append((value.get("facetParameter", parameter), value["values"]))
                elif value.get("descriptor") == country and "ountry" in (parameter or ""):
                    return parameter, value["id"]
    return None, None


def scrape_workday_site(host, tenant, site, source, company_name):
    session = requests.Session()
    session.headers.update(HEADERS)

    api = f"https://{host}/wday/cxs/{tenant}/{site}"

    def search(offset, applied_facets):
        response = session.post(
            f"{api}/jobs",
            json={
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": "",
                "appliedFacets": applied_facets,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    first = search(0, {})
    parameter, country_id = find_country_facet(first.get("facets"), TARGET_COUNTRY)

    if not parameter:
        print(f"{company_name}: no {TARGET_COUNTRY} facet on Workday site; 0 jobs")
        return pd.DataFrame()

    applied = {parameter: [country_id]}
    postings = []

    for page in range(MAX_PAGES):
        data = search(page * PAGE_SIZE, applied)
        batch = data.get("jobPostings") or []
        postings.extend(batch)

        if not batch or len(postings) >= data.get("total", 0):
            break

    print(f"{company_name}: {len(postings)} jobs in {TARGET_COUNTRY}, fetching details")

    jobs = []

    for posting in postings:
        path = posting.get("externalPath")
        if not path:
            continue

        try:
            response = session.get(f"{api}{path}", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            info = response.json().get("jobPostingInfo") or {}
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"{company_name}: could not fetch detail for {path}: {e}")
            info = {}

        location = info.get("location") or posting.get("locationsText")

        jobs.append({
            "title": info.get("title") or posting.get("title"),
            "location": location,
            "city": location,
            "country": TARGET_COUNTRY,
            "posted_date": info.get("startDate"),
            "job_id": info.get("jobReqId") or path.rsplit("_", 1)[-1],
            "source": source,
            "company_name": company_name,
            "employment_type": info.get("timeType"),
            "url": info.get("externalUrl") or f"https://{host}/{site}{path}",
            "description_short": None,
            "description": clean_html_text(info.get("jobDescription")),
        })

        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(jobs)

    if df.empty:
        return df

    return df.drop_duplicates(subset=["job_id"]).sort_values("posted_date", ascending=False)


def scrape_pg():
    return scrape_workday_site(
        host="pg.wd5.myworkdayjobs.com",
        tenant="pg",
        site="1000",
        source="pg",
        company_name="P&G",
    )
