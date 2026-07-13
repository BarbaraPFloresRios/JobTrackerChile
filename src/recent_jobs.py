import glob
import pandas as pd


RECENT_JOBS_COLUMNS = [
    "title",
    "company",
    "location",
    "semantic_similarity",
    "first_seen_date",
    "url",
]


def build_recent_jobs():
    today = pd.Timestamp.today().normalize()
    yesterday = today - pd.Timedelta(days=1)

    dfs = []

    for path in glob.glob("data/raw/*_jobs.csv"):
        df = pd.read_csv(path)

        df["first_seen_date"] = pd.to_datetime(
            df["first_seen_date"],
            errors="coerce"
        ).dt.normalize()

        recent = df[df["first_seen_date"].isin([today, yesterday])].copy()

        if recent.empty:
            continue

        if "company_name" in recent.columns:
            recent["company"] = recent["company_name"].fillna(recent["source"])
        else:
            recent["company"] = recent["source"]

        recent = recent[
        [
            "title",
            "company",
            "location",
            "semantic_similarity",
            "first_seen_date",
            "url",
        ]
    ]

        dfs.append(recent)

    if not dfs:
        return pd.DataFrame(columns=RECENT_JOBS_COLUMNS)

    result = pd.concat(dfs, ignore_index=True)

    result = result.sort_values(
        ["first_seen_date", "semantic_similarity"],
        ascending=[False, False]
    )

    return result


if __name__ == "__main__":
    df = build_recent_jobs()

    df.to_csv("data/recent_jobs.csv", index=False)

    print(f"Saved {len(df)} jobs")