import os
import pandas as pd

from src.scoring import add_semantic_scores
from src.recent_jobs import build_recent_jobs
from src.generate_readme import generate_readme

from scrapers.mercadolibre import scrape_mercadolibre
from scrapers.uber import scrape_uber
from scrapers.amazon import scrape_amazon
from scrapers.falabella import scrape_falabella
from scrapers.cencosud import scrape_cencosud
from scrapers.walmart import scrape_walmart
from scrapers.ccu import scrape_ccu
from scrapers.ripley import scrape_ripley
from scrapers.unilever import scrape_unilever
from scrapers.smartrecruiters import scrape_pedidosya, scrape_kenvue
from scrapers.rappi import scrape_rappi
from scrapers.workday import (
    scrape_pg,
    scrape_santander,
    scrape_mondelez,
    scrape_kimberlyclark,
)
from scrapers.consumer_goods import scrape_colgate, scrape_pepsico, scrape_beiersdorf
from scrapers.teamtailor import scrape_tenpo
from scrapers.loreal import scrape_loreal
from scrapers.successfactors import scrape_nestle, scrape_scotiabank
from scrapers.trabajando import (
    scrape_smu,
    scrape_andina,
    scrape_embonor,
    scrape_forus,
    scrape_rosen,
    scrape_ahumada,
    scrape_carozzi,
    scrape_salcobrand,
    scrape_pf,
    scrape_tricot,
    scrape_abc,
    scrape_casaideas,
    scrape_soprole,
    scrape_watts,
    scrape_entel,
    scrape_bci,
    scrape_bancochile,
)

RAW_DATA_DIR = "data/raw"

MERCADOLIBRE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/mercadolibre_jobs.csv"
)

UBER_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/uber_jobs.csv"
)

AMAZON_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/amazon_jobs.csv"
)

FALABELLA_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/falabella_jobs.csv"
)

CENCOSUD_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/cencosud_jobs.csv"
)

WALMART_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/walmart_jobs.csv"
)

CCU_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/ccu_jobs.csv"
)

RIPLEY_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/ripley_jobs.csv"
)

UNILEVER_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/unilever_jobs.csv"
)

ENTEL_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/entel_jobs.csv"
)

PEDIDOSYA_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/pedidosya_jobs.csv"
)

RAPPI_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/rappi_jobs.csv"
)

PG_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/pg_jobs.csv"
)

LOREAL_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/loreal_jobs.csv"
)

NESTLE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/nestle_jobs.csv"
)

BCI_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/bci_jobs.csv"
)

BANCOCHILE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/bancochile_jobs.csv"
)

SANTANDER_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/santander_jobs.csv"
)

SCOTIABANK_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/scotiabank_jobs.csv"
)

TENPO_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/tenpo_jobs.csv"
)

PEPSICO_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/pepsico_jobs.csv"
)

MONDELEZ_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/mondelez_jobs.csv"
)

KIMBERLYCLARK_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/kimberlyclark_jobs.csv"
)

COLGATE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/colgate_jobs.csv"
)

KENVUE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/kenvue_jobs.csv"
)

BEIERSDORF_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/beiersdorf_jobs.csv"
)

SMU_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/smu_jobs.csv"
)

ANDINA_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/andina_jobs.csv"
)

EMBONOR_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/embonor_jobs.csv"
)

FORUS_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/forus_jobs.csv"
)

ROSEN_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/rosen_jobs.csv"
)

AHUMADA_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/ahumada_jobs.csv"
)

CAROZZI_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/carozzi_jobs.csv"
)

SALCOBRAND_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/salcobrand_jobs.csv"
)

PF_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/pf_jobs.csv"
)

TRICOT_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/tricot_jobs.csv"
)

ABC_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/abc_jobs.csv"
)

CASAIDEAS_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/casaideas_jobs.csv"
)

SOPROLE_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/soprole_jobs.csv"
)

WATTS_OUTPUT_PATH = (
    f"{RAW_DATA_DIR}/watts_jobs.csv"
)

# Titles to exclude across all companies: internships and
# operational store roles (cajero/a, vendedor/a).
EXCLUDED_TITLE_PATTERN = r"pr[aá]ctic|cajer|vendedor"


def drop_excluded_titles(jobs):
    if jobs.empty or "title" not in jobs.columns:
        return jobs

    excluded = jobs["title"].astype(str).str.contains(
        EXCLUDED_TITLE_PATTERN,
        case=False,
        regex=True,
        na=False,
    )

    if excluded.any():
        print(f"Excluding {excluded.sum()} jobs with internship titles")

    return jobs[~excluded]


def normalize_key(series):
    return (
        series
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )


def print_section(title):
    width = 80
    print(f"\n{'═' * width}")
    print(f"SCRAPING {title.upper()}")
    print(f"{'═' * width}")


def print_phase(title):
    width = 80
    print(f"\n{'#' * width}")
    print(f"  {title.upper()}")
    print(f"{'#' * width}")

def save_jobs(current_jobs, output_path, company=""):

    width = 80
    print(f"\n{'═' * width}")
    print(f"RESULTS {company.upper()}")
    print(f"{'═' * width}")

    if current_jobs.empty:
        print(f"{company}: no jobs found; skipping.")
        return pd.DataFrame()

    dedupe_key = "job_id" if "job_id" in current_jobs.columns else "url"

    if dedupe_key not in current_jobs.columns:
        print(f"{company}: no valid jobs found; skipping.")
        return pd.DataFrame()

    today = pd.Timestamp.today().strftime("%Y-%m-%d")

    current_jobs = drop_excluded_titles(current_jobs)

    if current_jobs.empty:
        print(f"{company}: no jobs left after title exclusions; skipping.")
        return pd.DataFrame()

    current_jobs = current_jobs.copy()
    current_jobs[dedupe_key] = normalize_key(current_jobs[dedupe_key])
    current_jobs["last_seen_date"] = today


    if os.path.exists(output_path):
        old_jobs = pd.read_csv(output_path)
        old_jobs = drop_excluded_titles(old_jobs)

        if "position_id" in old_jobs.columns:
            old_jobs["position_id"] = (
                old_jobs["position_id"]
                .astype(str)
                .str.replace(r"\.0$", "", regex=True)
            )

        if dedupe_key in old_jobs.columns:
            old_jobs[dedupe_key] = normalize_key(old_jobs[dedupe_key])
        else:
            old_jobs[dedupe_key] = None

        if "first_seen_date" not in old_jobs.columns:
            old_jobs["first_seen_date"] = today

        if "last_seen_date" not in old_jobs.columns:
            old_jobs["last_seen_date"] = today

        old_keys = old_jobs[dedupe_key]

        new_jobs = current_jobs[
            ~current_jobs[dedupe_key].isin(old_keys)
        ].copy()

        old_jobs = old_jobs.drop_duplicates(
            subset=[dedupe_key],
            keep="last",
        )

        current_jobs["first_seen_date"] = current_jobs[dedupe_key].map(
            old_jobs.set_index(dedupe_key)["first_seen_date"]
        )

        current_jobs["first_seen_date"] = (
            current_jobs["first_seen_date"]
            .fillna(today)
        )

        jobs = pd.concat(
            [old_jobs, current_jobs],
            ignore_index=True,
        )

        jobs = jobs.drop_duplicates(
            subset=[dedupe_key],
            keep="last",
        )

    else:
        current_jobs["first_seen_date"] = today
        new_jobs = current_jobs
        jobs = current_jobs

    if "posted_date" in jobs.columns:
        jobs["posted_date_sort"] = pd.to_datetime(
            jobs["posted_date"],
            errors="coerce",
        )

        jobs = (
            jobs
            .sort_values(
                by=["posted_date_sort", "last_seen_date"],
                ascending=[False, False],
            )
            .drop(columns=["posted_date_sort"])
        )

    jobs = add_semantic_scores(jobs)

    preferred_order = [
        "title",
        "team",
        "location",
        "city",
        "state",
        "posted_date",
        "job_id",
        "internal_job_id",
        "requisition_id",
        "position_id",
        "source",
        "first_seen_date",
        "last_seen_date",
        "semantic_similarity",
        "management_level",
        "job_profile",
        "job_category",
        "job_family",
        "worker_type",
        "worker_sub_type",
        "schedule_type",
        "time_type",
        "pay_rate_type",
        "scheduled_weekly_hours",
        "company_name",
        "education",
        "cost_center",
        "office",
        "country",
        "brand",
        "industry",
        "experience_level",
        "remote",
        "hybrid",
        "recruiting_start_date",
        "target_hire_date",
        "target_hire_end_date",
        "application_deadline",
        "updated_time",
        "url",
        "description_short",
        "basic_qualifications",
        "preferred_qualifications",
        "description",
    ]

    existing_cols = [c for c in preferred_order if c in jobs.columns]
    remaining_cols = [c for c in jobs.columns if c not in preferred_order]

    jobs = jobs[existing_cols + remaining_cols]

    if "position_id" in jobs.columns:
        jobs["position_id"] = (
            jobs["position_id"]
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
        )

    jobs.to_csv(output_path, index=False)

    print(f"\nFound {len(current_jobs)} current jobs")
    print(f"Found {len(new_jobs)} truly new jobs")

    if len(new_jobs) > 0:
        print("\nNew jobs:")

        for _, job in new_jobs.iterrows():
            title = job.get("title", "No title")
            url = job.get("url", "")

            print(f"\n- {title}")

            if url:
                print(f"  {url}")

    print(f"\nSaved {len(jobs)} total jobs to {output_path}")

    return new_jobs


def run_pipeline():

    os.makedirs(RAW_DATA_DIR, exist_ok=True)

    scrapers = [
        ("MercadoLibre", scrape_mercadolibre, MERCADOLIBRE_OUTPUT_PATH),
        ("Uber", scrape_uber, UBER_OUTPUT_PATH),
        ("Amazon", scrape_amazon, AMAZON_OUTPUT_PATH),
        ("Falabella", scrape_falabella, FALABELLA_OUTPUT_PATH),
        ("Cencosud", scrape_cencosud, CENCOSUD_OUTPUT_PATH),
        ("Walmart", scrape_walmart, WALMART_OUTPUT_PATH),
        ("CCU", scrape_ccu, CCU_OUTPUT_PATH),
        ("Ripley", scrape_ripley, RIPLEY_OUTPUT_PATH),
        ("Unilever", scrape_unilever, UNILEVER_OUTPUT_PATH),
        ("SMU", scrape_smu, SMU_OUTPUT_PATH),
        ("Andina", scrape_andina, ANDINA_OUTPUT_PATH),
        ("Embonor", scrape_embonor, EMBONOR_OUTPUT_PATH),
        ("Forus", scrape_forus, FORUS_OUTPUT_PATH),
        ("Rosen", scrape_rosen, ROSEN_OUTPUT_PATH),
        ("Ahumada", scrape_ahumada, AHUMADA_OUTPUT_PATH),
        ("Carozzi", scrape_carozzi, CAROZZI_OUTPUT_PATH),
        ("Salcobrand", scrape_salcobrand, SALCOBRAND_OUTPUT_PATH),
        ("PF", scrape_pf, PF_OUTPUT_PATH),
        ("Tricot", scrape_tricot, TRICOT_OUTPUT_PATH),
        ("abc", scrape_abc, ABC_OUTPUT_PATH),
        ("Casaideas", scrape_casaideas, CASAIDEAS_OUTPUT_PATH),
        ("Soprole", scrape_soprole, SOPROLE_OUTPUT_PATH),
        ("Watts", scrape_watts, WATTS_OUTPUT_PATH),
        ("Entel", scrape_entel, ENTEL_OUTPUT_PATH),
        ("PedidosYa", scrape_pedidosya, PEDIDOSYA_OUTPUT_PATH),
        ("Rappi", scrape_rappi, RAPPI_OUTPUT_PATH),
        ("P&G", scrape_pg, PG_OUTPUT_PATH),
        ("L'Oréal", scrape_loreal, LOREAL_OUTPUT_PATH),
        ("Nestlé", scrape_nestle, NESTLE_OUTPUT_PATH),
        ("Bci", scrape_bci, BCI_OUTPUT_PATH),
        ("Banco de Chile", scrape_bancochile, BANCOCHILE_OUTPUT_PATH),
        ("Santander", scrape_santander, SANTANDER_OUTPUT_PATH),
        ("Scotiabank", scrape_scotiabank, SCOTIABANK_OUTPUT_PATH),
        ("Tenpo", scrape_tenpo, TENPO_OUTPUT_PATH),
        ("PepsiCo", scrape_pepsico, PEPSICO_OUTPUT_PATH),
        ("Mondelez", scrape_mondelez, MONDELEZ_OUTPUT_PATH),
        ("Kimberly-Clark", scrape_kimberlyclark, KIMBERLYCLARK_OUTPUT_PATH),
        ("Colgate", scrape_colgate, COLGATE_OUTPUT_PATH),
        ("Kenvue", scrape_kenvue, KENVUE_OUTPUT_PATH),
        ("Beiersdorf", scrape_beiersdorf, BEIERSDORF_OUTPUT_PATH),
    ]

    scraped_jobs = []
    failed_companies = []

    for company, scraper, output_path in scrapers:
        print_section(company)
        try:
            jobs = scraper()
        except Exception as error:
            print(f"ERROR scraping {company}: {error}")
            failed_companies.append(company)
            jobs = pd.DataFrame()
        scraped_jobs.append((company, jobs, output_path))

    print_phase("Processing results")

    for company, jobs, output_path in scraped_jobs:
        save_jobs(jobs, output_path, company)

    print_phase("Exporting recent jobs")

    recent_jobs = build_recent_jobs()
    recent_jobs.to_csv("data/recent_jobs.csv", index=False)

    print(f"Saved {len(recent_jobs)} recent jobs to data/recent_jobs.csv")
    print_phase("Updating README")

    generate_readme()
    print("Updated README.md")

    if failed_companies:
        print(
            f"\nWARNING: {len(failed_companies)} scraper(s) failed and kept "
            f"their previous data: {', '.join(failed_companies)}"
        )