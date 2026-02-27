#!/usr/bin/env python3
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

API_URL = "https://whalewisdom.com/shell/command.json"


def signed_request(shared_key: str, secret_key: str, payload: dict) -> requests.Response:
    args_json = json.dumps(payload, separators=(",", ":"))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = f"{args_json}\n{timestamp}".encode("utf-8")
    digest = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha1).digest()
    api_sig = base64.b64encode(digest).decode("ascii")
    return requests.get(
        API_URL,
        params={
            "args": args_json,
            "api_shared_key": shared_key,
            "api_sig": api_sig,
            "timestamp": timestamp,
        },
        timeout=30,
    )


def parse_response_body(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return response.text


def classify_access(response: requests.Response, body) -> str:
    if response.status_code == 401:
        return "auth_failed"
    if not response.ok:
        return "error"

    error_text = ""
    if isinstance(body, dict) and body.get("errors"):
        if isinstance(body["errors"], list):
            error_text = " ".join(str(e) for e in body["errors"])
        else:
            error_text = str(body["errors"])
    elif isinstance(body, str):
        error_text = body

    lowered = error_text.lower()
    if lowered:
        if "subscription limit has been reached" in lowered:
            return "subscription_required"
        if "subscription required" in lowered:
            return "subscription_required"
        if "no subscription found" in lowered:
            return "subscription_required"

    if response.ok and body is not None and str(body).strip() not in {"", "null"}:
        return "available"
    if response.ok:
        return "unknown"
    return "error"


def summarize_body(body) -> str:
    if body is None:
        return "null"
    if isinstance(body, dict):
        if body.get("errors"):
            if isinstance(body["errors"], list):
                return "; ".join(str(e) for e in body["errors"][:2])
            return str(body["errors"])
        keys = list(body.keys())
        if not keys:
            return "{}"
        return "json keys: " + ", ".join(str(k) for k in keys[:5])
    if isinstance(body, list):
        return f"json list ({len(body)} items)"

    one_line = str(body).strip().replace("\n", " ")
    return one_line[:220]


def list_free_capabilities(shared_key: str, secret_key: str) -> int:
    results = []
    available_quarter_ids = []
    available_quarter_periods = []

    quarter_payload = {"command": "quarters"}
    quarter_response = signed_request(shared_key, secret_key, quarter_payload)
    quarter_body = parse_response_body(quarter_response)
    quarter_access = classify_access(quarter_response, quarter_body)
    quarter_detail = summarize_body(quarter_body)

    if isinstance(quarter_body, dict) and isinstance(quarter_body.get("quarters"), list):
        available_quarters = [
            q
            for q in quarter_body["quarters"]
            if str(q.get("status", "")).lower().startswith("available")
        ]
        available_quarter_ids = [q.get("id") for q in available_quarters if isinstance(q.get("id"), int)]
        available_quarter_periods = [q.get("filing_period") for q in available_quarters if q.get("filing_period")]
        quarter_detail = f"{len(available_quarters)} available quarters"

    results.append(
        {
            "command": "quarters",
            "access": quarter_access,
            "http_status": quarter_response.status_code,
            "detail": quarter_detail,
        }
    )

    if len(available_quarter_ids) >= 2:
        q1id = available_quarter_ids[-2]
        q2id = available_quarter_ids[-1]
    else:
        q1id, q2id = 98, 99

    probe_payloads = [
        {"command": "stock_lookup", "symbol": "AAPL"},
        {"command": "filer_lookup", "name": "berkshire"},
        {"command": "stock_comparison", "stockid": 195, "q1id": q1id, "q2id": q2id},
        {"command": "holdings_comparison", "filerid": 349, "q1id": q1id, "q2id": q2id},
        {"command": "holdings", "filer_ids": [349], "limit": 1},
        {"command": "holders", "stock_ids": [195], "limit": 1},
        {"command": "filer_metadata", "id": 349},
    ]

    for payload in probe_payloads:
        try:
            response = signed_request(shared_key, secret_key, payload)
        except requests.RequestException as exc:
            results.append(
                {
                    "command": payload["command"],
                    "access": "error",
                    "http_status": None,
                    "detail": f"request failed: {exc}",
                }
            )
            continue

        body = parse_response_body(response)
        results.append(
            {
                "command": payload["command"],
                "access": classify_access(response, body),
                "http_status": response.status_code,
                "detail": summarize_body(body),
            }
        )

    report = {
        "probe_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rate_limit_per_minute": 20,
        "used_quarter_ids_for_comparisons": [q1id, q2id],
        "available_quarter_ids": available_quarter_ids,
        "available_quarter_periods": available_quarter_periods,
        "results": results,
        "notes": [
            "Best-effort probe based on sample inputs and current account permissions.",
            "Some commands may require additional valid parameters for full validation.",
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    load_dotenv()

    shared_key = os.getenv("WHALEWISDOM_API_KEY") or os.getenv("WHALE_WISDOM_SHARED_ACCESS_KEY")
    secret_key = os.getenv("WHALEWISDOM_API_SECRET") or os.getenv("WHALE_WISDOM_SECRET_ACCESS_KEY")
    if not shared_key or not secret_key:
        print(
            "Missing API credentials in .env. Supported names: "
            "WHALEWISDOM_API_KEY/WHALEWISDOM_API_SECRET or "
            "WHALE_WISDOM_SHARED_ACCESS_KEY/WHALE_WISDOM_SECRET_ACCESS_KEY",
            file=sys.stderr,
        )
        return 1

    parser = argparse.ArgumentParser(description="Small WhaleWisdom API client")
    parser.add_argument("--command", default="quarters", help="WhaleWisdom command name")
    parser.add_argument(
        "--list-free-capabilities",
        action="store_true",
        help="Run a best-effort access probe across common commands",
    )
    parser.add_argument(
        "--params",
        default="{}",
        help='JSON object of command params, e.g. \'{"symbol":"AAPL"}\'',
    )
    args = parser.parse_args()

    if args.list_free_capabilities:
        return list_free_capabilities(shared_key, secret_key)

    try:
        command_params = json.loads(args.params)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON passed to --params: {exc}", file=sys.stderr)
        return 1

    if not isinstance(command_params, dict):
        print("--params must be a JSON object", file=sys.stderr)
        return 1

    payload = {"command": args.command}
    payload.update(command_params)

    try:
        response = signed_request(shared_key, secret_key, payload)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    if not response.ok:
        print(f"HTTP {response.status_code}: {response.text}", file=sys.stderr)
        return 1

    data = parse_response_body(response)
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
