"""Tests for the alarm control panel configuration."""

import pathlib
import logging
from typing import Any

import pytest
import yaml

from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

_LOGGER = logging.getLogger(__name__)


SECRET_CODE = "1234"

ALARM_CONTROL_PANEL_YAML = pathlib.Path("config/alarm_control_panel.yaml")
HOME_ALARM_ENTITY_ID = "alarm_control_panel.home_alarm"
TEMPLATE_ALARM_ENTITY_ID = "alarm_control_panel.safe_alarm"


@pytest.fixture(name="alarm_control_panel")
async def mock_template(hass: HomeAssistant) -> None:
    with ALARM_CONTROL_PANEL_YAML.open("r") as fd:
        content = fd.read()
        content = content.replace("!secret alarm_code", SECRET_CODE)
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "alarm_control_panel", config)
    await hass.async_block_till_done()


async def test_manual_alarm_control_panel(
    hass: HomeAssistant,
    alarm_control_panel: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the alarm control panel."""

    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "disarmed"
    assert state.attributes == {
        "friendly_name": "Home Alarm",
        "changed_by": None,
        "code_arm_required": False,
        "code_format": "number",
        "supported_features": 63,
        "next_state": None,
        "previous_state": None,
    }

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        service_data={},
        blocking=True,
        target={"entity_id": HOME_ALARM_ENTITY_ID},
    )
    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "armed_home"

    # Attempt to disarm the alarm with the wrong code
    with pytest.raises(HomeAssistantError, match="Invalid alarm code"):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            service_data={"code": ""},
            blocking=True,
            target={"entity_id": HOME_ALARM_ENTITY_ID},
        )

    with pytest.raises(HomeAssistantError, match="Invalid alarm code"):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            service_data={"code": ""},
            blocking=True,
            target={"entity_id": HOME_ALARM_ENTITY_ID},
        )

    with pytest.raises(HomeAssistantError, match="Invalid alarm code"):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            service_data={"code": "4321"},
            blocking=True,
            target={"entity_id": HOME_ALARM_ENTITY_ID},
        )

    # Verify alarm is armed
    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "armed_home"

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        service_data={"code": SECRET_CODE},
        blocking=True,
        target={"entity_id": HOME_ALARM_ENTITY_ID},
    )
    await hass.async_block_till_done()

    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "disarmed"

    assert not error_caplog.records


async def test_template_control_panel(
    hass: HomeAssistant,
    alarm_control_panel: Any,
    error_caplog: pytest.CaptureFixture,
) -> None:
    """Exercise the template control panel can control the underlying alarm."""

    state = hass.states.get(TEMPLATE_ALARM_ENTITY_ID)
    assert state
    assert state.state == "disarmed"
    assert state.attributes == {
        "friendly_name": "Safe Alarm",
        "changed_by": None,
        "code_arm_required": False,
        "code_format": None,
        "supported_features": 3,
    }

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        service_data={},
        blocking=True,
        target={"entity_id": TEMPLATE_ALARM_ENTITY_ID},
    )
    await hass.async_block_till_done()

    # Verify both panels are armed
    state = hass.states.get(TEMPLATE_ALARM_ENTITY_ID)
    assert state
    assert state.state == "armed_home"
    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "armed_home"

    # Disarm the alarm without a code
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        blocking=True,
        target={"entity_id": TEMPLATE_ALARM_ENTITY_ID},
    )
    await hass.async_block_till_done()

    # Verify both alarms are disarmed
    state = hass.states.get(TEMPLATE_ALARM_ENTITY_ID)
    assert state
    assert state.state == "disarmed"
    state = hass.states.get(HOME_ALARM_ENTITY_ID)
    assert state
    assert state.state == "disarmed"

    assert not error_caplog.records
