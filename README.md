# Poisoned SERP? How to Scrape Google Search Results Reliably

This project collects Google Search results through Zenrows Fetch and checks the returned payload before treating it as a usable SERP. It records each attempt and compares observed organic-result domains with a manually reviewed, query-specific baseline.

## Features

- Builds localized Google Search URLs from CSV query records.
- Sends requests through Zenrows Fetch with `mode=auto` and `extract=auto`.
- Saves timestamped JSON capture records, including request settings, status, timing, selected response headers, parsed content, and HTML when returned.
- Preserves API and transport failures as records instead of dropping failed attempts.
- Separates incomplete, unscorable, baseline-consistent, and anomaly-candidate outcomes.
- Checks for later same-query captures before marking an anomaly candidate as recovered.
- Summarizes attempts, failures, incomplete results, elapsed time, and reported credits by route and round.
- Includes offline tests for collection settings, domain scoring, recovery, and summary counts.

## Prerequisites

- Python 3.10 or later
- A Zenrows account and API key for live collection
- Network access to the Zenrows Fetch API

## Installation

1. Clone the repository.

```bash
git clone https://github.com/FreemanBoss/zenrows-serp-validation.git
cd zenrows-serp-validation
```

2. Create and activate a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Install the dependencies.

```bash
python -m pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and set `ZENROWS_API_KEY` to a key from your Zenrows account. The `.env` file is excluded from version control. Never put a live key in a script, query file, capture, or README.

```dotenv
ZENROWS_API_KEY=your_api_key
```

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
└── requirements.txt
```

`queries.csv` defines the queries and locale settings. `baseline.example.json` demonstrates the expected baseline shape; replace its example domains with manually reviewed domains before interpreting evaluation output. Captures are written to `data/raw/`.

## How it works

The workflow keeps transport status and payload quality as separate checks:

```text
queries.csv -> Zenrows Fetch -> timestamped capture JSON
                                  |
                                  v
              payload/count checks -> baseline comparison -> summary
```

The evaluator uses organic results only. A low domain overlap is a review signal, not proof that Google intentionally returned a poisoned SERP. Missing or empty result groups, API errors, and fewer results than requested remain distinct outcomes.

## Running the project

Preview the request plan without making network calls or spending credits:

```bash
python scripts/collect_serps.py --input queries.csv --dry-run
```

For an approved live test, first copy `.env.example` to `.env`, set the API key, and specify a credit ceiling. This example limits the run to one query and caps the worst-case estimate at 25 credits:

```bash
python scripts/collect_serps.py \
  --input queries.csv \
  --output data/raw \
  --limit 1 \
  --max-credit-budget 25
```

Evaluate captures against a manually reviewed baseline:

```bash
python scripts/evaluate_serps.py --input data/raw --baseline baseline.example.json
```

Summarize attempts, including failed and incomplete responses:

```bash
python scripts/summarize_captures.py --input data/raw
```

Run the offline regression suite:

```bash
python -m pytest -q
```

## Output

The collector writes one JSON file per attempt under `data/raw/`. A successful response may include parsed SERP groups and HTML; failures retain their status and error evidence. The evaluator and summarizer print JSON to standard output. Live output depends on the query, locale, collection time, API response, and extraction result; this repository does not promise a particular result count or success rate.

## Technologies

- Python
- Requests
- python-dotenv
- pytest
- Zenrows Fetch API

## Use cases

Use the workflow to inspect SERP payload quality and test conservative screening rules. It is not a statistically representative route benchmark, a ranking-change detector, or proof of intentional SERP poisoning.

## Data sources

The collector retrieves Google Search pages live. `queries.csv` is the sample input, and `baseline.example.json` contains illustrative domains only. Build and review a separate baseline for each query and locale before using evaluation results as evidence.

## Troubleshooting

- `ZENROWS_API_KEY is missing`: copy `.env.example` to `.env` and add a valid key, or export the variable in your shell.
- A non-200 response: inspect the saved error record and `X-Request-Id`, then check the Zenrows dashboard and documentation.
- An HTTP 200 with too few organic results: the collector records the requested and returned counts; do not treat the response as a complete SERP.
- No captures are summarized: confirm that `--input` points to the directory containing the JSON files.

## Related article

This repository accompanies the Zenrows article **“Poisoned SERP? How to Scrape Google Search Results Reliably.”** The article URL will be added here after Zenrows publishes it. The article should link back to this repository.
