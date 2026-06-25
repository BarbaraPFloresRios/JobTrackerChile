from pathlib import Path

import numpy as np
import pandas as pd

import warnings

warnings.filterwarnings(
    "ignore",
    message="Failed to load image Python extension.*"
)


from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


MODEL_NAME = "all-MiniLM-L6-v2"
PROFILE_PATH = Path("data/profile/job_matching_profile.txt")

EXCLUDED_COLUMNS = {
    "url",
    "job_id",
    "first_seen_date",
    "last_seen_date",
    "updated_time",
}


def build_job_text(row):
    parts = []

    for col, value in row.items():
        if col in EXCLUDED_COLUMNS:
            continue

        if pd.notna(value) and str(value).strip():
            parts.append(f"{col}: {value}")

    return "\n".join(parts)


def add_semantic_scores(jobs):
    if jobs.empty:
        return jobs
    
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"Profile file not found: {PROFILE_PATH}")

    profile_text = PROFILE_PATH.read_text(encoding="utf-8")
    job_texts = jobs.apply(build_job_text, axis=1).tolist()

    model = SentenceTransformer(MODEL_NAME)

    profile_embedding = model.encode([profile_text], normalize_embeddings=True)
    job_embeddings = model.encode(job_texts, normalize_embeddings=True)

    similarities = cosine_similarity(job_embeddings, profile_embedding).flatten()

    jobs = jobs.copy()

    columns_to_drop = ["fit_score", "relative_fit_score"]
    jobs = jobs.drop(
        columns=[c for c in columns_to_drop if c in jobs.columns]
    )

    jobs["semantic_similarity"] = np.round(similarities, 4)

    return jobs


