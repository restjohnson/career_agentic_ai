#!/usr/bin/env python3
"""
Batch load Kaggle job descriptions → extract fields → embed → insert to Supabase.

Usage:
    python load_job_examples.py --csv_path data/jobs.csv --source kaggle_jobs

Expects CSV with columns: Title, ExperienceLevel, YearsofExperience, Skills, Responsibilities, Keywords
"""
import sys
import os
from pathlib import Path

# Load .env file before any imports that need environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from langchain_openai import OpenAIEmbeddings
from app.tools.supabase_repo import SupabaseRepo


def parse_semicolon_list(value: str) -> list[str]:
    """Parse semicolon-separated string into list of trimmed strings."""
    if not isinstance(value, str) or not value:
        return []
    return [s.strip() for s in value.split(';') if s.strip()]


def parse_years_of_experience(years_str: str) -> int | None:
    """
    Parse years of experience from various formats.
    Examples: "3-5 years" → 3, "5" → 5, "junior" → None
    """
    if not isinstance(years_str, str) or not years_str.strip():
        return None

    try:
        # Extract first number from the string
        parts = years_str.split('-')[0].split()
        for part in parts:
            if part.isdigit():
                return int(part)
    except (ValueError, IndexError):
        pass
    return None


def load_kaggle_dataset(csv_path: str, source_name: str, batch_size: int = 50):
    """
    Load Kaggle dataset with pre-extracted fields.

    Expected columns: Title, ExperienceLevel, YearsofExperience, Skills, Responsibilities, Keywords
    """
    print(f"Loading CSV from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows")

    # Deduplicate by Title (keep first occurrence)
    initial_count = len(df)
    df = df.drop_duplicates(subset=['Title'], keep='first')
    print(f"After deduplication: {len(df)} rows (removed {initial_count - len(df)} duplicates)")

    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    repo = SupabaseRepo()

    rows_to_insert = []
    skipped = 0

    for idx, row in df.iterrows():
        job_title = str(row.get('Title', '')).strip()

        if not job_title:
            skipped += 1
            continue

        # Parse semicolon-separated fields
        responsibilities = parse_semicolon_list(row.get('Responsibilities', ''))
        keywords = parse_semicolon_list(row.get('Keywords', ''))
        skills = parse_semicolon_list(row.get('Skills', ''))

        # Parse years of experience
        years_str = str(row.get('YearsofExperience', ''))
        years_exp = parse_years_of_experience(years_str)

        # Optional: extract experience level
        experience_level = str(row.get('ExperienceLevel', '')).strip()

        # Embedding text: job_title + responsibilities + keywords
        embedding_text = f"{job_title} {' '.join(responsibilities + keywords)}"

        if not embedding_text.strip():
            skipped += 1
            continue

        try:
            vec = embedder.embed_query(embedding_text)
        except Exception as e:
            print(f"  ⚠ Embedding failed for '{job_title}': {e}")
            skipped += 1
            continue

        rows_to_insert.append({
            "job_title": job_title,
            "kaggle_source": source_name,
            "years_of_experience": years_exp,
            "key_skills": skills[:10],          # top 10 skills
            "key_knowledge": keywords[:5],      # top 5 keywords
            "embedding_text": embedding_text,
            "embedding": vec,
        })

        # Batch insert every N rows
        if len(rows_to_insert) >= batch_size:
            try:
                count = repo.insert_job_examples(rows_to_insert)
                print(f"  ✓ Inserted {count} rows (progress: {idx + 1}/{len(df)})")
                rows_to_insert = []
            except Exception as e:
                print(f"  ✗ Batch insert failed: {e}")
                skipped += len(rows_to_insert)
                rows_to_insert = []

    # Final batch
    if rows_to_insert:
        try:
            count = repo.insert_job_examples(rows_to_insert)
            print(f"  ✓ Inserted {count} final rows")
        except Exception as e:
            print(f"  ✗ Final batch insert failed: {e}")
            skipped += len(rows_to_insert)

    print(f"\n✓ Complete!")
    print(f"  Total rows processed: {len(df)}")
    print(f"  Successfully embedded and inserted: {len(df) - skipped}")
    print(f"  Skipped: {skipped}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Load Kaggle job dataset into Supabase vector DB"
    )
    parser.add_argument(
        "--csv_path",
        required=True,
        help="Path to CSV file with job data"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source name/identifier (e.g., kaggle_jobs, linkedin_jobs)"
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=50,
        help="Batch size for Supabase inserts (default: 50)"
    )

    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"✗ File not found: {args.csv_path}")
        sys.exit(1)

    try:
        load_kaggle_dataset(args.csv_path, args.source, args.batch_size)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
