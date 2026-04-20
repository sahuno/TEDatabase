# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Coordinate parsing, validation, locus ID construction, and overlap utilities

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# hg38 chromosome sizes (main chromosomes only).
# These are fixed biological constants used solely for input validation,
# not for genomic analysis — an intentional exception to the no-hardcoding rule.
# Source: https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.chrom.sizes
# ---------------------------------------------------------------------------

_HG38_CHROM_SIZES: dict[str, int] = {
    "chr1":  248956422,
    "chr2":  242193529,
    "chr3":  198295559,
    "chr4":  190214555,
    "chr5":  181538259,
    "chr6":  170805979,
    "chr7":  159345973,
    "chr8":  145138636,
    "chr9":  138394717,
    "chr10": 133797422,
    "chr11": 135086622,
    "chr12": 133275309,
    "chr13": 114364328,
    "chr14": 107043718,
    "chr15": 101991189,
    "chr16":  90338345,
    "chr17":  83257441,
    "chr18":  80373285,
    "chr19":  58617616,
    "chr20":  64444167,
    "chr21":  46709983,
    "chr22":  50818468,
    "chrX":  156040895,
    "chrY":   57227415,
    "chrM":      16569,
}

# ---------------------------------------------------------------------------
# Chromosome name parsing
# ---------------------------------------------------------------------------

_NUMERIC_TO_UCSC: dict[str, str] = {str(i): f"chr{i}" for i in range(1, 23)}
_NUMERIC_TO_UCSC["23"] = "chrX"
_NUMERIC_TO_UCSC["24"] = "chrY"
_NUMERIC_TO_UCSC["X"] = "chrX"
_NUMERIC_TO_UCSC["Y"] = "chrY"
_NUMERIC_TO_UCSC["M"] = "chrM"
_NUMERIC_TO_UCSC["MT"] = "chrM"

_VALID_UCSC = set(_HG38_CHROM_SIZES.keys())


def parse_chrom(s: str) -> str | None:
    """
    Normalize a chromosome name to UCSC style (e.g. ``chr1``, ``chrX``).

    Handles:
    - Already-prefixed names: ``"chrX"`` -> ``"chrX"``
    - Bare numerics: ``"2"`` -> ``"chr2"``
    - Special aliases: ``"23"`` -> ``"chrX"``, ``"24"`` -> ``"chrY"``
    - Mitochondrial: ``"M"`` / ``"MT"`` -> ``"chrM"``

    Parameters
    ----------
    s : str
        Raw chromosome string from a data source.

    Returns
    -------
    str or None
        Normalized UCSC chromosome string, or ``None`` if the input cannot
        be mapped to a known chromosome.

    Examples
    --------
    >>> parse_chrom("2")
    'chr2'
    >>> parse_chrom("chrX")
    'chrX'
    >>> parse_chrom("23")
    'chrX'
    >>> parse_chrom("24")
    'chrY'
    >>> parse_chrom("garbage") is None
    True
    """
    if not isinstance(s, str) or not s.strip():
        return None

    s = s.strip()

    # Already in UCSC format
    if s in _VALID_UCSC:
        return s

    # Has "chr" prefix but not in our valid set — could be an alt contig
    if s.startswith("chr"):
        suffix = s[3:]
        mapped = _NUMERIC_TO_UCSC.get(suffix)
        if mapped and mapped in _VALID_UCSC:
            return mapped
        # Accept as-is only if it matches a known chrom form after prefix stripping
        return None

    # Bare string — try direct lookup
    mapped = _NUMERIC_TO_UCSC.get(s.upper(), _NUMERIC_TO_UCSC.get(s))
    if mapped and mapped in _VALID_UCSC:
        return mapped

    return None


# ---------------------------------------------------------------------------
# Coordinate validation
# ---------------------------------------------------------------------------

def validate_hg38_coords(chrom: str, start: int, end: int) -> bool:
    """
    Validate that coordinates are in-range for the given hg38 chromosome.

    Parameters
    ----------
    chrom : str
        UCSC-style chromosome name (e.g. ``"chr1"``).
    start : int
        0-based start position (inclusive).
    end : int
        0-based end position (exclusive).

    Returns
    -------
    bool
        ``True`` if the chromosome is known and the interval is valid.

    Examples
    --------
    >>> validate_hg38_coords("chr1", 1000, 2000)
    True
    >>> validate_hg38_coords("chr1", -1, 100)
    False
    >>> validate_hg38_coords("chr99", 0, 100)
    False
    """
    if chrom not in _HG38_CHROM_SIZES:
        return False
    chrom_len = _HG38_CHROM_SIZES[chrom]
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and start >= 0
        and end > start
        and end <= chrom_len
    )


# ---------------------------------------------------------------------------
# Locus ID construction
# ---------------------------------------------------------------------------

def make_locus_id(chrom: str, start: int, end: int, strand: str) -> str:
    """
    Build a canonical locus ID for a somatic LINE-1 insertion.

    Format: ``L1SOI-{chrom}-{start:09d}-{end:09d}-{strand}``

    Parameters
    ----------
    chrom : str
        UCSC-style chromosome name.
    start : int
        0-based start coordinate.
    end : int
        0-based end coordinate.
    strand : str
        Strand (``"+"`` or ``"-"``).

    Returns
    -------
    str
        Canonical locus ID string.

    Examples
    --------
    >>> make_locus_id("chr7", 117548628, 117548729, "+")
    'L1SOI-chr7-117548628-117548729-+'
    """
    return f"L1SOI-{chrom}-{start:09d}-{end:09d}-{strand}"


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------

def coords_overlap(
    c1: str,
    s1: int,
    e1: int,
    c2: str,
    s2: int,
    e2: int,
    window: int = 100,
) -> bool:
    """
    Return ``True`` if two intervals are on the same chromosome and overlap
    within ``window`` bp of each other.

    Two intervals are considered overlapping (with window) when:
    ``s1 - window <= e2`` and ``s2 - window <= e1`` (both on same chromosome).

    Parameters
    ----------
    c1, c2 : str
        Chromosome names.
    s1, e1 : int
        Start/end of first interval (0-based, half-open).
    s2, e2 : int
        Start/end of second interval (0-based, half-open).
    window : int, optional
        Distance window in bp (default 100). Two intervals within this
        distance are treated as potentially the same insertion.

    Returns
    -------
    bool
        ``True`` if the intervals are on the same chromosome and within
        ``window`` bp of each other.

    Examples
    --------
    >>> coords_overlap("chr1", 1000, 1100, "chr1", 1150, 1250, window=100)
    True
    >>> coords_overlap("chr1", 1000, 1100, "chr2", 1000, 1100)
    False
    >>> coords_overlap("chr1", 1000, 1100, "chr1", 1300, 1400, window=100)
    False
    """
    if c1 != c2:
        return False
    # Expand each interval by the window on both sides
    return (s1 - window) < e2 and (s2 - window) < e1
