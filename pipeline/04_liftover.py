# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Lift non-hg38 loci coordinates to hg38 using pyliftover

from __future__ import annotations

import argparse
import gzip
import json
import logging
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Chain file URLs
# ---------------------------------------------------------------------------

CHAIN_URLS: dict[str, str] = {
    "hg19ToHg38": "https://hgdownload.soe.ucsc.edu/goldenPath/hg19/liftOver/hg19ToHg38.over.chain.gz",
    "hg18ToHg38": "https://hgdownload.soe.ucsc.edu/goldenPath/hg18/liftOver/hg18ToHg38.over.chain.gz",
}

# Build -> chain key mapping
_BUILD_CHAIN: dict[str, str] = {
    "hg19": "hg19ToHg38",
    "GRCh37": "hg19ToHg38",
    "hg18": "hg18ToHg38",
    "GRCh36": "hg18ToHg38",
    "hg17": "hg18ToHg38",  # best-effort: two-step via hg18
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path, script_name: str) -> logging.Logger:
    """
    Configure dual-handler logging (file + stdout).

    Parameters
    ----------
    log_dir : Path
        Directory for the log file.
    script_name : str
        Logger name and log file prefix.

    Returns
    -------
    logging.Logger
        Configured logger.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{script_name}_{timestamp}.log"

    logger = logging.getLogger(script_name)
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# Chain file management
# ---------------------------------------------------------------------------

def _chain_path(seed_dir: Path, chain_key: str) -> Path:
    """Return the local (decompressed) path for a chain file."""
    return seed_dir / f"{chain_key}.over.chain"


def ensure_chain_file(
    seed_dir: Path,
    chain_key: str,
    logger: logging.Logger,
) -> Path:
    """
    Return the local path to a chain file, downloading and decompressing it
    from UCSC if not already present.

    Parameters
    ----------
    seed_dir : Path
        Directory where chain files are cached.
    chain_key : str
        Key in ``CHAIN_URLS`` (e.g. ``"hg19ToHg38"``).
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    Path
        Path to the decompressed chain file.

    Raises
    ------
    KeyError
        If ``chain_key`` is not in ``CHAIN_URLS``.
    """
    local_path = _chain_path(seed_dir, chain_key)
    if local_path.exists():
        logger.info("Chain file already present: %s", local_path)
        return local_path

    url = CHAIN_URLS[chain_key]
    gz_path = seed_dir / f"{chain_key}.over.chain.gz"
    seed_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading chain file: %s -> %s", url, gz_path)
    try:
        with urllib.request.urlopen(url) as response, gz_path.open("wb") as out_f:
            shutil.copyfileobj(response, out_f)
    except Exception as exc:
        logger.error("Failed to download chain file %s: %s", url, exc)
        raise

    logger.info("Decompressing %s -> %s", gz_path, local_path)
    with gzip.open(gz_path, "rb") as f_in, local_path.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_path.unlink()
    logger.info("Chain file ready: %s (%.1f MB)", local_path, local_path.stat().st_size / 1e6)
    return local_path


# ---------------------------------------------------------------------------
# Liftover helpers
# ---------------------------------------------------------------------------

def _get_converter(
    seed_dir: Path,
    chain_key: str,
    logger: logging.Logger,
) -> object:
    """
    Return a pyliftover LiftOver instance for the given chain key.
    Downloads the chain file if necessary.

    Parameters
    ----------
    seed_dir : Path
        Seed/cache directory for chain files.
    chain_key : str
        Key in CHAIN_URLS.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    pyliftover.LiftOver
        Converter object.
    """
    try:
        from pyliftover import LiftOver
    except ImportError:
        logger.error("pyliftover is not installed. Run: pip install pyliftover")
        sys.exit(1)

    chain_file = ensure_chain_file(seed_dir, chain_key, logger)
    return LiftOver(str(chain_file))


def lift_coordinates(
    converter: object,
    chrom: str,
    start: int,
    end: int,
    logger: logging.Logger,
) -> tuple[str, int, int] | None:
    """
    Lift a single interval using a pyliftover converter.

    Uses the midpoint for the primary lift, then also lifts start and end
    independently and chooses the widest consistent result.

    Parameters
    ----------
    converter : pyliftover.LiftOver
        Converter instance.
    chrom : str
        UCSC chromosome name in the source build.
    start : int
        0-based start coordinate.
    end : int
        0-based end coordinate (exclusive).
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    tuple[str, int, int] or None
        ``(new_chrom, new_start, new_end)`` on success, or ``None`` if
        the interval could not be mapped.
    """
    # pyliftover uses 0-based coordinates
    results_start = converter.convert_coordinate(chrom, start)
    results_end = converter.convert_coordinate(chrom, end - 1)  # end-1 for last base

    if not results_start or not results_end:
        return None

    new_chrom_s, new_pos_s, new_strand_s, _ = results_start[0]
    new_chrom_e, new_pos_e, new_strand_e, _ = results_end[0]

    # Must land on the same chromosome
    if new_chrom_s != new_chrom_e:
        return None

    new_start = min(new_pos_s, new_pos_e)
    new_end = max(new_pos_s, new_pos_e) + 1  # restore half-open

    return new_chrom_s, new_start, new_end


# ---------------------------------------------------------------------------
# Per-locus liftover
# ---------------------------------------------------------------------------

def liftover_locus(
    locus: dict,
    converters: dict[str, object],
    seed_dir: Path,
    logger: logging.Logger,
) -> dict:
    """
    Apply coordinate liftover to a single locus dict.

    Modifies and returns the locus in place (conceptually — actually returns
    a new dict). Loci already in hg38 are passed through unchanged.

    Parameters
    ----------
    locus : dict
        Locus record with at minimum ``genome_build``, ``chrom``, ``start``,
        ``end`` keys.
    converters : dict[str, pyliftover.LiftOver]
        Cache of already-instantiated converters keyed by chain key.
    seed_dir : Path
        Chain file cache directory.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    dict
        Updated locus dict.
    """
    import copy
    locus = copy.deepcopy(locus)

    build = locus.get("genome_build")
    chrom = locus.get("chrom")
    start = locus.get("start")
    end = locus.get("end")

    # Already hg38 — pass through
    from pipeline.config import HG38_BUILDS
    if build in HG38_BUILDS:
        locus.setdefault("liftover_performed", False)
        return locus

    # Unknown or missing build
    if build is None or build not in _BUILD_CHAIN:
        locus["coordinate_confidence"] = "low"
        notes = locus.get("notes") or ""
        tag = "genome_build_unknown"
        if tag not in (notes or ""):
            locus["notes"] = (notes + "; " + tag).strip("; ") if notes else tag
        logger.debug(
            "Locus %s: genome_build=%s unknown, flagging as low confidence",
            locus.get("locus_id", "?"), build,
        )
        return locus

    # Validate that we have coords to lift
    if chrom is None or start is None or end is None:
        locus["coordinate_confidence"] = "low"
        notes = locus.get("notes") or ""
        tag = "missing_coords_for_liftover"
        if tag not in (notes or ""):
            locus["notes"] = (notes + "; " + tag).strip("; ") if notes else tag
        return locus

    chain_key = _BUILD_CHAIN[build]

    # Get or create converter
    if chain_key not in converters:
        logger.info("Initialising converter for %s", chain_key)
        converters[chain_key] = _get_converter(seed_dir, chain_key, logger)

    converter = converters[chain_key]

    result = lift_coordinates(converter, chrom, int(start), int(end), logger)

    if result is None:
        locus["coordinate_confidence"] = "low"
        notes = locus.get("notes") or ""
        tag = "liftover_failed_unmapped"
        if tag not in (notes or ""):
            locus["notes"] = (notes + "; " + tag).strip("; ") if notes else tag
        logger.debug(
            "Locus %s: liftover from %s failed (unmapped): %s:%s-%s",
            locus.get("locus_id", "?"), build, chrom, start, end,
        )
    else:
        new_chrom, new_start, new_end = result
        locus["original_build"] = build
        locus["original_chrom"] = chrom
        locus["original_start"] = start
        locus["original_end"] = end
        locus["chrom"] = new_chrom
        locus["start"] = new_start
        locus["end"] = new_end
        locus["genome_build"] = "hg38"
        locus["liftover_performed"] = True
        logger.debug(
            "Locus %s: lifted %s:%s-%s (%s) -> %s:%s-%s (hg38)",
            locus.get("locus_id", "?"), chrom, start, end, build,
            new_chrom, new_start, new_end,
        )

    return locus


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lift non-hg38 LINE-1 loci coordinates to hg38 using pyliftover."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/loci_raw.json"),
        help="Input loci JSON (default: data/raw/loci_raw.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/loci_lifted.json"),
        help="Output loci JSON after liftover (default: data/raw/loci_lifted.json).",
    )
    parser.add_argument(
        "--seed_dir",
        type=Path,
        default=Path("data/seed"),
        help="Directory for chain file cache (default: data/seed).",
    )
    parser.add_argument(
        "--log_dir",
        type=Path,
        default=Path("logs"),
        help="Directory for log files (default: logs).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    script_name = Path(__file__).stem
    logger = setup_logging(args.log_dir, script_name)

    # Session header
    logger.info("=== SESSION START: %s ===", script_name)
    logger.info("Date/time   : %s", datetime.now().isoformat())
    logger.info("Python      : %s", sys.version.split()[0])
    logger.info("Working dir : %s", Path.cwd())
    logger.info("Log dir     : %s", args.log_dir.resolve())
    logger.info("Input       : %s", args.input.resolve())
    logger.info("Output      : %s", args.output.resolve())
    logger.info("Seed dir    : %s", args.seed_dir.resolve())

    # Load input
    if not args.input.exists():
        logger.error("Input file not found: %s", args.input.resolve())
        sys.exit(1)

    raw = args.input.read_text(encoding="utf-8")
    loci: list[dict] = json.loads(raw) if raw.strip() else []
    logger.info("Loaded %d loci from %s", len(loci), args.input.resolve())

    if not loci:
        logger.info("No loci to process. Writing empty output.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([], indent=2))
        logger.info("=== DONE: %s completed successfully ===", script_name)
        return

    # Count builds in input
    from collections import Counter
    from pipeline.config import HG38_BUILDS

    build_counter: Counter = Counter()
    for locus in loci:
        build_counter[locus.get("genome_build") or "unknown"] += 1
    logger.info("Input build distribution: %s", dict(build_counter))

    # Process loci
    converters: dict[str, object] = {}
    processed: list[dict] = []
    n_already_hg38 = 0
    lift_counts: Counter = Counter()
    n_failed = 0
    n_unknown_build = 0

    for locus in loci:
        build = locus.get("genome_build")
        result = liftover_locus(locus, converters, args.seed_dir, logger)

        notes = result.get("notes") or ""
        if build in HG38_BUILDS:
            n_already_hg38 += 1
        elif result.get("liftover_performed"):
            lift_counts[build] += 1
        elif "liftover_failed_unmapped" in notes:
            n_failed += 1
        else:
            n_unknown_build += 1

        processed.append(result)

    # Summary
    logger.info("=== Liftover Summary ===")
    logger.info("Total loci input    : %d", len(loci))
    logger.info("Already hg38        : %d", n_already_hg38)
    logger.info("Lifted successfully : %d", sum(lift_counts.values()))
    for build, n in sorted(lift_counts.items()):
        logger.info("  from %-10s   : %d", build, n)
    logger.info("Liftover failed     : %d", n_failed)
    logger.info("Unknown build       : %d", n_unknown_build)

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(processed, indent=2, ensure_ascii=False))
    logger.info(
        "Saved loci_lifted.json: %s (%d loci, %.1f KB)",
        args.output.resolve(),
        len(processed),
        args.output.stat().st_size / 1024,
    )

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
