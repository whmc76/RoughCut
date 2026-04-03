from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
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


@pytest.mark.asyncio
async def test_collect_sample_report_counts_subject_brand_and_model_in_keyword_hits(monkeypatch):
    job_id = "00000000-0000-0000-0000-000000000124"
    sample = {
        "source_name": "flashlight.mp4",
        "source_path": "Y:/EDC系列/未剪辑视频/flashlight.mp4",
        "expected_product_family": "flashlight",
        "expected_keywords": ["OLIGHT", "SLIM2"],
    }
    artifact_payload = {
        "content_subject": "",
        "content_kind": "product_review",
        "subject_brand": "OLIGHT",
        "subject_model": "SLIM2 ULTRA",
        "subject_type": "SLIM2 ULTRA版手电筒",
        "video_theme": "手电筒版本选购比较",
        "content_understanding": {
            "observed_entities": [{"kind": "product", "name": "SLIM2 ULTRA版手电筒"}],
            "resolved_entities": [],
            "resolved_primary_subject": "",
            "conflicts": [],
            "capability_matrix": {"visual_understanding": {"mode": "native_multimodal"}},
            "needs_review": True,
            "review_reasons": ["品牌词来自身份归一化"],
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

    assert report.keyword_hits == ["OLIGHT", "SLIM2"]


@pytest.mark.asyncio
async def test_prepare_job_for_source_updates_reused_job_workflow_template(monkeypatch, tmp_path):
    source_path = tmp_path / "20260301-171443.mp4"
    source_path.write_bytes(b"fake")
    reused_job = SimpleNamespace(
        id=uuid.uuid4(),
        source_name=source_path.name,
        workflow_template=None,
        language="zh-CN",
        status="done",
        error_message="old",
        updated_at=datetime.now(timezone.utc),
    )
    steps = [
        SimpleNamespace(
            step_name="probe",
            status="done",
            error_message="old",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            metadata_={"old": True},
        ),
        SimpleNamespace(
            step_name="content_profile",
            status="failed",
            error_message="boom",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            metadata_={"old": True},
        ),
    ]

    class FakeScalarRows:
        def __init__(self, items):
            self._items = items

        def first(self):
            return self._items[0] if self._items else None

        def all(self):
            return list(self._items)

    class FakeExecuteResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return FakeScalarRows(self._items)

    class FakeSession:
        def __init__(self):
            self.calls = 0
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeExecuteResult([reused_job])
            if self.calls == 2:
                return FakeExecuteResult(steps)
            raise AssertionError(f"unexpected execute call {self.calls}")

        async def commit(self):
            self.committed = True

    fake_session = FakeSession()
    monkeypatch.setattr(benchmark_mod, "get_session_factory", lambda: (lambda: fake_session))

    job_id = await benchmark_mod.prepare_job_for_source(
        source_path,
        channel_profile="edc_tactical",
        language="zh-CN",
    )

    assert job_id == str(reused_job.id)
    assert reused_job.workflow_template == "edc_tactical"
    assert reused_job.language == "zh-CN"
    assert reused_job.status == "pending"
    assert reused_job.error_message is None
    assert fake_session.committed is True
    assert steps[0].status == "pending"
    assert steps[0].metadata_ is None
    assert steps[1].status == "pending"
    assert steps[1].error_message is None
