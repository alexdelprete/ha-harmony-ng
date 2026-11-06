"""Fixtures for Harmony NG tests.

The `hass` fixture and the test helpers (`MockConfigEntry`, `load_fixture`, ...)
come from pytest-homeassistant, the test package Home Assistant core publishes
with every release. It loads as a pytest plugin and enables custom integrations
by default; add integration-specific fixtures here.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip the integration setup (async_setup_entry returns None since HA 2026.11)."""
    with patch(
        "custom_components.harmony_ng.async_setup_entry",
        return_value=None,
    ) as mock_setup:
        yield mock_setup
