# TEDatabase — LINE-1 Somatic Insertion Tracker
# Author: Samuel Ahuno | ekwame001@gmail.com
# Greenbaum Lab, MSKCC

## Project Overview
Automated database and static website of active somatic LINE-1 insertions in humans (hg38).
Weekly pipeline: PubMed search → PDF download → Claude API extraction → dedup/merge → site deploy.

## Key File Paths
- **Master loci**: `data/processed/loci.json` — never edit manually
- **Papers index**: `data/processed/papers.json`
- **Pipeline run log**: `data/processed/run_log.jsonl`
- **Seen PMIDs**: `data/raw/pmids_seen.txt`
- **Site root**: `site/` — deploys to GitHub Pages

## Running the Pipeline

```bash
# Full run (all 6 stages):
bash scripts/run_pipeline.sh

# First-ever run (seed L1Base2 first):
bash scripts/run_pipeline.sh --seed

# Single stage:
python pipeline/01_pubmed_search.py
python pipeline/02_paper_fetch.py
python pipeline/03_llm_extract.py
python pipeline/04_liftover.py
python pipeline/05_dedup_merge.py
python pipeline/06_build_site_data.py

# Validate data:
bash scripts/validate_data.sh
```

## Required Environment Variables
- `ANTHROPIC_API_KEY` — for PDF/table parsing (stage 3)
- `NCBI_API_KEY` — optional, increases PubMed rate limit to 10 req/sec

Set in `.env` locally; in GitHub Secrets for CI.

## Pipeline Stage Summary
| Stage | Script | Input | Output |
|-------|--------|-------|--------|
| 1 | 01_pubmed_search.py | PubMed API | data/raw/papers_pending.json |
| 2 | 02_paper_fetch.py | papers_pending.json | data/raw/papers_to_extract.json |
| 3 | 03_llm_extract.py | papers_to_extract.json | data/raw/loci_raw.json |
| 4 | 04_liftover.py | loci_raw.json | data/raw/loci_lifted.json |
| 5 | 05_dedup_merge.py | loci_lifted.json + loci.json | data/processed/loci.json |
| 6 | 06_build_site_data.py | loci.json | site/data/ |

## Data Schema
See pipeline/config.py for field definitions. Key rules:
- `locus_id` format: `L1SOI-{chrom}-{start:09d}-{end:09d}-{strand}`
- All coordinates: hg38, 0-based half-open
- `source_type`: "literature" | "l1base2" | "curated"
- `validation_level`: "experimental" | "computational" | "predicted"
- `coordinate_confidence`: "high" | "medium" | "low"

## Deduplication Rules
- Loci within 100 bp on same chrom+strand are flagged as potential duplicates
- Exact locus_id match → merge (union list fields, keep higher confidence coordinate)
- Do not manually resolve duplicate flags — that is intentional audit trail

## GitHub Actions
- `weekly_update.yml` — runs every Monday 03:00 UTC, commits updated data/processed/ and site/data/
- `deploy_site.yml` — deploys site/ to GitHub Pages on any push touching site/ or data/processed/

## Secrets Needed in GitHub Repo Settings
- `ANTHROPIC_API_KEY`
- `NCBI_API_KEY`

## Development Notes
- Raw PDFs and LLM extractions are gitignored (large/re-generatable)
- All intermediate files (papers_pending.json, loci_raw.json, etc.) are ephemeral and gitignored
- Only data/processed/ is committed to git — this is the authoritative database
- Logs go to logs/ (gitignored locally, uploaded as CI artifacts for 30 days)
