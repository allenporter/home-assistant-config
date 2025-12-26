"""Tests for the calendar location template."""

import datetime
import pathlib
import logging
from typing import Any

import pytest
import yaml
from freezegun import freeze_time

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)

_LOGGER = logging.getLogger(__name__)

CALENDAR_LOCATION_YAML = pathlib.Path("config/templates/calendar_location.yaml")


@pytest.fixture(name="template")
async def mock_template(hass: HomeAssistant, calendar: Any) -> None:
    """Mock the template."""
    with CALENDAR_LOCATION_YAML.open("r") as fd:
        content = fd.read()
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "template", {"template": config})
    await hass.async_block_till_done()


@pytest.mark.parametrize(("expected_lingering_timers"), [True])
async def test_calendar_location_template(
    hass: HomeAssistant,
    calendar: Any,
    template: Any,
    error_caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the calendar location template."""

    # Create an event
    now = dt_util.now()
    start = now + datetime.timedelta(hours=7)
    end = start + datetime.timedelta(hours=1)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": "calendar.personal",
            "summary": "Gym",
            "location": "Gym Location",
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        },
        blocking=True,
    )

    # Trigger the template update via time pattern
    next_run = now + datetime.timedelta(hours=6)
    with freeze_time(next_run):
        async_fire_time_changed(hass, next_run)
        await hass.async_block_till_done()

    # Check sensors
    state = hass.states.get("sensor.next_location")
    assert state
    assert state.state == "Gym Location"

    state = hass.states.get("sensor.next_location_summary")
    assert state
    assert state.state == "Gym"

    state = hass.states.get("sensor.next_location_start")
    assert state
    assert dt_util.parse_datetime(state.state) == start.replace(microsecond=0)

    assert not error_caplog.records
