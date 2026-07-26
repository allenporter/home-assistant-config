"""Tests for the weather forecast templates."""

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
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

_LOGGER = logging.getLogger(__name__)


WEATHER_FORECAST_YAML = pathlib.Path("config/templates/weather_forecast.yaml")


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
    return config_entry


@pytest.fixture(name="template")
async def mock_template(hass: HomeAssistant) -> None:
    content = await hass.async_add_executor_job(WEATHER_FORECAST_YAML.read_text)
    content = content.replace("weather.woodgreen", "weather.demo_weather_north")
    config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "template", {"template": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


@pytest.mark.parametrize(("expected_lingering_timers"), [True])
async def test_weather_forecast_template(
    hass: HomeAssistant,
    weather: Any,
    template: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the weather summary."""
    assert await async_setup_component(hass, "sun", {})
    await hass.async_block_till_done()

    # Advance past the trigger time
    next = utcnow() + datetime.timedelta(hours=1)
    with freeze_time(next):
        async_fire_time_changed(hass, next)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.woodgreen_forecast_display")
    assert state
    assert state.state == "OK"
    assert state.attributes.get("friendly_name") == "Woodgreen Forecast Display"

    assert state.attributes.get("weather_temperature_0") == -23
    assert state.attributes.get("weather_timestamp_0") == "4 PM"

    assert state.attributes.get("weather_temperature_1") == -25
    assert state.attributes.get("weather_timestamp_1") == "5 PM"

    assert state.attributes.get("weather_temperature_2") == -28
    assert state.attributes.get("weather_timestamp_2") == "6 PM"

    assert state.attributes.get("weather_temperature_3") == -31
    assert state.attributes.get("weather_timestamp_3") == "7 PM"

    assert not error_caplog.records
