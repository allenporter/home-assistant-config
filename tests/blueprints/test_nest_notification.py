"""Tests for the nest notification automations."""

import uuid
import shutil
from asyncio import AbstractEventLoop
import pathlib
import logging
import datetime
import copy
import re
from typing import Any
from collections.abc import Mapping, Generator
from unittest.mock import patch, AsyncMock

import pytest
import yaml
import aiohttp
from yarl import URL

from google_nest_sdm.event import EventType
from google_nest_sdm.traits import TraitType
from google_nest_sdm.streaming_manager import StreamingManager, Message

from homeassistant.core import HomeAssistant, Event, ServiceCall
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.components.application_credentials import (
    async_import_client_credential,
    ClientCredential,
)
from homeassistant.components.nest.const import API_URL
from homeassistant.util.dt import utcnow
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator


_LOGGER = logging.getLogger(__name__)


AUTOMATION_YAML = pathlib.Path("config/automations/nest_notification.yaml")
NEST_DEVICE_NAME = "enterprise/project/sdm/device-id"
NEST_DERVICE_TRAITS = {
    "name": NEST_DEVICE_NAME,
    "type": "sdm.devices.types.device-type",
    "traits": {
        TraitType.INFO: {"customName": "Front Door"},
        TraitType.CAMERA_CLIP_PREVIEW: {},
        TraitType.DOORBELL_CHIME: {},
        TraitType.CAMERA_MOTION: {},
    },
}
PROJECT_ID = "a"
SUBSCRIBER_ID = "projects/cloud-id-9876/subscriptions/subscriber-id-9876"
NEST_CONFIG_ENTRY_DATA = {
    "sdm": {},
    "project_id": PROJECT_ID,
    "cloud_project_id": "b",
    "subscriber_id": SUBSCRIBER_ID,
    "auth_implementation": "imported-cred",
    "token": {
        "access_token": "some-token",
        "expires_at": (
            datetime.datetime.now() + datetime.timedelta(days=7)
        ).timestamp(),
    },
}
DEVICE_URL_MATCH = re.compile(
    f"{API_URL}/enterprises/project-id/devices/[^:]+:executeCommand"
)
TEST_IMAGE_URL = "https://domain/sdm_event_snapshot/dGTZwR3o4Y1..."
TEST_CLIP_URL = "https://domain/clip/XyZ.mp4"

EVENT_SESSION_ID = "CjY5Y3VKaTZwR3o4Y19YbTVfMF..."
EVENT_ID = "FWWVQVUdGNUlTU2V4MGV2aTNXV..."
ENCODED_EVENT_ID = "WyJDalk1WTNWS2FUWndSM280WTE5WWJUVmZNRi4uLiIsICJGV1dWUVZVZEdOVWxUVTJWNE1HVjJhVE5YVi4uLiJd"
NEST_MEDIA_URL = "http://some-preview.com/url"

MOBILE_APP_DEVICE_ID = "mobile-device-id-1"
PUSH_URL = "http://push-url.com/push"
MOBILE_APP_CONFIG_ENTRY_DATA = {
    "webhook_id": "123",
    "app_id": "io.homeassistant.mobile_app",
    "app_version": "1.0",
    # "app_data": {"push_token": "PUSH_TOKEN", "push_url": "xx"},
    "app_data": {
        "push_websocket_channel": True,
        "push_url": PUSH_URL,
        "push_token": "PUSH_TOKEN",
    },
    "device_id": MOBILE_APP_DEVICE_ID,
    "manufacturer": "Google",
    "model": "Pixel 6",
    "device_name": "Pixel",
    "os_version": "",
}


@pytest.fixture(autouse=True)
def cleanup_media_storage(hass: HomeAssistant) -> Generator[None]:
    """Test cleanup, remove any media storage persisted during the test."""
    tmp_path = str(uuid.uuid4())
    with patch("homeassistant.components.nest.media_source.MEDIA_PATH", new=tmp_path):
        yield
        shutil.rmtree(hass.config.path(tmp_path), ignore_errors=True)


class CreateDevice:
    """Fixture used for creating devices."""

    def __init__(self) -> None:
        """Initialize CreateDevice."""
        self.data = {"traits": {}}
        self.devices = []

    def create(
        self,
        raw_traits: dict[str, Any] | None = None,
        raw_data: dict[str, Any] | None = None,
    ) -> None:
        """Create a new device with the specifeid traits."""
        data = copy.deepcopy(self.data)
        data.update(raw_data if raw_data else {})
        data["traits"].update(raw_traits if raw_traits else {})
        self.devices.append(data)


@pytest.fixture
async def device_id() -> str:
    """Fixture to set default device id used when creating devices."""
    return NEST_DEVICE_NAME


@pytest.fixture
async def device_type() -> str:
    """Fixture to set default device type used when creating devices."""
    return "sdm.devices.types.THERMOSTAT"


@pytest.fixture
async def device_traits() -> dict[str, Any]:
    """Fixture to set default device traits used when creating devices."""
    return {}


@pytest.fixture
async def create_device(
    device_id: str,
    device_type: str,
    device_traits: dict[str, Any],
) -> CreateDevice:
    """Fixture for creating devices."""
    factory = CreateDevice()
    factory.data.update(
        {
            "name": device_id,
            "type": device_type,
            "traits": device_traits,
        }
    )
    return factory


class FakeAuth:
    """A fixture for request handling that records requests.

    This class is used with AiohttpClientMocker to capture outgoing requests
    and can also be used by tests to set up fake responses.
    """

    def __init__(
        self,
        aioclient_mock: AiohttpClientMocker,
        device_factory: CreateDevice,
        project_id: str,
    ) -> None:
        """Initialize FakeAuth."""
        # Tests can factory fixture to create fake device responses.
        self.device_factory = device_factory
        # Tests can set fake structure responses here.
        self.structures: list[dict[str, Any]] = []
        # Tests can set fake command responses here.
        self.responses: list[aiohttp.web.Response] = []

        # The last request is recorded here.
        self.method = None
        self.url = None
        self.json = None
        self.headers = None
        self.captured_requests = []
        self._project_id = project_id
        self._aioclient_mock = aioclient_mock
        self.register_mock_requests()

    def register_mock_requests(self) -> None:
        """Register the mocks."""
        # API makes a call to request structures to initiate pubsub feed, but the
        # integration does not use this.
        self._aioclient_mock.get(
            f"{API_URL}/enterprises/{self._project_id}/structures",
            side_effect=self.request_structures,
        )
        self._aioclient_mock.get(
            f"{API_URL}/enterprises/{self._project_id}/devices",
            side_effect=self.request_devices,
        )
        self._aioclient_mock.post(DEVICE_URL_MATCH, side_effect=self.request)
        self._aioclient_mock.get(TEST_IMAGE_URL, side_effect=self.request)
        self._aioclient_mock.get(TEST_CLIP_URL, side_effect=self.request)

    async def request_structures(
        self, method: str, url: str, data: dict[str, Any]
    ) -> AiohttpClientMockResponse:
        """Handle requests to create devices."""
        return AiohttpClientMockResponse(
            method, url, json={"structures": self.structures}
        )

    async def request_devices(
        self, method: str, url: str, data: dict[str, Any]
    ) -> AiohttpClientMockResponse:
        """Handle requests to create devices."""
        return AiohttpClientMockResponse(
            method, url, json={"devices": self.device_factory.devices}
        )

    async def request(
        self, method: str, url: URL, data: dict[str, Any]
    ) -> AiohttpClientMockResponse:
        """Capure the request arguments for tests to assert on."""
        self.method = method
        str_url = str(url)
        self.url = str_url[len(API_URL) + 1 :]
        self.json = data
        self.captured_requests.append((method, url, self.json))

        if len(self.responses) > 0:
            response = self.responses.pop(0)
            return AiohttpClientMockResponse(
                method, url, response=response.body, status=response.status
            )
        return AiohttpClientMockResponse(method, url)


@pytest.fixture
def aiohttp_client(
    event_loop: AbstractEventLoop,
    aiohttp_client: ClientSessionGenerator,
    socket_enabled: None,
) -> ClientSessionGenerator:
    """Return aiohttp_client and allow opening sockets."""
    return aiohttp_client


@pytest.fixture(name="device_access_project_id")
def mock_device_access_project_id() -> str:
    """Fixture to configure the device access console project id used in tests."""
    return PROJECT_ID


@pytest.fixture
async def auth(
    aioclient_mock: AiohttpClientMocker,
    create_device: CreateDevice,
    device_access_project_id: str,
) -> FakeAuth:
    """Fixture for an AbstractAuth."""
    return FakeAuth(aioclient_mock, create_device, device_access_project_id)


@pytest.fixture
def subscriber_side_effect() -> Any | None:
    """Fixture to inject failures into FakeSubscriber start."""
    return None


@pytest.fixture(autouse=True, name="subscriber")
def subscriber_fixture(subscriber_side_effect: Any | None) -> Generator[AsyncMock]:
    """Fixture to allow tests to emulate the pub/sub subscriber receiving messages."""
    with patch(
        "google_nest_sdm.google_nest_subscriber.StreamingManager", spec=StreamingManager
    ) as mock_manager:
        # Use side_effect to capture the callback
        def mock_init(**kwargs: Any) -> AsyncMock:
            mock_manager.async_receive_event = kwargs["callback"]
            if subscriber_side_effect is not None:
                mock_manager.start.side_effect = subscriber_side_effect
            return mock_manager

        mock_manager.side_effect = mock_init
        yield mock_manager


@pytest.fixture(autouse=True)
async def mock_default_components(hass: HomeAssistant) -> None:
    """Fixture to setup required default components."""
    assert await async_setup_component(hass, "homeassistant", {})
    # assert await async_setup_component(hass, "ffmpeg", {})
    assert await async_setup_component(hass, "application_credentials", {})


@pytest.fixture(name="nest")
async def mock_nest(
    hass: HomeAssistant,
    create_device: CreateDevice,
    auth: FakeAuth,
) -> MockConfigEntry:
    create_device.create(raw_data=NEST_DERVICE_TRAITS)

    cred = ClientCredential("client-id", "client-secret")
    await async_import_client_credential(hass, "nest", cred, "imported-cred")
    config_entry = MockConfigEntry(
        domain="nest",
        data=NEST_CONFIG_ENTRY_DATA,
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry


@pytest.fixture(name="mobile_app")
async def mock_mobile_app(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "webhook", {})

    config_entry = MockConfigEntry(
        domain="mobile_app", data=MOBILE_APP_CONFIG_ENTRY_DATA
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state == ConfigEntryState.LOADED
    return config_entry


@pytest.fixture(name="template")
async def mock_template(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    nest: MockConfigEntry,
    mobile_app: MockConfigEntry,
) -> None:
    nest_device_entry = device_registry.async_get_device(
        identifiers={("nest", NEST_DEVICE_NAME)}
    )
    assert nest_device_entry
    mobile_device_entry = device_registry.async_get_device(
        identifiers={("mobile_app", MOBILE_APP_DEVICE_ID)}
    )
    assert mobile_device_entry

    with AUTOMATION_YAML.open("r") as fd:
        content = fd.read()
        content = content.replace("NEST_EVENT_ENTITY_ID", "event.front_door_chime")
        content = content.replace("NEST_DEVICE_ID", nest_device_entry.id)
        content = content.replace("MOBILE_APP_DEVICE_ID", mobile_device_entry.id)
        config = yaml.load(content, Loader=yaml.Loader)

    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


@pytest.fixture
def notify_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Fixture that catches notify events."""
    # return async_capture_events(hass, "notify")
    # TODO: Need to figure out notify calls
    return async_mock_service(hass, "notify", "notify.mock")


@pytest.mark.parametrize(("expected_lingering_timers"), [True])
async def test_nest_notification(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    template: Any,
    notify_calls: list[Event[Mapping[str, Any]]],
    subscriber: AsyncMock,
    auth: FakeAuth,
) -> None:
    """Collects model responses for area summaries."""
    # For setup
    expected_mock_calls = 2

    state = hass.states.get("automation.nest_doorbell_mobile_notification")
    assert state
    assert state.state == "on"
    assert state.attributes.get("last_triggered") is None

    now = datetime.datetime.now() + datetime.timedelta(hours=24)
    iso_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    aioclient_mock.post(
        PUSH_URL,
        json={
            "rateLimits": {
                "attempts": 1,
                "successful": 1,
                "errors": 0,
                "total": 1,
                "maximum": 150,
                "remaining": 149,
                "resetsAt": iso_time,
            }
        },
    )

    # For setup
    assert aioclient_mock.call_count == expected_mock_calls

    nest_event = Message.from_data(
        {
            "eventId": "some-event-id",
            "timestamp": utcnow().isoformat(timespec="seconds"),
            "resourceUpdate": {
                "name": NEST_DEVICE_NAME,
                "events": {
                    EventType.DOORBELL_CHIME: {
                        "eventSessionId": EVENT_SESSION_ID,
                        "eventId": EVENT_ID,
                    }
                },
            },
        },
    )
    await subscriber.async_receive_event(nest_event)
    await hass.async_block_till_done()

    assert hass.services.has_service("notify", "mobile_app_pixel")

    expected_mock_calls += 1
    assert aioclient_mock.call_count == expected_mock_calls
    data = aioclient_mock.mock_calls[expected_mock_calls - 1][2]["data"]
    assert data["group"] == "event.front_door_chime"
    assert data["tag"] == ENCODED_EVENT_ID
    assert "video" not in data
    assert "image" not in data

    # Verify automation is triggered
    state = hass.states.get("automation.nest_doorbell_mobile_notification")
    assert state
    assert state.state == "on"
    assert state.attributes.get("last_triggered") is not None

    # Publish media
    aioclient_mock.get(
        NEST_MEDIA_URL,
        content=b"image-bytes",
    )

    nest_event = Message.from_data(
        {
            "eventId": "some-event-id",
            "timestamp": utcnow().isoformat(timespec="seconds"),
            "resourceUpdate": {
                "name": NEST_DEVICE_NAME,
                "events": {
                    EventType.CAMERA_CLIP_PREVIEW: {
                        "eventSessionId": EVENT_SESSION_ID,
                        "previewUrl": NEST_MEDIA_URL,
                    }
                },
            },
        },
    )
    await subscriber.async_receive_event(nest_event)
    await hass.async_block_till_done()

    expected_mock_calls += 2
    assert aioclient_mock.call_count == expected_mock_calls
    data = aioclient_mock.mock_calls[expected_mock_calls - 1][2]["data"]
    assert data["group"] == "event.front_door_chime"
    assert data["tag"] == ENCODED_EVENT_ID
    assert data["image"]
    assert data["video"]
