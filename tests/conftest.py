"""Test fixtures for configuration."""

import logging

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def mock_default_components(hass: HomeAssistant) -> None:
    """Fixture to setup required default components."""
    assert await async_setup_component(hass, "homeassistant", {})
