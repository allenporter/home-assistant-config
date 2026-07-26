"""Tests for the conversation agent agenda notifications."""

import datetime
import logging
import pathlib
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

_LOGGER = logging.getLogger(__name__)


AUTOMATION_YAML = pathlib.Path("config/automations/notify_agenda.yaml")
NOTIFY_ENTITY = "notify.notifier"
WEATHER_ENTITY = "weather.demo_weather_north"


@pytest.fixture(autouse=True)
async def mock_default_components(hass: HomeAssistant) -> None:
    """Fixture to setup required default components."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})


@pytest.fixture(name="weather")
async def mock_weather_demo(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.demo.COMPONENTS_WITH_CONFIG_ENTRY_DEMO_PLATFORM",
        [Platform.WEATHER],
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED

    state = hass.states.get(WEATHER_ENTITY)
    assert state is not None

    return config_entry


@pytest.fixture(name="notify")
async def mock_notify(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.demo.COMPONENTS_WITH_CONFIG_ENTRY_DEMO_PLATFORM",
        [Platform.NOTIFY],
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED

    state = hass.states.get(NOTIFY_ENTITY)
    assert state is not None

    return config_entry


@pytest.fixture(name="template")
async def mock_template(
    hass: HomeAssistant,
    weather: Any,
    notify: Any,
) -> None:
    content = await hass.async_add_executor_job(AUTOMATION_YAML.read_text)
    content = content.replace("weather.woodgreen", WEATHER_ENTITY)
    content = content.replace(
        "conversation_agent: 2ee2edd1e9dbee5de7474922ce3cee42",
        "conversation_agent: conversation.home_assistant",
    )
    content = content.replace(
        "notify_service: notify.discord",
        "notify_service: notify.persistent_notification",
    )
    content = content.replace(
        "notify_target: notify.discord", "notify_target: notify.notifier"
    )
    print(content)
    config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


@pytest.fixture
def notify_service_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Fixture that catches notify events."""
    return async_mock_service(hass, "notify", "persistent_notification")


@pytest.mark.parametrize(("expected_lingering_timers"), [True])
async def test_notify_agenda(
    hass: HomeAssistant,
    template: Any,
    calendar: Any,
    error_caplog: pytest.LogCaptureFixture,
    notify_service_calls: list[ServiceCall],
) -> None:
    """Collects model responses for area summaries."""

    state = hass.states.get("automation.conversation_agent_agenda_notification")
    assert state
    assert state.state == "on"

    # Automation is triggered daily
    next = utcnow() + datetime.timedelta(hours=24)
    with freeze_time(next):
        async_fire_time_changed(hass, next)
        await hass.async_block_till_done()

    assert len(notify_service_calls) == 1
    data = notify_service_calls[0].data
    assert "Agenda" in data.get("title")

    # We're using the default agent for testing
    assert "couldn't understand that" in data.get(
        "message"
    ) or "Sorry, I am not aware" in data.get("message")

    # Automation completes with success
    assert not error_caplog.records
