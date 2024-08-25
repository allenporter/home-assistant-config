"""Tests for the weather forecast templates."""

import datetime
import pathlib
import logging
from typing import Any
from collections.abc import Mapping
from unittest.mock import patch

import pytest
from freezegun import freeze_time
import yaml

from homeassistant.core import HomeAssistant, Event, ServiceCall
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.const import Platform

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_capture_events,
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


@pytest.fixture(name="calendar")
async def mock_demo(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain="local_calendar", data={"calendar_name": "personal"}
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry


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
    calendar: Any,
    weather: Any,
    notify: Any,
) -> None:
    with AUTOMATION_YAML.open("r") as fd:
        content = fd.read()
        content = content.replace("weather.woodgreen", WEATHER_ENTITY)
        content = content.replace(
            "conversation_agent: 2ee2edd1e9dbee5de7474922ce3cee42",
            "conversation_agent: homeassistant",
        )
        content = content.replace("notify_service: notify.discord", "notify_service: notify.persistent_notification")
        content = content.replace("notify_target: notify.discord", "notify_target: notify.notifier")
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
    error_caplog: pytest.LogCaptureFixture,
    notify_service_calls: list[ServiceCall],
) -> None:
    """Collects model responses for area summaries."""

    state = hass.states.get("automation.conversation_agent_agenda_notification")
    assert state
    assert state.state == "on"

    # Automation is triggered daily
    next = datetime.datetime.now() + datetime.timedelta(hours=24)
    with freeze_time(next):
        async_fire_time_changed(hass, next)
        await hass.async_block_till_done()

    assert len(notify_service_calls) == 1
    data = notify_service_calls[0].data
    assert "Agenda" in data.get("title")

    # We're using the default agent for testing
    assert "couldn't understand that" in data.get("message")

    # Automation completes with success
    assert not error_caplog.records
