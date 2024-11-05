"""Tests for the weather intent scripts."""

import pathlib
import logging
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.const import Platform
from homeassistant.helpers import intent

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)


_LOGGER = logging.getLogger(__name__)


SCRIPT_YAML = pathlib.Path("config/intent_scripts/weather_forecast.yaml")
TEST_WEATHER_ENTITY = "weather.demo_weather_north"


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


@pytest.fixture(name="script")
async def mock_script(hass: HomeAssistant) -> None:
    with SCRIPT_YAML.open("r") as fd:
        content = fd.read()
        content = content.replace("weather.woodgreen", TEST_WEATHER_ENTITY)
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "intent_script", {"intent_script": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_get_weather_forecast(
    hass: HomeAssistant,
    weather: Any,
    script: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the weather summary."""
    response = await intent.async_handle(hass, "test", "GetWeatherForecast", {})
    assert response.speech["plain"]["speech"] == "sunny (-23.3°C, 2.0% precipitation)"
