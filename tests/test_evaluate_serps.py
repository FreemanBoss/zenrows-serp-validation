from scripts.collect_serps import build_google_url, fetch_serp, redact_secret
from scripts.summarize_captures import summarize
from datetime import datetime, timedelta, timezone

from scripts.evaluate_serps import (
    evaluate_capture,
    normalize_domain,
    observed_domains,
    recovery_status,
    score_domains,
    usual_domains,
)


def test_normalize_domain_handles_google_redirect():
    assert normalize_domain("https://www.google.com/url?q=https%3A%2F%2Fexample.org%2Fpage") == "example.org"


def test_observed_domains_reads_result_groups():
    parsed = {
        "organic_results": [
            {"url": "https://www.example.com/article"},
            {"url": "https://news.example.net/story"},
        ],
        "related_questions": [{"url": "https://not-a-result.example/question"}],
    }
    assert observed_domains(parsed) == {"example.com", "news.example.net"}


def test_observed_domains_ignores_non_organic_blocks():
    parsed = {
        "video_results": [{"url": "https://video.example/watch"}],
        "related_questions": [{"url": "https://question.example/ask"}],
    }
    assert observed_domains(parsed) == set()


def test_observed_domains_uses_displayed_url_when_redirect_is_opaque():
    parsed = {
        "organic_results": [
            {
                "url": "/goto?url=opaque-google-redirect",
                "displayed_url": "https://example.org › article",
            }
        ]
    }
    assert observed_domains(parsed) == {"example.org"}


def test_score_domains_flags_below_half_but_preserves_evidence():
    result = score_domains(
        {"one.example", "two.example", "three.example", "four.example"},
        {"one.example"},
    )
    assert result["matched_domains"] == 1
    assert result["match_ratio"] == 0.25
    assert result["candidate_flag"] is True


def test_score_domains_does_not_flag_half_or_more():
    result = score_domains({"one.example", "two.example"}, {"one.example"})
    assert result["candidate_flag"] is False


def test_score_domains_rejects_empty_baseline():
    try:
        score_domains(set(), {"one.example"})
    except ValueError as error:
        assert "baseline" in str(error)
    else:
        raise AssertionError("empty baseline should be rejected")


def test_build_google_url_encodes_search_and_localization():
    url = build_google_url("coffee grinder reviews", "en", "us", 10)
    assert url == "https://www.google.com/search?q=coffee+grinder+reviews&hl=en&gl=us&num=10"


def test_fetch_serp_uses_documented_settings_and_keeps_evidence():
    class FakeResponse:
        status_code = 200
        headers = {"X-Request-Id": "req-test", "X-Request-Cost": "1"}
        elapsed = type("Elapsed", (), {"total_seconds": lambda self: 0.25})()
        ok = True
        text = ""

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"parsed": {"organic_results": [{"title": "Example"}]}, "html": "<html/>"}

    class FakeSession:
        seen_url = None
        seen_params = None
        seen_timeout = None

        def get(self, url, *, params, timeout):
            self.seen_url = url
            self.seen_params = params
            self.seen_timeout = timeout
            return FakeResponse()

    session = FakeSession()
    row = {
        "query": "example query",
        "language": "en",
        "country": "us",
        "proxy_country": "us",
        "result_count": "10",
    }
    result = fetch_serp(row, "secret-for-test", session)

    assert session.seen_url == "https://api.zenrows.com/v1/"
    assert session.seen_params["mode"] == "auto"
    assert session.seen_params["proxy_country"] == "us"
    assert session.seen_params["extract"] == "auto"
    assert session.seen_params["apikey"] == "secret-for-test"
    assert session.seen_timeout == 180
    assert result["parsed"]["organic_results"][0]["title"] == "Example"
    assert result["response_headers"]["X-Request-Id"] == "req-test"
    assert result["elapsed_seconds"] == 0.25
    assert "device" not in result["settings"]


def test_failed_capture_is_unscorable_not_flagged():
    result = evaluate_capture(
        {"query": "example query", "http_status": 429, "error": "throttled"},
        {"one.example", "two.example"},
    )
    assert result["evaluation_status"] == "unscorable"
    assert "candidate_flag" not in result


def test_missing_organic_group_is_unscorable():
    result = evaluate_capture(
        {"query": "example query", "http_status": 200, "parsed": {"people_also_ask": []}},
        {"one.example"},
    )
    assert result["evaluation_status"] == "unscorable"


def test_empty_organic_group_is_not_a_poisoning_flag():
    result = evaluate_capture(
        {"query": "example query", "http_status": 200, "parsed": {"organic_results": []}},
        {"one.example"},
    )
    assert result["evaluation_status"] == "no_organic_results"
    assert "candidate_flag" not in result


def test_incomplete_result_count_is_not_scored_as_confirmed_anomaly():
    record = {
        "query": "example query",
        "http_status": 200,
        "settings": {"result_count": 10},
        "parsed": {"organic_results": [{"url": "https://other.example/"}]},
    }
    result = evaluate_capture(record, {"expected.example", "also-expected.example"})
    assert result["evaluation_status"] == "incomplete_anomaly_candidate"
    assert result["candidate_flag"] is True


def test_unparseable_organic_results_are_unscorable():
    record = {
        "query": "example query",
        "http_status": 200,
        "parsed": {"organic_results": [{"title": "No URL or source"}]},
    }
    result = evaluate_capture(record, {"expected.example"})
    assert result["evaluation_status"] == "unscorable"
    assert "candidate_flag" not in result


def test_error_redaction_hides_api_key():
    assert redact_secret("request failed for key secret-value", "secret-value") == (
        "request failed for key [REDACTED]"
    )


def make_capture(query, collected_at, domains, status=200):
    return {
        "query": query,
        "collected_at": collected_at.isoformat(),
        "http_status": status,
        "parsed": {
            "organic_results": [{"url": f"https://{domain}/"} for domain in domains]
        }
        if status == 200
        else None,
    }


def test_usual_domains_uses_share_of_successful_baseline_captures():
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    captures = [
        make_capture("q", base + timedelta(hours=i), ["a.example", "b.example"])
        for i in range(5)
    ]
    captures.append(make_capture("q", base + timedelta(hours=6), [], status=422))
    assert usual_domains(captures, minimum_share=0.6) == {"a.example", "b.example"}


def test_recovery_requires_same_query_and_comparable_settings():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    anomalous = make_capture("q", start, ["other.example"])
    anomalous["settings"] = {
        "language": "en", "country": "us", "proxy_country": "us", "route": "fetch"
    }
    later = [
        make_capture("different", start + timedelta(hours=1), ["a.example", "b.example"]),
        make_capture("q", start + timedelta(days=2), ["a.example", "b.example"]),
    ]
    later[1]["settings"] = {
        "language": "en", "country": "us", "proxy_country": "us", "route": "fetch"
    }
    assert recovery_status(anomalous, later, {"a.example", "b.example"}) == "recovered_within_window"


def test_no_followup_is_unresolved_not_no_recovery():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    anomalous = make_capture("q", start, ["other.example"])
    assert recovery_status(anomalous, [anomalous], {"a.example", "b.example"}) == "no_valid_followup"


def test_followup_after_window_does_not_count_as_recovery():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    anomalous = make_capture("q", start, ["other.example"])
    later = [make_capture("q", start + timedelta(days=4), ["a.example", "b.example"])]
    assert recovery_status(anomalous, later, {"a.example", "b.example"}) == "not_recovered_within_window"


def test_window_is_open_without_enough_followup_time():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    anomalous = make_capture("q", start, ["other.example"])
    later = [make_capture("q", start + timedelta(days=1), ["other.example"])]
    assert recovery_status(anomalous, later, {"a.example", "b.example"}) == "window_still_open"


def test_summarize_keeps_failures_and_incomplete_successes():
    records = [
        {
            "query": "q1",
            "http_status": 200,
            "elapsed_seconds": 4,
            "settings": {"round": "r1", "route": "zenrows_fetch", "result_count": 10},
            "parsed": {"organic_results": [{"url": "https://a.example"}]},
            "response_headers": {"X-Request-Credits": "25"},
        },
        {
            "query": "q2",
            "http_status": 422,
            "elapsed_seconds": 2,
            "settings": {"round": "r1", "route": "zenrows_fetch", "result_count": 10},
            "response_headers": {"X-Request-Credits": "0"},
        },
    ]
    result = summarize(records)[0]
    assert result["attempted"] == 2
    assert result["failed"] == 1
    assert result["incomplete_result_count"] == 1
    assert result["credits_reported"] == 25
