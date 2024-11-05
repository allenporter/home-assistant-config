"""Tests for the weather intent scripts."""

import datetime
import pathlib
import logging
from typing import Any
from unittest.mock import patch, Mock
from collections.abc import Generator

import pytest
import yaml

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util
from homeassistant.components.local_calendar.store import LocalCalendarStore

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)


_LOGGER = logging.getLogger(__name__)


SCRIPT_YAML = pathlib.Path("config/intent_scripts/todays_agenda.yaml")
CALENDAR_ENTITY = "calendar.personal"


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
async def mock_demo(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain="local_calendar", data={"calendar_name": "personal"}
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry


@pytest.fixture(name="script")
async def mock_script(hass: HomeAssistant) -> None:
    with SCRIPT_YAML.open("r") as fd:
        content = fd.read()
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "intent_script", {"intent_script": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_empty_calendar_agenda(
    hass: HomeAssistant,
    calendar: Any,
    script: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the calendar event summary when there are no events."""
    response = await intent.async_handle(hass, "test", "GetTodaysAgenda", {})
    assert response.speech["plain"]["speech"] == "- No upcoming events."


async def test_upcoming_events(
    hass: HomeAssistant,
    calendar: Any,
    script: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the calendar event summary with an upcoming event."""

    start_time = dt_util.now() + datetime.timedelta(hours=1)
    end_time = start_time + datetime.timedelta(minutes=30)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "start_date_time": start_time.isoformat(),
            "end_date_time": end_time.isoformat(),
            "summary": "Bastille Day Party",
            "location": "Test Location",
        },
        target={"entity_id": CALENDAR_ENTITY},
        blocking=True,
    )
    await hass.async_block_till_done()

    start_time += datetime.timedelta(hours=1)
    end_time = start_time + datetime.timedelta(minutes=15)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "start_date_time": start_time.isoformat(),
            "end_date_time": end_time.isoformat(),
            "summary": "Meeting",
            "description": "Test description",
        },
        target={"entity_id": CALENDAR_ENTITY},
        blocking=True,
    )
    await hass.async_block_till_done()

    response = await intent.async_handle(hass, "test", "GetTodaysAgenda", {})
    assert (
        response.speech["plain"]["speech"]
        == """Summary: Bastille Day Party
  Starts in: 0 hours, 59 minutes, lasts 0:30:00 (h:mm:ss).
  Location: Test Location

  Summary: Meeting
  Starts in: 1 hours, 59 minutes, lasts 0:15:00 (h:mm:ss).
  Description: Test description"""
    )



async def test_event_starting_now(
    hass: HomeAssistant,
    calendar: Any,
    script: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Test an event that starts at the same time as the script is run."""

    start_time = dt_util.now() - datetime.timedelta(seconds=1)
    end_time = start_time + datetime.timedelta(minutes=30)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "start_date_time": start_time.isoformat(),
            "end_date_time": end_time.isoformat(),
            "summary": "Bastille Day Party",
            "location": "Test Location",
        },
        target={"entity_id": CALENDAR_ENTITY},
        blocking=True,
    )
    await hass.async_block_till_done()

    response = await intent.async_handle(hass, "test", "GetTodaysAgenda", {})
    assert (
        response.speech["plain"]["speech"]
        == """Summary: Bastille Day Party
  Starts in: 0 hours, 0 minutes, lasts 0:30:00 (h:mm:ss).
  Location: Test Location"""
    )
