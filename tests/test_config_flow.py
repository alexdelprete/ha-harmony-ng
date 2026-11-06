"""Tests for the config, reauth, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import Generator
from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.harmony_ng.const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    CONF_TOKEN,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_API,
    ZEROCONF_TYPE,
)
from custom_components.harmony_ng.pyharmonyng import (
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    HubStatus,
)
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import HOST, HUB_ID
from .pyharmonyng.conftest import load_json

TOKEN = "pat_secret"  # noqa: S105


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Replace the REST client used by the flow's probe."""
    status = HubStatus.from_json(load_json("status"))
    with patch("custom_components.harmony_ng.config_flow.HarmonyNgClient") as client_class:
        instance = MagicMock()
        instance.get_status = AsyncMock(return_value=status)
        client_class.return_value = instance
        yield instance.get_status


def zeroconf_info(**properties: str) -> ZeroconfServiceInfo:
    props = {"id": HUB_ID, "api": "2", "auth": "0", "name": "Living Room Hub", **properties}
    return ZeroconfServiceInfo(
        ip_address=ip_address(HOST),
        ip_addresses=[ip_address(HOST)],
        port=8089,
        hostname="harmony-ng-20140101120000-000001.local.",
        type=ZEROCONF_TYPE,
        name=f"Living Room Hub.{ZEROCONF_TYPE}",
        properties=props,
    )


async def test_user_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room Hub"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: 8089,
        CONF_TOKEN: None,
        CONF_TRANSPORT: TRANSPORT_API,
    }
    assert result["result"].unique_id == HUB_ID
    assert mock_setup_entry.call_count == 1


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (HarmonyNgConnectionError("refused"), "cannot_connect"),
        (HarmonyNgApiError("boom", code=500), "cannot_connect"),
        (HarmonyNgUnsupportedError("the Hub reports no hub_id"), "not_harmony_ng"),
        (HarmonyNgUnsupportedError("API version 1 is below 2"), "unsupported_firmware"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any, error: Exception, code: str
) -> None:
    mock_client.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": code}

    mock_client.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_with_auth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any
) -> None:
    mock_client.side_effect = HarmonyNgAuthError("token required")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "auth"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "bad"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == TOKEN


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: Any,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.99", CONF_PORT: 8089}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.0.2.99"


async def test_zeroconf_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"name": "Living Room Hub", "host": HOST}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room Hub"
    assert result["result"].unique_id == HUB_ID
    assert result["data"][CONF_HOST] == HOST


async def test_zeroconf_flow_with_auth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info(auth="1")
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "auth"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == TOKEN


async def test_zeroconf_confirm_errors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    mock_client.side_effect = HarmonyNgConnectionError("refused")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.side_effect = HarmonyNgAuthError("token required")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "auth"


@pytest.mark.parametrize(
    ("properties", "reason"),
    [
        ({"id": ""}, "not_harmony_ng"),
        ({"api": "1"}, "unsupported_firmware"),
        ({"api": "x"}, "unsupported_firmware"),
    ],
)
async def test_zeroconf_aborts(
    hass: HomeAssistant, properties: dict[str, str], reason: str
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info(**properties)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


async def test_zeroconf_updates_known_hub(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    info = zeroconf_info()
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.77"),
        ip_addresses=[ip_address("192.0.2.77")],
        port=8090,
        hostname=info.hostname,
        type=info.type,
        name=info.name,
        properties=info.properties,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.0.2.77"
    assert mock_config_entry.data[CONF_PORT] == 8090


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: Any,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    mock_client.side_effect = HarmonyNgAuthError("bad")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "bad"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.side_effect = None
    other = HubStatus.from_json({**load_json("status"), "hub_id": "20140101120000-000009"})
    mock_client.return_value = other
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["errors"] == {"base": "hub_mismatch"}

    mock_client.return_value = HubStatus.from_json(load_json("status"))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_TOKEN] == TOKEN


async def test_reconfigure_flow(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: Any,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    mock_client.side_effect = HarmonyNgAuthError("token required")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.side_effect = None
    mock_client.return_value = HubStatus.from_json(
        {**load_json("status"), "hub_id": "20140101120000-000009"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089, CONF_TOKEN: TOKEN}
    )
    assert result["errors"] == {"base": "hub_mismatch"}

    mock_client.return_value = HubStatus.from_json(load_json("status"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089, CONF_TOKEN: TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.0.2.50"
    assert mock_config_entry.data[CONF_TOKEN] == TOKEN


async def test_options_flow(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert schema is not None
    selector = next(value for key, value in schema.schema.items() if key == CONF_DEFAULT_ACTIVITY)
    assert [o["value"] for o in selector.config["options"]] == [
        "previous",
        "Watch TV",
        "Listen to Music",
    ]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEFAULT_ACTIVITY: "Watch TV", CONF_DELAY_SECS: 0.2}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEFAULT_ACTIVITY: "Watch TV", CONF_DELAY_SECS: 0.2}


async def test_options_flow_without_runtime(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    selector = next(value for key, value in schema.schema.items() if key == CONF_DEFAULT_ACTIVITY)
    assert [o["value"] for o in selector.config["options"]] == ["previous"]
