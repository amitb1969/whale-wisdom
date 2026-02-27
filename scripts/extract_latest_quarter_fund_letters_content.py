#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


WORKDIR = Path.cwd()
INPUT_PATH = WORKDIR / "output/playwright/fund-letters/latest-quarter-fund-letters.json"
OUTPUT_DIR = WORKDIR / "output/playwright/fund-letters/latest-quarter-content"
TEXT_DIR = OUTPUT_DIR / "text"
RAW_DIR = OUTPUT_DIR / "raw"
CONSOLIDATED_JSON = OUTPUT_DIR / "latest-quarter-fund-letters-with-content.json"
SUMMARY_CSV = OUTPUT_DIR / "latest-quarter-fund-letters-content-summary.csv"
ISSUES_JSON = OUTPUT_DIR / "latest-quarter-fund-letters-content-issues.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

HTML_SELECTORS = [
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".newsletter-content",
    "#content",
    ".content",
]


@dataclass
class FetchResult:
    response: requests.Response | None
    error: str | None


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "letter"


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def load_letters() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    letters = payload.get("letters", [])
    return payload, letters


def normalize_drive_url(url: str) -> str:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return url

    path_match = re.search(r"/file/d/([^/]+)", parsed.path)
    if path_match:
        file_id = path_match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    query_id = parse_qs(parsed.query).get("id", [None])[0]
    if query_id:
        return f"https://drive.google.com/uc?export=download&id={query_id}"

    return url


def fetch_with_retries(session: requests.Session, url: str, retries: int = 3) -> FetchResult:
    backoff = 1.5
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=60, allow_redirects=True)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(backoff * attempt)
                continue
            return FetchResult(response=response, error=None)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    return FetchResult(response=None, error=last_error or "Unknown fetch error")


def looks_like_pdf(response: requests.Response, source_url: str) -> bool:
    ctype = response.headers.get("content-type", "").lower()
    if "application/pdf" in ctype:
        return True
    if source_url.lower().endswith(".pdf"):
        return True
    if response.content[:5] == b"%PDF-":
        return True
    return False


def extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return clean_text("\n\n".join(pages))


def extract_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form", "aside"]):
        node.decompose()

    candidates: list[str] = []
    for selector in HTML_SELECTORS:
        for node in soup.select(selector):
            text = node.get_text("\n", strip=True)
            if text:
                candidates.append(text)

    if candidates:
        best = max(candidates, key=len)
        if len(best) >= 800:
            return clean_text(best)

    body = soup.body.get_text("\n", strip=True) if soup.body else soup.get_text("\n", strip=True)
    return clean_text(body)


def clean_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def save_raw(raw_path: Path, content: bytes) -> None:
    with raw_path.open("wb") as f:
        f.write(content)


def save_text(text_path: Path, text: str) -> None:
    with text_path.open("w", encoding="utf-8") as f:
        f.write(text)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def main() -> None:
    ensure_dirs()
    metadata, letters = load_letters()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})

    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    total = len(letters)
    for idx, letter in enumerate(letters, start=1):
        title = str(letter.get("title", f"letter-{idx}"))
        original_url = str(letter.get("link", "")).strip()
        resolved_url = normalize_drive_url(original_url)
        slug = f"{idx:03d}-{slugify(title)}"

        print(f"[{idx}/{total}] Fetching {title}")

        if not resolved_url:
            issue = {
                "title": title,
                "url": original_url,
                "status": "missing_url",
                "error": "No URL provided",
            }
            issues.append(issue)
            results.append({**letter, **issue, "full_text": ""})
            continue

        fetched = fetch_with_retries(session, resolved_url)
        if fetched.response is None:
            issue = {
                "title": title,
                "url": original_url,
                "resolvedUrl": resolved_url,
                "status": "fetch_failed",
                "error": fetched.error,
            }
            issues.append(issue)
            results.append({**letter, **issue, "full_text": ""})
            continue

        response = fetched.response
        ctype = response.headers.get("content-type", "")
        status = response.status_code

        result: dict[str, Any] = {
            **letter,
            "url": original_url,
            "resolvedUrl": resolved_url,
            "finalUrl": response.url,
            "httpStatus": status,
            "contentType": ctype,
            "status": "ok",
            "extractionType": "",
            "wordCount": 0,
            "rawPath": "",
            "textPath": "",
            "full_text": "",
            "error": "",
        }

        if status >= 400:
            result["status"] = "http_error"
            result["error"] = f"HTTP {status}"
            issues.append(
                {
                    "title": title,
                    "url": original_url,
                    "resolvedUrl": resolved_url,
                    "finalUrl": response.url,
                    "status": "http_error",
                    "error": result["error"],
                }
            )
            results.append(result)
            continue

        try:
            if looks_like_pdf(response, response.url):
                raw_path = RAW_DIR / f"{slug}.pdf"
                save_raw(raw_path, response.content)
                text = extract_pdf_text(response.content)
                result["extractionType"] = "pdf"
                result["rawPath"] = str(raw_path.relative_to(WORKDIR))
            else:
                raw_path = RAW_DIR / f"{slug}.html"
                html = response.text
                save_raw(raw_path, html.encode("utf-8", errors="ignore"))
                text = extract_html_text(html)
                result["extractionType"] = "html"
                result["rawPath"] = str(raw_path.relative_to(WORKDIR))

            text_path = TEXT_DIR / f"{slug}.txt"
            save_text(text_path, text)

            result["textPath"] = str(text_path.relative_to(WORKDIR))
            result["wordCount"] = word_count(text)
            result["full_text"] = text

            if result["wordCount"] < 100:
                result["status"] = "thin_content"
                result["error"] = "Extracted text appears too short"
                issues.append(
                    {
                        "title": title,
                        "url": original_url,
                        "resolvedUrl": resolved_url,
                        "finalUrl": response.url,
                        "status": "thin_content",
                        "error": result["error"],
                        "wordCount": result["wordCount"],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            result["status"] = "extract_failed"
            result["error"] = str(exc)
            issues.append(
                {
                    "title": title,
                    "url": original_url,
                    "resolvedUrl": resolved_url,
                    "finalUrl": response.url,
                    "status": "extract_failed",
                    "error": str(exc),
                }
            )

        results.append(result)
        time.sleep(0.4)

    output_payload = {
        "source": str(INPUT_PATH.relative_to(WORKDIR)),
        "latestQuarter": metadata.get("latestQuarter"),
        "latestQuarterLetterCount": metadata.get("latestQuarterLetterCount"),
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "letters": results,
    }

    with CONSOLIDATED_JSON.open("w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "year",
                "quarter",
                "date",
                "cik",
                "url",
                "finalUrl",
                "httpStatus",
                "contentType",
                "extractionType",
                "wordCount",
                "status",
                "error",
                "textPath",
                "rawPath",
            ],
        )
        writer.writeheader()
        for item in results:
            writer.writerow({k: item.get(k, "") for k in writer.fieldnames})

    with ISSUES_JSON.open("w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)

    ok_count = sum(1 for x in results if x.get("status") == "ok")
    thin_count = sum(1 for x in results if x.get("status") == "thin_content")
    fail_count = len(results) - ok_count - thin_count
    print(
        json.dumps(
            {
                "outputJson": str(CONSOLIDATED_JSON.relative_to(WORKDIR)),
                "summaryCsv": str(SUMMARY_CSV.relative_to(WORKDIR)),
                "issuesJson": str(ISSUES_JSON.relative_to(WORKDIR)),
                "ok": ok_count,
                "thin_content": thin_count,
                "failed": fail_count,
                "total": len(results),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
