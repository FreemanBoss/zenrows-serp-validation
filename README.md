# ZenRows SERP validation project

This repository contains a conservative, evidence-first workflow for collecting Google Search results through ZenRows Fetch and checking whether the returned organic results are complete enough to trust. The project is intentionally narrow in scope: it records what was requested, what was returned, and what still requires human review.

The code does not treat an HTTP 200 as proof of a valid SERP. It records failures, preserves incomplete responses, and compares the observed organic domains against a manually reviewed baseline before calling a capture an anomaly candidate.

## What the project does

- Builds localized Google Search URLs from a CSV input.
- Sends requests to the ZenRows Fetch API with `mode=auto` and `extract=auto`.
- Stores each capture as a JSON record with query settings, status, timing, response headers, parsed content, and raw HTML where available.
- Keeps failed and incomplete captures in the dataset instead of silently dropping them.
- Evaluates the observed organic domains against a baseline of reviewed domains.
- Flags recovery only when a later same-query capture exists within the configured window.
- Includes offline regression tests to protect the evaluation logic.

## Project structure

```text
.
├── data/
│   └── raw/
│       └── .gitkeep
├── scripts/
│   ├── collect_serps.py
│   ├── evaluate_serps.py
│   └── summarize_captures.py
├── tests/
│   └── test_evaluate_serps.py
├── .env.example
├── .gitignore
├── baseline.example.json
├── queries.csv
├── README.md
├── requirements.txt
└── .zenrows/
```

## Prerequisites

- Python 3.10 or later
- A ZenRows API key
- Network access to the ZenRows API

## Installation

1. Create and activate a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install the project dependencies.

```bash
pip install -r requirements.txt
```

3. Add a local environment variable or `.env` file with the ZenRows key.

```dotenv
ZENROWS_API_KEY=your_api_key
```

## Running the collector

Preview a planned run without making requests:

```bash
python scripts/collect_serps.py --input queries.csv --dry-run
```

Run a small, approved collection with a conservative credit cap:

```bash
python scripts/collect_serps.py \
  --input queries.csv \
  --output data/raw \
  --limit 1 \
  --max-credit-budget 25
```

The collector requires a positive `--max-credit-budget` value in live mode. The default budget check assumes the highest documented Fetch cost of 25 credits per request.

## Evaluating a capture

Create a manually reviewed baseline for the same query and locale. The file should be a JSON object keyed by query and containing normalized hostnames.

```json
{
  "best running shoes": ["example.com", "example.org"],
  "weather forecast london": ["metoffice.gov.uk", "weather.com"]
}
```

Then evaluate the collected captures:

```bash
python scripts/evaluate_serps.py --input data/raw --baseline baseline.json
```

The summary script keeps failed and incomplete captures visible in the totals:

```bash
python scripts/summarize_captures.py --input data/raw
```

## Method and guardrails

- Keep the Google URL localization aligned with the request country and language.
- Preserve raw HTML and request metadata when retention is allowed.
- Record the requested result count and the returned result count separately.
- Treat a low overlap score as an anomaly candidate, not as proof of poisoning.
- Require a valid later observation before labeling a candidate as recovered.
- Keep failures, empty organic sets, and malformed captures distinct from complete results.

## Tests

Run the offline regression suite without API credentials:

```bash
pytest
```

The project includes a small set of fixtures that cover parsing, recovery, incomplete responses, and failure counting.

## Related notes

- `research-notes.md`: the initial three-query smoke test and its limits
- `test-protocol.md`: a protocol for larger route comparisons and publication gating

The project is intended for a careful, evidence-based analysis of SERP quality and not for publishing route-comparison claims without a fixed comparison protocol and manual review process.
