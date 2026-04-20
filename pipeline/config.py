# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Central configuration constants and helpers for the LINE-1 somatic insertion tracker

from pathlib import Path


# ---------------------------------------------------------------------------
# PubMed search queries
# ---------------------------------------------------------------------------

PUBMED_QUERIES: list[str] = [
    (
        '("LINE-1" OR "L1 retrotransposon" OR "L1HS") AND '
        '("somatic insertion" OR "somatic retrotransposition") AND "human"[organism]'
    ),
    (
        '("retrotransposon" OR "transposable element") AND "somatic" AND '
        '("cancer" OR "tumor") AND ("LINE-1" OR "L1")'
    ),
    '"de novo L1 insertion" AND human',
    '"L1 mobilization" AND somatic AND human',
    (
        '("ATLAS-seq" OR "RC-seq" OR "mTRAP" OR "L1-seq" OR "LEAP-seq") '
        'AND "somatic" AND "human"'
    ),
]

# ---------------------------------------------------------------------------
# Search and processing parameters
# ---------------------------------------------------------------------------

LOOKBACK_DAYS: int = 14
NCBI_BATCH_SIZE: int = 200

# Loci within this many bp on the same chrom+strand are flagged as potential duplicates
DEDUP_WINDOW_BP: int = 100

# ---------------------------------------------------------------------------
# Genomic constants
# ---------------------------------------------------------------------------

VALID_CHROMS: set[str] = (
    {f"chr{i}" for i in range(1, 23)}
    | {"chrX", "chrY"}
)

VALID_GENOME_BUILDS: set[str] = {
    "hg38", "GRCh38",
    "hg19", "GRCh37",
    "hg18", "GRCh36",
    "hg17",
}

HG38_BUILDS: set[str] = {"hg38", "GRCh38"}

# ---------------------------------------------------------------------------
# Claude model identifiers
# ---------------------------------------------------------------------------

CLAUDE_PDF_MODEL: str = "claude-opus-4-5"
CLAUDE_TEXT_MODEL: str = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Project directory layout (all relative to project root)
# ---------------------------------------------------------------------------


def get_project_root() -> Path:
    """
    Return the project root directory (the parent of the directory containing
    this file, i.e. the directory that contains pipeline/).

    Returns
    -------
    Path
        Absolute path to the project root.

    Example
    -------
    >>> root = get_project_root()
    >>> (root / "data").exists()
    True
    """
    return Path(__file__).resolve().parent.parent


_ROOT = get_project_root()

DATA_DIR: Path = _ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
SEED_DIR: Path = DATA_DIR / "seed"
PROCESSED_DIR: Path = DATA_DIR / "processed"
SITE_DATA_DIR: Path = _ROOT / "site" / "data"
