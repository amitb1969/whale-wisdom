#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_INPUT_DIR = Path("output/playwright/fund-letters/latest-quarter-content/text")

POSITIVE_KEYWORDS = {
    "buy",
    "bought",
    "adding",
    "added",
    "accumulate",
    "initiated",
    "initiate",
    "long",
    "bullish",
    "favorite",
    "high conviction",
    "recommend",
}

HIGH_CONVICTION_KEYWORDS = {
    "largest position",
    "top position",
    "core holding",
    "high conviction",
    "best idea",
    "overweight",
}

STOP_TICKERS = {
    "THE",
    "AND",
    "FOR",
    "WITH",
    "THIS",
    "THAT",
    "WAS",
    "ARE",
    "NOT",
    "FROM",
    "WERE",
    "WILL",
    "ETF",
    "USD",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
}

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
TICKER_PATTERNS = [
    re.compile(r"\$([A-Z]{1,5})\b"),
    re.compile(r"\((?:NYSE|NASDAQ|AMEX|TSX|LSE)\s*[:\-]\s*([A-Z]{1,5})\)", re.IGNORECASE),
    re.compile(r"\(([A-Z]{1,5})\)"),
]
ETF_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9&'\-. ]{1,50}? ETF)\b")


@dataclass
class Mention:
    asset: str
    score: int
    sentence: str


def score_sentence(sentence: str) -> int:
    s = sentence.lower()
    score = 1
    if any(keyword in s for keyword in POSITIVE_KEYWORDS):
        score += 2
    if any(keyword in s for keyword in HIGH_CONVICTION_KEYWORDS):
        score += 3
    return score


def extract_assets(sentence: str) -> set[str]:
    assets: set[str] = set()

    for pattern in TICKER_PATTERNS:
        for match in pattern.findall(sentence):
            ticker = match.upper()
            if ticker in STOP_TICKERS:
                continue
            assets.add(ticker)

    for etf in ETF_PATTERN.findall(sentence):
        assets.add(re.sub(r"\s+", " ", etf.strip()))

    return assets


def extract_mentions(text: str) -> list[Mention]:
    mentions: list[Mention] = []
    for raw_sentence in SENTENCE_SPLIT.split(text):
        sentence = raw_sentence.strip()
        if len(sentence) < 20:
            continue

        assets = extract_assets(sentence)
        if not assets:
            continue

        base_score = score_sentence(sentence)
        for asset in assets:
            mentions.append(Mention(asset=asset, score=base_score, sentence=sentence))

    return mentions


def rank_mentions(mentions: Iterable[Mention]) -> list[dict[str, object]]:
    aggregate: dict[str, dict[str, object]] = {}
    for mention in mentions:
        if mention.asset not in aggregate:
            aggregate[mention.asset] = {"asset": mention.asset, "score": 0, "mentions": 0, "examples": []}
        row = aggregate[mention.asset]
        row["score"] = int(row["score"]) + mention.score
        row["mentions"] = int(row["mentions"]) + 1
        examples = row["examples"]
        if len(examples) < 3:
            examples.append(mention.sentence)

    ranked = sorted(aggregate.values(), key=lambda item: (int(item["score"]), int(item["mentions"])), reverse=True)
    return ranked


def resolve_files(input_dir: Path, explicit_files: list[Path] | None) -> list[Path]:
    if explicit_files:
        return [f for f in explicit_files if f.exists()]
    return sorted(input_dir.glob("*.txt"))


def format_markdown(result: dict[str, object], top_n: int) -> str:
    lines = ["# Fund Letter Top Stock/ETF Recommendations", ""]

    lines.append("## Aggregate Top Ideas")
    lines.append("")
    lines.append("| Rank | Asset | Score | Mentions |")
    lines.append("|---:|---|---:|---:|")
    for idx, row in enumerate(result["aggregate"][:top_n], start=1):
        lines.append(f"| {idx} | {row['asset']} | {row['score']} | {row['mentions']} |")

    for file_result in result["files"]:
        lines.append("")
        lines.append(f"## {file_result['file']}")
        lines.append("")
        lines.append("| Rank | Asset | Score | Mentions |")
        lines.append("|---:|---|---:|---:|")
        for idx, row in enumerate(file_result["top"][:top_n], start=1):
            lines.append(f"| {idx} | {row['asset']} | {row['score']} | {row['mentions']} |")

    lines.append("")
    lines.append("_Heuristic extraction only; verify against source letters._")
    return "\n".join(lines)


def run(input_dir: Path, files: list[Path] | None, top_n: int) -> dict[str, object]:
    selected_files = resolve_files(input_dir, files)

    all_mentions: list[Mention] = []
    per_file_results = []

    for file_path in selected_files:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        mentions = extract_mentions(text)
        all_mentions.extend(mentions)

        ranked = rank_mentions(mentions)
        per_file_results.append(
            {
                "file": file_path.name,
                "top": ranked[:top_n],
                "mention_count": len(mentions),
            }
        )

    aggregate_ranked = rank_mentions(all_mentions)

    return {
        "input_dir": str(input_dir),
        "files_processed": len(selected_files),
        "aggregate": aggregate_ranked,
        "files": per_file_results,
    }


def print_console(result: dict[str, object], top_n: int) -> None:
    print("\nAggregate top ideas:\n")
    for idx, row in enumerate(result["aggregate"][:top_n], start=1):
        print(f"{idx:>2}. {row['asset']:<30} score={row['score']:<3} mentions={row['mentions']}")

    for file_result in result["files"]:
        print(f"\n{file_result['file']}")
        for idx, row in enumerate(file_result["top"][:top_n], start=1):
            print(f"  {idx:>2}. {row['asset']:<30} score={row['score']:<3} mentions={row['mentions']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract top stock/ETF recommendations from fund letter text files.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--files", type=Path, nargs="*", help="Optional explicit files to process")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.input_dir, args.files, args.top_n)

    print_console(result, args.top_n)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(format_markdown(result, args.top_n), encoding="utf-8")


if __name__ == "__main__":
    main()
