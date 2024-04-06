"""Tests for the weather forecast templates."""

import datetime
import pathlib
import logging
from unittest.mock import patch
from freezegun import freeze_time

import yaml
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.const import Platform

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)


_LOGGER = logging.getLogger(__name__)


WEATHER_FORECAST_YAML = pathlib.Path("config/templates/weather_forecast.yaml")


@pytest.fixture(autouse=True)
async def mock_demo(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.demo.COMPONENTS_WITH_CONFIG_ENTRY_DEMO_PLATFORM",
        [Platform.WEATHER],
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry


@pytest.fixture(autouse=True)
async def mock_template(hass: HomeAssistant) -> None:
    with WEATHER_FORECAST_YAML.open("r") as fd:
        content = fd.read()
        content = content.replace("weather.woodgreen", "weather.demo_weather_north")
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "template", {"template": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


@pytest.mark.parametrize(("expected_lingering_timers"), [True])
async def test_weather_summary(
    hass: HomeAssistant,
) -> None:
    """Collects model responses for area summaries."""
    assert await async_setup_component(hass, "sun", {})
    await hass.async_block_till_done()

    # Advance past the trigger time
    next = datetime.datetime.now() + datetime.timedelta(hours=1)
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
