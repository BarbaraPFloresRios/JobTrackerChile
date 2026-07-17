import pandas as pd


README_PATH = "README.md"
RECENT_JOBS_PATH = "data/recent_jobs.csv"


def make_jobs_table(max_rows=25):
    df = pd.read_csv(RECENT_JOBS_PATH)

    if df.empty:
        return "_No recent jobs found._"

    df = df.sort_values(
        "semantic_similarity",
        ascending=False
    ).head(max_rows)

    rows = [
        "| Title | Company | Location | Similarity | First Seen |",
        "|---|---|---|---:|---|",
    ]

    for _, job in df.iterrows():
        title = str(job.get("title", "")).replace("|", "\\|")
        company = str(job.get("company", "")).replace("|", "\\|")
        location = str(job.get("location", "")).replace("|", "\\|")
        score = job.get("semantic_similarity", "")
        first_seen = job.get("first_seen_date", "")
        url = job.get("url", "")

        try:
            score = f"{float(score):.4f}"
        except (TypeError, ValueError):
            score = ""

        title_cell = f"[{title}]({url})" if url else title

        rows.append(
            f"| {title_cell} | {company} | {location} | {score} | {first_seen} |"
        )

    return "\n".join(rows)


def generate_readme():
    jobs_table = make_jobs_table()

    content = f"""# Chile JobTracker
    
# Latest Jobs

_Updated automatically from `data/recent_jobs.csv`._

{jobs_table}

# About

A lightweight job monitoring and semantic matching system built in Python.

JobTracker automatically collects openings directly from company career pages, maintains historical records of job postings, and ranks opportunities using semantic similarity against a configurable candidate profile.

## Current Features

* Scrape job postings directly from company career pages
* Support multiple companies
* Detect newly discovered openings
* Track historical job data over time
* Run automatically using GitHub Actions
* Store structured datasets as CSV files
* Export recent jobs from the last 7 days
* Semantic job matching using sentence embeddings
* Configurable candidate profile for personalized ranking
* Cosine similarity scoring between jobs and candidate profile

## Status

Active personal project focused on job discovery, semantic search, and recommendation workflows.
"""

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    generate_readme()
    print("Updated README.md")