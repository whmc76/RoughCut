from __future__ import annotations

import pytest

from roughcut.host import publication_browser


def test_open_publication_entry_url_uses_bound_chromium_profile(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(publication_browser, "_find_chromium_executable", lambda browser: "chrome.exe")
    monkeypatch.setattr(
        publication_browser,
        "_spawn_chromium_profile_window",
        lambda **kwargs: calls.append(kwargs),
    )

    result = publication_browser.open_publication_entry_url(
        "https://member.example.com/upload",
        browser_binding={
            "browser": "chrome",
            "user_data_dir": "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            "profile_directory": "Profile 2",
            "profile_id": "browser-profile:chrome:demo",
        },
    )

    assert result["used_binding"] is True
    assert result["mode"] == "browser_profile"
    assert calls == [
        {
            "executable": "chrome.exe",
            "user_data_dir": "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            "profile_directory": "Profile 2",
            "url": "https://member.example.com/upload",
        }
    ]


def test_open_publication_entry_url_falls_back_without_profile_binding(monkeypatch: pytest.MonkeyPatch):
    opened: list[str] = []
    monkeypatch.setattr(publication_browser, "_open_with_default_browser", opened.append)

    result = publication_browser.open_publication_entry_url(
        "https://member.example.com/upload",
        browser_binding={"browser": "chrome", "profile_id": "browser-agent:chrome:creator:bilibili"},
    )

    assert result["used_binding"] is False
    assert result["mode"] == "default_browser"
    assert opened == ["https://member.example.com/upload"]


def test_open_publication_entry_url_delegates_to_host_bridge_inside_container(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_bridge(url: str, *, browser_binding: dict[str, object]) -> dict[str, object]:
        captured["url"] = url
        captured["browser_binding"] = browser_binding
        return {
            "opened": True,
            "url": url,
            "used_binding": True,
            "mode": "browser_profile",
            "launch_source": "codex_host_bridge",
        }

    monkeypatch.setattr(publication_browser, "_should_delegate_to_host_bridge", lambda: True)
    monkeypatch.setattr(publication_browser, "_open_publication_entry_via_host_bridge", fake_bridge)

    result = publication_browser.open_publication_entry_url(
        "https://member.example.com/upload",
        browser_binding={
            "browser": "chrome",
            "user_data_dir": "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            "profile_directory": "Profile 2",
        },
    )

    assert result["launch_source"] == "codex_host_bridge"
    assert captured == {
        "url": "https://member.example.com/upload",
        "browser_binding": {
            "browser": "chrome",
            "user_data_dir": "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            "profile_directory": "Profile 2",
        },
    }


def test_open_publication_entry_url_rejects_non_http_urls():
    with pytest.raises(ValueError):
        publication_browser.open_publication_entry_url("file:///C:/Windows/System32/calc.exe")
