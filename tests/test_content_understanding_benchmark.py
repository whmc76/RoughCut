from dataclasses import asdict

from scripts.run_content_understanding_benchmark import SampleRunReport, build_console_summary
from tests.fixtures.content_understanding_benchmark_samples import BENCHMARK_SAMPLES
from tests.fixtures.content_understanding_benchmark_samples import BENCHMARK_REPORT_CONTRACT_FIELDS


def test_benchmark_samples_cover_multiple_product_families():
    families = {sample["expected_product_family"] for sample in BENCHMARK_SAMPLES}

    assert len(families) >= 5
    assert {
        "bag",
        "flashlight",
        "knife",
        "knife_tool",
        "case",
    }.issubset(families)


def test_benchmark_samples_define_expected_keywords():
    for sample in BENCHMARK_SAMPLES:
        assert sample["expected_keywords"]


def test_benchmark_report_contract_includes_observed_resolved_conflicts_and_capability_matrix():
    report = SampleRunReport(
        source_name="demo.mp4",
        source_path="/tmp/demo.mp4",
        expected_product_family="bag",
        expected_keywords=["双肩包"],
        keyword_hits=["双肩包"],
        keyword_misses=[],
        job_id="job-123",
        status="done",
        transcript_segment_count=3,
        subtitle_count=2,
        content_subject="demo subject",
        content_kind="product_review",
        subject_type="bag",
        video_theme="demo theme",
        observed_entities=[{"kind": "product", "name": "demo"}],
        resolved_entities=[{"kind": "product", "name": "demo resolved"}],
        resolved_primary_subject="demo resolved",
        conflicts=["observed_vs_resolved_subject"],
        capability_matrix={"visual_understanding": {"mode": "native_multimodal"}},
        needs_review=False,
        review_reasons=[],
        elapsed_seconds=1.234,
    )

    console_report = build_console_summary(
        {
            "sample_count": 1,
            "success_count": 1,
            "failed_count": 0,
            "reports": [asdict(report)],
        }
    )["reports"][0]

    for field in BENCHMARK_REPORT_CONTRACT_FIELDS:
        assert field in console_report
    assert console_report["observed_entities"] == report.observed_entities
    assert console_report["resolved_entities"] == report.resolved_entities
    assert console_report["conflicts"] == report.conflicts
    assert console_report["capability_matrix"] == report.capability_matrix
