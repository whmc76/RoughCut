from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
import uuid

import pytest

import scripts.run_content_understanding_benchmark as benchmark_mod
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


@pytest.mark.asyncio
async def test_collect_sample_report_reads_conflicts_from_persisted_content_understanding(monkeypatch):
    job_id = "00000000-0000-0000-0000-000000000123"
    sample = {
        "source_name": "demo.mp4",
        "source_path": "Y:/EDC系列/未剪辑视频/demo.mp4",
        "expected_product_family": "bag",
        "expected_keywords": ["游刃", "BOLTBOAT"],
    }
    artifact_payload = {
        "content_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
        "content_kind": "product_review",
        "subject_type": "HSJUN × BOLTBOAT 游刃机能双肩包",
        "video_theme": "联名机能双肩包对比评测",
        "content_understanding": {
            "observed_entities": [{"kind": "product", "name": "船长联名包"}],
            "resolved_entities": [{"kind": "product", "name": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
            "resolved_primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
            "conflicts": ["primary_subject", "subject_entities"],
            "capability_matrix": {"visual_understanding": {"mode": "native_multimodal"}},
            "needs_review": True,
            "review_reasons": ["原始称呼与归一化实体存在差异"],
        },
    }

    class FakeScalarRows:
        def __init__(self, items):
            self._items = items

        def all(self):
            return list(self._items)

        def first(self):
            return self._items[0] if self._items else None

    class FakeExecuteResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return FakeScalarRows(self._items)

    class FakeSession:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, model, key):
            assert str(key) == job_id
            return SimpleNamespace(id=uuid.UUID(job_id), status="done")

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeExecuteResult([SimpleNamespace(id=1), SimpleNamespace(id=2)])
            if self.calls == 2:
                return FakeExecuteResult([SimpleNamespace(id=1)])
            if self.calls == 3:
                return FakeExecuteResult([SimpleNamespace(data_json=artifact_payload)])
            raise AssertionError(f"unexpected execute call {self.calls}")

    monkeypatch.setattr(benchmark_mod, "get_session_factory", lambda: (lambda: FakeSession()))

    report = await benchmark_mod.collect_sample_report(job_id, sample, 1.234)

    assert report.keyword_hits == ["游刃", "BOLTBOAT"]
    assert report.observed_entities == [{"kind": "product", "name": "船长联名包"}]
    assert report.resolved_entities == [{"kind": "product", "name": "HSJUN × BOLTBOAT 游刃机能双肩包"}]
    assert report.resolved_primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert report.conflicts == ["primary_subject", "subject_entities"]
    assert report.capability_matrix == {"visual_understanding": {"mode": "native_multimodal"}}
