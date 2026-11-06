"""Tests for the config, reauth, reconfigure and options flows."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from ipaddress import ip_address
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.harmony_ng.config_flow import (
    ERROR_MQTT_NOT_CONFIGURED,
    ProbeError,
    async_probe_mqtt,
)
from custom_components.harmony_ng.const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    CONF_MQTT_BASE_TOPIC,
    CONF_TOKEN,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_API,
    TRANSPORT_MQTT,
    ZEROCONF_TYPE,
)
from custom_components.harmony_ng.pyharmonyng import (
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    HubStatus,
)
from homeassistant.components import mqtt
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import HOST, HUB_ID
from .pyharmonyng.conftest import load_json
from .test_transport_mqtt import no_lingering_timers  # noqa: F401

API = {CONF_TRANSPORT: TRANSPORT_API}

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
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "transport"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], API)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room Hub"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: 8089,
        CONF_TOKEN: None,
        CONF_TRANSPORT: TRANSPORT_API,
        CONF_MQTT_BASE_TOPIC: None,
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
    assert result["step_id"] == "transport"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], API)
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
    assert result["step_id"] == "transport"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], API)
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
    assert result["step_id"] == "transport"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], API)
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
    assert result["step_id"] == "transport"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], API)
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
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089, **API}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.side_effect = None
    mock_client.return_value = HubStatus.from_json(
        {**load_json("status"), "hub_id": "20140101120000-000009"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089, CONF_TOKEN: TOKEN, **API}
    )
    assert result["errors"] == {"base": "hub_mismatch"}

    mock_client.return_value = HubStatus.from_json(load_json("status"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8089, CONF_TOKEN: TOKEN, **API}
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


@pytest.fixture
def mock_mqtt_probe() -> Generator[AsyncMock]:
    """Replace the MQTT probe of the transport step."""
    status = HubStatus.from_json({**load_json("status"), "capabilities": ["events", "mqtt_v2"]})
    with patch(
        "custom_components.harmony_ng.config_flow.async_probe_mqtt", AsyncMock(return_value=status)
    ) as probe:
        yield probe


async def test_transport_mqtt(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: Any, mock_mqtt_probe: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089}
    )
    assert result["step_id"] == "transport"

    mock_mqtt_probe.side_effect = ProbeError(ERROR_MQTT_NOT_CONFIGURED)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRANSPORT: TRANSPORT_MQTT, CONF_MQTT_BASE_TOPIC: "harmony/hub"}
    )
    assert result["errors"] == {"base": "mqtt_not_configured"}

    mock_mqtt_probe.side_effect = None
    mock_mqtt_probe.return_value = HubStatus.from_json(
        {**load_json("status"), "hub_id": "20140101120000-000009", "capabilities": ["mqtt_v2"]}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRANSPORT: TRANSPORT_MQTT, CONF_MQTT_BASE_TOPIC: "harmony/hub"}
    )
    assert result["errors"] == {"base": "hub_mismatch"}

    mock_mqtt_probe.return_value = HubStatus.from_json(
        {**load_json("status"), "capabilities": ["mqtt_v2"]}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRANSPORT: TRANSPORT_MQTT, CONF_MQTT_BASE_TOPIC: "home/hub"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TRANSPORT] == TRANSPORT_MQTT
    assert result["data"][CONF_MQTT_BASE_TOPIC] == "home/hub"
    mock_mqtt_probe.assert_awaited_with(hass, "home/hub")


async def test_reconfigure_switches_transport(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: Any,
    mock_mqtt_probe: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: HOST,
            CONF_PORT: 8089,
            CONF_TRANSPORT: TRANSPORT_MQTT,
            CONF_MQTT_BASE_TOPIC: "harmony/hub",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TRANSPORT] == TRANSPORT_MQTT
    assert mock_config_entry.data[CONF_MQTT_BASE_TOPIC] == "harmony/hub"
    assert mock_config_entry.unique_id == HUB_ID

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8089, CONF_TRANSPORT: TRANSPORT_API}
    )
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TRANSPORT] == TRANSPORT_API
    assert mock_config_entry.data[CONF_MQTT_BASE_TOPIC] is None


@pytest.mark.usefixtures("mqtt_mock")
async def test_probe_mqtt(hass: HomeAssistant) -> None:
    hub = {**load_json("status"), "type": "hub", "capabilities": ["events", "mqtt_v2"]}

    async def probe(payloads: list[str], base: str = "harmony/hub") -> HubStatus:
        subscribed = asyncio.Event()
        original = mqtt.async_subscribe

        async def _subscribe(*args: Any, **kwargs: Any) -> Any:
            unsubscribe = await original(*args, **kwargs)
            subscribed.set()
            return unsubscribe

        with patch("custom_components.harmony_ng.config_flow.mqtt.async_subscribe", _subscribe):
            task = hass.async_create_task(async_probe_mqtt(hass, base))
            await asyncio.wait_for(subscribed.wait(), 5)
            for payload in payloads:
                async_fire_mqtt_message(hass, f"{base.rstrip('/')}/hub", payload)
            return await task

    status = await probe(["junk", "[1]", json.dumps(hub)], base="home/hub/")
    assert status.hub_id == HUB_ID

    with pytest.raises(ProbeError) as info:
        await probe([json.dumps({**hub, "hub_id": None})])
    assert info.value.code == "mqtt_unsupported"

    with pytest.raises(ProbeError) as info:
        await probe([json.dumps({**hub, "capabilities": ["events"]})])
    assert info.value.code == "mqtt_unsupported"

    with (
        patch("custom_components.harmony_ng.config_flow.MQTT_PROBE_TIMEOUT", 0.05),
        pytest.raises(ProbeError) as info,
    ):
        await probe([])
    assert info.value.code == "mqtt_unsupported"

    with (
        patch(
            "custom_components.harmony_ng.config_flow.mqtt.async_wait_for_mqtt_client",
            return_value=False,
        ),
        pytest.raises(ProbeError) as info,
    ):
        await async_probe_mqtt(hass, "harmony/hub")
    assert info.value.code == "mqtt_not_configured"
