"""Test fixtures for configuration."""

import logging
import pathlib
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


_LOGGER = logging.getLogger(__name__)

CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"


@pytest.fixture(autouse=True)
def mock_config_dir() -> None:
    with patch(
        "pytest_homeassistant_custom_component.common.get_test_config_dir",
        return_value=CONFIG_DIR,
    ):
        yield


@pytest.fixture(autouse=True)
async def mock_default_components(hass: HomeAssistant) -> None:
    """Fixture to setup required default components."""
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture(name="error_caplog")
def caplog_fixture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture error logs."""
    caplog.set_level(logging.ERROR)
    return caplog
