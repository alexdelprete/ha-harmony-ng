"""Config flow for Harmony NG: discovery, manual setup, auth, transport, reauth, reconfigure, options."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import logging
from typing import Any

import probatio

from homeassistant.components import mqtt
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import Required as VisibleRequired
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.field_visibility import FieldCondition
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    CONF_MQTT_BASE_TOPIC,
    CONF_TOKEN,
    CONF_TRANSPORT,
    DEFAULT_DELAY_SECS,
    DEFAULT_PORT,
    DOMAIN,
    PREVIOUS_ACTIVITY,
    TRANSPORT_API,
    TRANSPORT_MQTT,
    TXT_API,
    TXT_AUTH,
    TXT_ID,
    TXT_NAME,
    TXT_TOPIC,
)
from .pyharmonyng import (
    CAP_MQTT_V2,
    MIN_API_VERSION,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgClient,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    HubStatus,
)

_LOGGER = logging.getLogger(__name__)

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_AUTH_REQUIRED = "auth_required"
ERROR_NOT_HARMONY_NG = "not_harmony_ng"
ERROR_UNSUPPORTED_FIRMWARE = "unsupported_firmware"
ERROR_HUB_MISMATCH = "hub_mismatch"
ERROR_MQTT_NOT_CONFIGURED = "mqtt_not_configured"
ERROR_MQTT_UNSUPPORTED = "mqtt_unsupported"

MQTT_PROBE_TIMEOUT = 10.0
DEFAULT_BASE_TOPIC = "harmony/hub"

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): cv.string,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)
TOKEN_SCHEMA = probatio.Schema({probatio.Required(CONF_TOKEN): cv.string})
TRANSPORT_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[TRANSPORT_API, TRANSPORT_MQTT],
        mode=SelectSelectorMode.LIST,
        translation_key=CONF_TRANSPORT,
    )
)
MQTT_ONLY: FieldCondition = {"field": CONF_TRANSPORT, "value": TRANSPORT_MQTT}


def transport_schema(transport: str, base_topic: str) -> probatio.Schema:
    """Return the transport choice with the base topic shown for MQTT only."""
    return probatio.Schema(
        {
            probatio.Required(CONF_TRANSPORT, default=transport): TRANSPORT_SELECTOR,
            VisibleRequired(CONF_MQTT_BASE_TOPIC, default=base_topic, visible=MQTT_ONLY): cv.string,
        }
    )


class ProbeError(Exception):
    """A probe failed with a flow error code."""

    def __init__(self, code: str) -> None:
        """Keep the error code shown in the form."""
        super().__init__(code)
        self.code = code


async def async_probe(flow: ConfigFlow, host: str, port: int, token: str | None) -> HubStatus:
    """Read the Hub's status over REST, mapping library errors to flow error codes."""
    client = HarmonyNgClient(host, async_get_clientsession(flow.hass), port=port, token=token)
    try:
        return await client.get_status()
    except HarmonyNgAuthError as err:
        raise ProbeError(ERROR_INVALID_AUTH if token else ERROR_AUTH_REQUIRED) from err
    except HarmonyNgUnsupportedError as err:
        code = ERROR_NOT_HARMONY_NG if "hub_id" in str(err) else ERROR_UNSUPPORTED_FIRMWARE
        raise ProbeError(code) from err
    except (HarmonyNgConnectionError, HarmonyNgApiError) as err:
        raise ProbeError(ERROR_CANNOT_CONNECT) from err


async def async_probe_mqtt(hass: HomeAssistant, base_topic: str) -> HubStatus:
    """Read the Hub's retained hub topic through the MQTT integration."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ProbeError(ERROR_MQTT_NOT_CONFIGURED)
    received: asyncio.Future[Mapping[str, Any]] = asyncio.get_running_loop().create_future()

    @callback
    def _on_message(message: mqtt.ReceiveMessage) -> None:
        if received.done():
            return
        try:
            payload = json.loads(message.payload)
        except TypeError, ValueError:
            return
        if isinstance(payload, Mapping):
            received.set_result(payload)

    unsubscribe = await mqtt.async_subscribe(hass, f"{base_topic.rstrip('/')}/hub", _on_message)
    try:
        async with asyncio.timeout(MQTT_PROBE_TIMEOUT):
            payload = await received
    except TimeoutError as err:
        raise ProbeError(ERROR_MQTT_UNSUPPORTED) from err
    finally:
        unsubscribe()
    try:
        status = HubStatus.from_json(payload)
    except HarmonyNgUnsupportedError as err:
        raise ProbeError(ERROR_MQTT_UNSUPPORTED) from err
    if not status.has(CAP_MQTT_V2):
        raise ProbeError(ERROR_MQTT_UNSUPPORTED)
    return status


class HarmonyNgConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for a Hub."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing known about the Hub."""
        self._host = ""
        self._port: int = DEFAULT_PORT
        self._token: str | None = None
        self._name: str | None = None
        self._auth_required = False
        self._base_topic = DEFAULT_BASE_TOPIC
        self._status: HubStatus | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HarmonyNgOptionsFlow:
        """Return the options flow."""
        return HarmonyNgOptionsFlow()

    # Manual setup

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for host and port, then probe the Hub."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input[CONF_PORT]
            try:
                status = await async_probe(self, self._host, self._port, None)
            except ProbeError as err:
                if err.code == ERROR_AUTH_REQUIRED:
                    return await self.async_step_auth()
                errors["base"] = err.code
            else:
                return await self._async_probed(status)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    # Discovery

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle a Hub found through mDNS."""
        properties = discovery_info.properties
        hub_id = properties.get(TXT_ID)
        if not hub_id:
            return self.async_abort(reason=ERROR_NOT_HARMONY_NG)
        if _txt_int(properties.get(TXT_API)) < MIN_API_VERSION:
            return self.async_abort(reason=ERROR_UNSUPPORTED_FIRMWARE)
        self._host = discovery_info.host
        self._port = discovery_info.port or DEFAULT_PORT
        self._name = properties.get(TXT_NAME) or discovery_info.name.split(".")[0]
        self._auth_required = properties.get(TXT_AUTH) == "1"
        self._base_topic = properties.get(TXT_TOPIC) or DEFAULT_BASE_TOPIC
        await self.async_set_unique_id(hub_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port})
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user confirm the discovered Hub."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._auth_required:
                return await self.async_step_auth()
            try:
                status = await async_probe(self, self._host, self._port, None)
            except ProbeError as err:
                if err.code == ERROR_AUTH_REQUIRED:
                    return await self.async_step_auth()
                errors["base"] = err.code
            else:
                return await self._async_probed(status)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name or "", "host": self._host},
            errors=errors,
        )

    # Authentication

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a Personal Access Token when the Hub requires one."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._token = user_input[CONF_TOKEN]
            try:
                status = await async_probe(self, self._host, self._port, self._token)
            except ProbeError as err:
                errors["base"] = err.code
            else:
                return await self._async_probed(status)
        return self.async_show_form(step_id="auth", data_schema=TOKEN_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The Hub refused the stored token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token and check it against the same Hub."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_TOKEN]
            try:
                status = await async_probe(
                    self, entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT), token
                )
            except ProbeError as err:
                errors["base"] = err.code
            else:
                if status.hub_id != entry.unique_id:
                    errors["base"] = ERROR_HUB_MISMATCH
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_TOKEN: token}
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    # Transport

    async def _async_probed(self, status: HubStatus) -> ConfigFlowResult:
        """The Hub answered over REST; make sure it is new, then pick the transport."""
        await self.async_set_unique_id(status.hub_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port})
        self._status = status
        if status.mqtt is not None and status.mqtt.base_topic:
            self._base_topic = status.mqtt.base_topic
        return await self.async_step_transport()

    async def async_step_transport(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose API or MQTT; MQTT is checked against the broker and the same Hub."""
        errors: dict[str, str] = {}
        status = self._status
        if status is None:
            return await self.async_step_user()
        if user_input is not None:
            transport = user_input[CONF_TRANSPORT]
            base_topic = str(user_input.get(CONF_MQTT_BASE_TOPIC) or self._base_topic)
            try:
                await self._async_check_transport(transport, base_topic, status.hub_id)
            except ProbeError as err:
                errors["base"] = err.code
            else:
                return self.async_create_entry(
                    title=self._name or status.hub_name,
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_TOKEN: self._token,
                        CONF_TRANSPORT: transport,
                        CONF_MQTT_BASE_TOPIC: base_topic if transport == TRANSPORT_MQTT else None,
                    },
                )
        return self.async_show_form(
            step_id="transport",
            data_schema=self.add_suggested_values_to_schema(
                transport_schema(TRANSPORT_API, self._base_topic), user_input
            ),
            errors=errors,
        )

    async def _async_check_transport(self, transport: str, base_topic: str, hub_id: str) -> None:
        if transport != TRANSPORT_MQTT:
            return
        status = await async_probe_mqtt(self.hass, base_topic)
        if status.hub_id != hub_id:
            raise ProbeError(ERROR_HUB_MISMATCH)

    # Reconfiguration

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, port, token or transport; the Hub id must stay the same."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            token = user_input.get(CONF_TOKEN) or None
            transport = user_input[CONF_TRANSPORT]
            base_topic = str(
                user_input.get(CONF_MQTT_BASE_TOPIC)
                or entry.data.get(CONF_MQTT_BASE_TOPIC)
                or DEFAULT_BASE_TOPIC
            )
            try:
                await self._async_check_reconfigure(
                    entry,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    token,
                    transport,
                    base_topic,
                )
            except ProbeError as err:
                errors["base"] = ERROR_INVALID_AUTH if err.code == ERROR_AUTH_REQUIRED else err.code
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_TOKEN: token,
                        CONF_TRANSPORT: transport,
                        CONF_MQTT_BASE_TOPIC: base_topic if transport == TRANSPORT_MQTT else None,
                    },
                )
        schema = probatio.Schema(
            {
                probatio.Required(CONF_HOST, default=entry.data[CONF_HOST]): cv.string,
                probatio.Required(
                    CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                ): cv.port,
                probatio.Optional(CONF_TOKEN): cv.string,
                probatio.Required(
                    CONF_TRANSPORT, default=entry.data.get(CONF_TRANSPORT, TRANSPORT_API)
                ): TRANSPORT_SELECTOR,
                VisibleRequired(
                    CONF_MQTT_BASE_TOPIC,
                    default=entry.data.get(CONF_MQTT_BASE_TOPIC) or DEFAULT_BASE_TOPIC,
                    visible=MQTT_ONLY,
                ): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    async def _async_check_reconfigure(
        self,
        entry: ConfigEntry,
        host: str,
        port: int,
        token: str | None,
        transport: str,
        base_topic: str,
    ) -> None:
        status = await async_probe(self, host, port, token)
        if status.hub_id != entry.unique_id:
            raise ProbeError(ERROR_HUB_MISMATCH)
        await self._async_check_transport(transport, base_topic, status.hub_id)


class HarmonyNgOptionsFlow(OptionsFlowWithReload):
    """Default activity and inter-command delay, as the core integration offers."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        activities = _activity_options(self.config_entry)
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_DEFAULT_ACTIVITY,
                    default=options.get(CONF_DEFAULT_ACTIVITY, PREVIOUS_ACTIVITY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=activities,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key=CONF_DEFAULT_ACTIVITY,
                    )
                ),
                probatio.Required(
                    CONF_DELAY_SECS, default=options.get(CONF_DELAY_SECS, DEFAULT_DELAY_SECS)
                ): probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=10)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _activity_options(entry: ConfigEntry) -> list[SelectOptionDict]:
    """Return the selectable default activities: previous, then the Hub's."""
    options = [SelectOptionDict(value=PREVIOUS_ACTIVITY, label=PREVIOUS_ACTIVITY)]
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.coordinator.data is not None:
        options.extend(
            SelectOptionDict(value=activity.name, label=activity.name)
            for activity in runtime.coordinator.data.activities
        )
    return options


def _txt_int(value: Any) -> int:
    """Return a TXT record number, 0 when absent or malformed."""
    try:
        return int(value)
    except TypeError, ValueError:
        return 0
