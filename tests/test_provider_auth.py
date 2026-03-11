from __future__ import annotations

import pytest

from roughcut.providers.auth import resolve_credential


def test_resolve_credential_with_api_key():
    value = resolve_credential(
        mode="api_key",
        direct_value="sk-test",
        helper_command="",
        provider_name="OpenAI",
    )
    assert value == "sk-test"


def test_resolve_credential_with_helper_command():
    value = resolve_credential(
        mode="codex_compat",
        direct_value="",
        helper_command="python -c \"print('token-from-helper')\"",
        provider_name="OpenAI",
    )
    assert value == "token-from-helper"


def test_resolve_credential_raises_on_missing_value():
    with pytest.raises(ValueError):
        resolve_credential(
            mode="claude_code_compat",
            direct_value="",
            helper_command="",
            provider_name="Anthropic",
        )
