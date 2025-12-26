"""Fixtures for setting up a local calendar store."""

import pathlib
from unittest.mock import patch, Mock
from collections.abc import Generator

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.components.local_calendar.store import LocalCalendarStore

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)


class FakeStore(LocalCalendarStore):
    """Mock storage implementation."""

    def __init__(
        self,
        hass: HomeAssistant,
        path: pathlib.Path,
    ) -> None:
        """Initialize FakeStore."""
        super().__init__(hass, path)
        mock_path = self._mock_path = Mock()
        mock_path.exists = self._mock_exists
        mock_path.read_text = Mock()
        mock_path.read_text.return_value = ""
        mock_path.write_text = self._mock_write_text
        super().__init__(hass, mock_path)

    def _mock_exists(self) -> bool:
        return self._mock_path.read_text.return_value is not None

    def _mock_write_text(self, content: str) -> None:
        self._mock_path.read_text.return_value = content


@pytest.fixture(name="store", autouse=True)
def mock_store() -> Generator[None]:
    """Test cleanup, remove any media storage persisted during the test."""

    def new_store(hass: HomeAssistant, path: pathlib.Path) -> FakeStore:
        # Single fake store
        return FakeStore(hass, path)

    with patch(
        "homeassistant.components.local_calendar.LocalCalendarStore", new=new_store
    ):
        yield


@pytest.fixture(name="calendar")
async def mock_calendar(hass: HomeAssistant) -> MockConfigEntry:
    """Mock the local calendar."""
    config_entry = MockConfigEntry(
        domain="local_calendar", data={"calendar_name": "personal"}
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry
