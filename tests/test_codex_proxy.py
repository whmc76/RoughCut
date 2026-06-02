from __future__ import annotations

from roughcut.host import codex_proxy


def test_codex_proxy_url_normalizes_host_docker_internal_to_localhost_on_windows_runtime(monkeypatch) -> None:
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "http://host.docker.internal:38695/v1/codex/exec")
    monkeypatch.setattr(codex_proxy.os, "name", "nt")

    assert codex_proxy.resolve_codex_proxy_url() == "http://127.0.0.1:38695/v1/codex/exec"
    assert codex_proxy.resolve_codex_proxy_sibling_url("/v1/host/complete-codex-imagegen") == "http://127.0.0.1:38695/v1/host/complete-codex-imagegen"
