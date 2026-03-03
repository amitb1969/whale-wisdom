---
name: fund-letter-top-recommendations
description: Extract top stock and ETF recommendations from downloaded fund letters.
---

# Fund Letter Top Recommendations Skill

Use this skill when the user wants top stock or ETF ideas from the text files in:

`output/playwright/fund-letters/latest-quarter-content/text/`

## What this skill does

1. Reads one or many fund letter `.txt` files.
2. Scores stock/ETF mentions with a lightweight conviction heuristic.
3. Produces:
   - a per-file ranking, and
   - an aggregate ranking across all selected letters.

## Run

From the repo root:

```bash
python .claude/skills/fund-letter-top-recommendations/scripts/extract_top_recommendations.py \
  --input-dir output/playwright/fund-letters/latest-quarter-content/text \
  --top-n 5
```

For specific files only:

```bash
python .claude/skills/fund-letter-top-recommendations/scripts/extract_top_recommendations.py \
  --files \
    output/playwright/fund-letters/latest-quarter-content/text/001-1-main-capital.txt \
    output/playwright/fund-letters/latest-quarter-content/text/002-arquitos-capital.txt \
    output/playwright/fund-letters/latest-quarter-content/text/003-blue-tower-asset-management.txt \
  --top-n 5
```

Optional outputs:

- `--json-out <path>` writes machine-readable results.
- `--markdown-out <path>` writes a markdown report.

## Interpreting results

- Higher score = stronger evidence of recommendation/conviction language.
- Mentions with keywords like "largest position", "added", "high conviction", and "buy" are weighted higher.
- This is heuristic extraction, not investment advice.
