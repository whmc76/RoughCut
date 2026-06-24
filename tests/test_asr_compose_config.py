from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_asr_matrix_compose_uses_workspace_relative_model_cache_defaults() -> None:
    content = (ROOT / "docker-compose.asr-matrix.yml").read_text(encoding="utf-8")

    assert "ASR_MATRIX_HF_CACHE:-./.model-cache/huggingface" in content
    assert "ASR_MATRIX_MODELSCOPE_CACHE:-./.model-cache/modelscope" in content
    assert "ASR_MATRIX_HF_CACHE:-C:/sample-workspace/RoughCut" not in content
    assert "ASR_MATRIX_MODELSCOPE_CACHE:-C:/sample-workspace/RoughCut" not in content


def test_qwen3_asr_compose_defaults_use_real_modelscope_cache_directories() -> None:
    content = (ROOT / "docker-compose.asr-matrix.yml").read_text(encoding="utf-8")

    assert "QWEN3_ASR_MODEL:-/models/modelscope/Qwen/Qwen3-ASR-1___7B" in content
    assert "QWEN3_ASR_ALIGNER:-/models/modelscope/Qwen/Qwen3-ForcedAligner-0___6B" in content
