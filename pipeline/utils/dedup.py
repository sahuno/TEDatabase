# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Deduplication and merge utilities for LINE-1 somatic insertion loci

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pipeline.utils.coordinates import coords_overlap, parse_chrom

# ---------------------------------------------------------------------------
# Schema defaults — every locus record must have these keys
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: dict[str, object] = {
    "locus_id": None,
    "chrom": None,
    "start": None,
    "end": None,
    "strand": None,
    "genome_build": None,
    "l1_family": None,
    "l1_subtype": None,
    "insertion_type": None,
    "tissue_type": [],
    "cancer_type": [],
    "gene_name": None,
    "gene_region": None,
    "validation_level": None,
    "validation_method": [],
    "detection_method": [],
    "n_samples_detected": None,
    "vaf": None,
    "source_pmid": [],
    "source_doi": None,
    "source_type": None,
    "coordinate_confidence": None,
    "coordinate_source": None,
    "liftover_performed": False,
    "original_build": None,
    "l1base2_uid": None,
    "l1base2_category": None,
    "is_full_length": None,
    "has_orf1": None,
    "has_orf2": None,
    "paper_year": None,
    "paper_journal": None,
    "date_added": None,
    "date_updated": None,
    "version": 1,
    "notes": None,
}

# Fields whose values are lists and should be union-merged
_LIST_FIELDS: set[str] = {
    "source_pmid",
    "tissue_type",
    "cancer_type",
    "validation_method",
    "detection_method",
}

# Confidence ranking for coordinate_confidence (higher index = more confident)
_CONFIDENCE_RANK: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


# ---------------------------------------------------------------------------
# normalize_locus
# ---------------------------------------------------------------------------

def normalize_locus(locus: dict) -> dict:
    """
    Ensure a locus dict has all required fields, normalising as needed.

    Missing fields are filled with the schema defaults. The ``chrom`` field
    is normalised via :func:`~pipeline.utils.coordinates.parse_chrom`.
    Array-valued fields are deduplicated and sorted.

    Parameters
    ----------
    locus : dict
        Raw locus dict (e.g. as extracted by the LLM step).

    Returns
    -------
    dict
        New dict with all required fields present.

    Example
    -------
    >>> norm = normalize_locus({"chrom": "2", "source_pmid": ["12345", "12345"]})
    >>> norm["chrom"]
    'chr2'
    >>> norm["source_pmid"]
    ['12345']
    """
    import copy
    out: dict = {}

    # Fill defaults first
    for field, default in _REQUIRED_FIELDS.items():
        if isinstance(default, list):
            out[field] = list(default)  # fresh copy of default list
        else:
            out[field] = default

    # Overlay with values from the incoming locus
    for field, default in _REQUIRED_FIELDS.items():
        incoming = locus.get(field)
        if field in _LIST_FIELDS:
            if isinstance(incoming, list):
                out[field] = incoming
            elif incoming is not None:
                out[field] = [incoming]
            # else: keep the empty-list default
        else:
            if incoming is not None:
                out[field] = incoming

    # Normalise chrom
    raw_chrom = out.get("chrom")
    if raw_chrom is not None:
        out["chrom"] = parse_chrom(str(raw_chrom))

    # Sort and deduplicate list fields
    for field in _LIST_FIELDS:
        raw_list = out.get(field)
        if isinstance(raw_list, list):
            out[field] = sorted(set(str(v) for v in raw_list if v is not None))

    # Carry through any extra keys not in the schema
    for key, val in locus.items():
        if key not in out:
            out[key] = val

    return out


# ---------------------------------------------------------------------------
# merge_loci
# ---------------------------------------------------------------------------

def merge_loci(existing: dict, new: dict) -> dict:
    """
    Merge a new locus record into an existing record for the same genomic
    position.

    Merge rules:
    - List fields (``source_pmid``, ``tissue_type``, etc.): union, deduplicated.
    - ``coordinate_confidence``: keep the more confident value (high > medium > low).
    - ``version``: incremented by 1.
    - ``date_updated``: set to today.
    - All other scalar fields: prefer non-``None`` from ``existing``; fall back
      to ``new`` if ``existing`` is ``None``.
    - ``notes``: concatenate with ``"; "`` separator, deduplicating identical
      notes.

    Parameters
    ----------
    existing : dict
        The master-database record to update.
    new : dict
        The incoming record to merge in.

    Returns
    -------
    dict
        Merged record (a new dict; neither input is mutated).

    Example
    -------
    >>> m = merge_loci({"source_pmid": ["111"], "version": 1, "notes": "A"},
    ...                {"source_pmid": ["222"], "notes": "B"})
    >>> sorted(m["source_pmid"])
    ['111', '222']
    >>> m["version"]
    2
    """
    merged: dict = dict(existing)  # shallow copy

    # Union-merge list fields
    for field in _LIST_FIELDS:
        existing_list: list = existing.get(field) or []
        new_list: list = new.get(field) or []
        combined = sorted(set(list(existing_list) + list(new_list)))
        merged[field] = combined

    # Keep the more confident coordinate
    existing_conf = _CONFIDENCE_RANK.get(existing.get("coordinate_confidence") or "", -1)
    new_conf = _CONFIDENCE_RANK.get(new.get("coordinate_confidence") or "", -1)
    if new_conf > existing_conf:
        merged["coordinate_confidence"] = new.get("coordinate_confidence")

    # Scalar fields: prefer non-None from existing, then fall back to new
    scalar_skip = _LIST_FIELDS | {"coordinate_confidence", "version", "date_updated", "notes"}
    for field in _REQUIRED_FIELDS:
        if field in scalar_skip:
            continue
        if merged.get(field) is None and new.get(field) is not None:
            merged[field] = new[field]

    # Merge notes
    existing_notes: str = (existing.get("notes") or "").strip()
    new_notes: str = (new.get("notes") or "").strip()
    if existing_notes and new_notes:
        parts = [p.strip() for p in (existing_notes + "; " + new_notes).split(";")]
        unique_parts = list(dict.fromkeys(p for p in parts if p))  # preserve order, dedup
        merged["notes"] = "; ".join(unique_parts)
    elif new_notes:
        merged["notes"] = new_notes
    else:
        merged["notes"] = existing_notes or None

    # Bookkeeping
    merged["version"] = (existing.get("version") or 1) + 1
    merged["date_updated"] = str(date.today())

    return merged


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------

def find_duplicates(
    loci: list[dict],
    window: int = 100,
) -> list[tuple[int, int]]:
    """
    Find pairs of loci that are potential duplicates.

    Two loci are considered potential duplicates when they share the same
    chromosome and strand, and their coordinates overlap within ``window`` bp.

    Parameters
    ----------
    loci : list[dict]
        List of normalised locus records (must have ``chrom``, ``start``,
        ``end``, and ``strand`` keys).
    window : int, optional
        Distance window in bp (default 100).

    Returns
    -------
    list[tuple[int, int]]
        List of ``(i, j)`` index pairs (``i < j``) where the two loci are
        potential duplicates.

    Example
    -------
    >>> loci = [
    ...     {"chrom": "chr1", "start": 1000, "end": 1100, "strand": "+"},
    ...     {"chrom": "chr1", "start": 1050, "end": 1150, "strand": "+"},
    ...     {"chrom": "chr1", "start": 5000, "end": 5100, "strand": "+"},
    ... ]
    >>> find_duplicates(loci, window=100)
    [(0, 1)]
    """
    dupes: list[tuple[int, int]] = []
    n = len(loci)

    for i in range(n):
        a = loci[i]
        c1 = a.get("chrom")
        s1 = a.get("start")
        e1 = a.get("end")
        st1 = a.get("strand")
        if c1 is None or s1 is None or e1 is None:
            continue

        for j in range(i + 1, n):
            b = loci[j]
            c2 = b.get("chrom")
            s2 = b.get("start")
            e2 = b.get("end")
            st2 = b.get("strand")
            if c2 is None or s2 is None or e2 is None:
                continue
            # Must share the same strand (or either be unknown)
            if st1 and st2 and st1 != st2:
                continue
            if coords_overlap(c1, s1, e1, c2, s2, e2, window=window):
                dupes.append((i, j))

    return dupes
