"""Tests for the Harmony NG config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.harmony_ng.const import DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    """The user step shows a form and creates an entry from the input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.1"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "192.0.2.1"
    assert result["data"] == {"host": "192.0.2.1"}
    assert len(mock_setup_entry.mock_calls) == 1
