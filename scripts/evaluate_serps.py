#!/usr/bin/env python3
"""Compare captured SERPs with a manually reviewed domain baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta


def normalize_domain(value: str) -> str | None:
    """Extract a normalized hostname from a URL or Google redirect."""
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    query = parse_qs(parsed.query)
    for key in ("q", "url", "target"):
        for target in query.get(key, []):
            if urlparse(target).scheme.lower() not in {"http", "https"}:
                continue
            domain = normalize_domain(target)
            if domain:
                return domain
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or host in {"google.com", "google.co.uk", "google.ca"}:
        return None
    return host


def observed_domains(parsed: dict) -> set[str]:
    """Read hostnames from the organic-results group only."""
    domains: set[str] = set()
    for group, items in parsed.items():
        if group != "organic_results" or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ("url", "link"):
                domain = normalize_domain(str(item.get(field, "")))
                if domain:
                    domains.add(domain)
                    break
            else:
                fallback = item.get("displayed_url") or item.get("source_name")
                if fallback:
                    fallback = str(fallback).split("›", 1)[0].strip()
                domain = normalize_domain(str(fallback or ""))
                if domain:
                    domains.add(domain)
    return domains


def score_domains(baseline: set[str], observed: set[str]) -> dict:
    """Return overlap evidence and a deliberately limited screening flag."""
    if not baseline:
        raise ValueError("baseline must contain at least one reviewed domain")
    matched = baseline & observed
    ratio = len(matched) / len(baseline)
    return {
        "baseline_domains": len(baseline),
        "matched_domains": len(matched),
        "match_ratio": ratio,
        "candidate_flag": ratio < 0.5,
    }


def usual_domains(captures: list[dict], minimum_share: float = 0.6) -> set[str]:
    """Derive usual query domains from independently reviewed baseline captures."""
    if not 0 < minimum_share <= 1:
        raise ValueError("minimum_share must be > 0 and <= 1")
    successful = [
        record
        for record in captures
        if record.get("http_status") == 200
        and isinstance(record.get("parsed"), dict)
        and isinstance(record["parsed"].get("organic_results"), list)
        and record["parsed"]["organic_results"]
    ]
    if not successful:
        return set()
    frequency: dict[str, int] = {}
    for record in successful:
        for domain in observed_domains(record["parsed"]):
            frequency[domain] = frequency.get(domain, 0) + 1
    return {
        domain
        for domain, count in frequency.items()
        if count / len(successful) >= minimum_share
    }


def recovery_status(
    capture: dict,
    later_captures: list[dict],
    baseline: set[str],
    recovery_window_days: int = 3,
) -> str:
    """Classify observed recovery without treating missing follow-up as failure."""
    captured_at = datetime.fromisoformat(capture["collected_at"])
    deadline = captured_at + timedelta(days=recovery_window_days)
    query = capture.get("query")
    settings = capture.get("settings", {})
    followups = []
    for later in later_captures:
        if later.get("query") != query or later.get("http_status") != 200:
            continue
        later_settings = later.get("settings", {})
        if any(
            settings.get(key) != later_settings.get(key)
            for key in ("language", "country", "proxy_country", "route")
            if settings.get(key) is not None
        ):
            continue
        later_at = datetime.fromisoformat(later["collected_at"])
        if not captured_at < later_at:
            continue
        later_parsed = later.get("parsed")
        if not isinstance(later_parsed, dict):
            continue
        later_results = later_parsed.get("organic_results")
        if not isinstance(later_results, list) or not later_results:
            continue
        expected_count = later.get("settings", {}).get("result_count")
        if expected_count is not None and len(later_results) < int(expected_count):
            continue
        if not observed_domains(later_parsed):
            continue
        followups.append((later_at, later_parsed))
    for later_at, later_parsed in sorted(followups, key=lambda item: item[0]):
        if later_at <= deadline and len(observed_domains(later_parsed) & baseline) / len(baseline) >= 0.5:
            return "recovered_within_window"
    if not followups:
        return "no_valid_followup"
    if max(item[0] for item in followups) < deadline:
        return "window_still_open"
    return "not_recovered_within_window"


def evaluate_capture(
    record: dict,
    baseline: set[str],
    later_captures: list[dict] | None = None,
    recovery_window_days: int = 3,
) -> dict:
    """Score successful captures and keep failed or malformed captures unscorable."""
    parsed = record.get("parsed")
    if record.get("http_status") != 200 or not isinstance(parsed, dict):
        return {
            "query": record.get("query"),
            "evaluation_status": "unscorable",
            "reason": record.get("error", "capture has no successful parsed response"),
        }
    if "organic_results" not in parsed:
        return {
            "query": record.get("query"),
            "evaluation_status": "unscorable",
            "reason": "response did not include an organic_results group",
        }
    if not isinstance(parsed["organic_results"], list):
        return {
            "query": record.get("query"),
            "evaluation_status": "unscorable",
            "reason": "organic_results was not a list",
        }
    if not parsed["organic_results"]:
        return {
            "query": record.get("query"),
            "evaluation_status": "no_organic_results",
            "reason": "response explicitly contained an empty organic_results list",
        }
    observed = observed_domains(parsed)
    if not observed:
        return {
            "query": record.get("query"),
            "evaluation_status": "unscorable",
            "reason": "organic_results was present but no usable hostnames could be extracted",
        }
    result = score_domains(baseline, observed)
    result["query"] = record.get("query")
    requested_result_count = record.get("settings", {}).get("result_count")
    returned_result_count = len(parsed["organic_results"])
    result["requested_result_count"] = requested_result_count
    result["returned_result_count"] = returned_result_count
    result["result_count_matches_request"] = (
        requested_result_count is None
        or returned_result_count == int(requested_result_count)
    )
    result["round"] = record.get("settings", {}).get("round")
    result["route"] = record.get("settings", {}).get("route")
    if not result["result_count_matches_request"]:
        result["evaluation_status"] = "incomplete_anomaly_candidate"
    elif not result["candidate_flag"]:
        result["evaluation_status"] = "baseline_consistent"
    elif later_captures is None:
        result["evaluation_status"] = "anomaly_candidate_unconfirmed"
    else:
        recovery = recovery_status(record, later_captures, baseline, recovery_window_days)
        result["recovery_status"] = recovery
        result["evaluation_status"] = {
            "recovered_within_window": "recovered_anomaly_candidate",
            "no_valid_followup": "unresolved_no_followup",
            "window_still_open": "unresolved_window_open",
            "not_recovered_within_window": "anomaly_not_observed_to_recover",
        }[recovery]
    result["interpretation"] = (
        "project screening rule, not ground truth; inspect the captures and alternative explanations"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--recovery-window-days", type=int, default=3)
    args = parser.parse_args()
    if args.recovery_window_days < 1:
        parser.error("--recovery-window-days must be at least 1")

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.input.glob("*.json"))]
    for record in records:
        query_baseline = {
            normalize_domain(domain)
            for domain in baseline.get(record.get("query"), [])
        } - {None}
        if not query_baseline:
            print(f"{record.get('query')}: no reviewed baseline; skipped")
            continue
        result = evaluate_capture(
            record,
            query_baseline,
            later_captures=records,
            recovery_window_days=args.recovery_window_days,
        )
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
