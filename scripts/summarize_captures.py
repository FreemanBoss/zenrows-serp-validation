#!/usr/bin/env python3
"""Summarize all stored SERP attempts without dropping failures."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from scripts.evaluate_serps import observed_domains


def summarize(records: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        settings = record.get("settings", {})
        groups[(str(settings.get("round", "unspecified")), str(settings.get("route", "unspecified")))].append(record)

    summaries = []
    for (round_id, route), captures in sorted(groups.items()):
        http_200 = [item for item in captures if item.get("http_status") == 200]
        failed = [item for item in captures if item.get("http_status") != 200]
        parsed = [
            item for item in http_200
            if isinstance(item.get("parsed"), dict)
        ]
        unscorable = [
            item for item in http_200
            if not isinstance(item.get("parsed"), dict)
            or not isinstance(item["parsed"].get("organic_results"), list)
            or not item["parsed"]["organic_results"]
            or not observed_domains(item["parsed"])
        ]
        incomplete = [
            item for item in http_200
            if isinstance(item.get("parsed"), dict)
            and isinstance(item["parsed"].get("organic_results"), list)
            and item["parsed"]["organic_results"]
            and observed_domains(item["parsed"])
            and item.get("settings", {}).get("result_count") is not None
            and len(item["parsed"]["organic_results"])
            < int(item["settings"]["result_count"])
        ]
        complete = [item for item in parsed if item not in unscorable and item not in incomplete]
        credits = sum(
            int(item.get("response_headers", {}).get("X-Request-Credits", 0) or 0)
            for item in captures
        )
        elapsed = [float(item["elapsed_seconds"]) for item in captures if item.get("elapsed_seconds") is not None]
        summaries.append({
            "round": round_id,
            "route": route,
            "attempted": len(captures),
            "http_200": len(http_200),
            "parsed_response": len(parsed),
            "complete_organic_response": len(complete),
            "failed": len(failed),
            "unscorable": len(unscorable),
            "incomplete_result_count": len(incomplete),
            "credits_reported": credits,
            "elapsed_seconds": elapsed,
            "queries": [item.get("query") for item in captures],
        })
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.input.glob("*.json"))]
    print(json.dumps(summarize(records), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
