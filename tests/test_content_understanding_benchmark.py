from tests.fixtures.content_understanding_benchmark_samples import BENCHMARK_SAMPLES


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
