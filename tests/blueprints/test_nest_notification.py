"""Tests for the nest notification automations."""

import uuid
import shutil
from asyncio import AbstractEventLoop
import pathlib
import logging
import datetime
import copy
from typing import Any
from collections.abc import Mapping, Awaitable, Callable, Generator
from unittest.mock import patch

import pytest
import yaml
import aiohttp

from google_nest_sdm.auth import AbstractAuth
from google_nest_sdm.device import Device
from google_nest_sdm.device_manager import DeviceManager
from google_nest_sdm.event import EventMessage, EventType
from google_nest_sdm.event_media import CachePolicy
from google_nest_sdm.traits import TraitType
from google_nest_sdm.google_nest_subscriber import GoogleNestSubscriber

from homeassistant.core import HomeAssistant, Event, ServiceCall
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.components.application_credentials import (
    async_import_client_credential,
    ClientCredential,
)
from homeassistant.util.dt import utcnow
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
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
NEST_CONFIG_ENTRY_DATA = {
    "sdm": {},
    "project_id": "a",
    "cloud_project_id": "b",
    "subscriber_id": "c",
    "auth_implementation": "imported-cred",
    "token": {
        "access_token": "some-token",
        "expires_at": (datetime.datetime.now() + datetime.timedelta(days=7)).timestamp()
    }
}
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


class FakeSubscriber(GoogleNestSubscriber):
    """Fake subscriber that supplies a FakeDeviceManager."""

    stop_calls = 0

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        """Initialize Fake Subscriber."""
        self._device_manager = DeviceManager()

    def set_update_callback(self, target: Callable[[EventMessage], Awaitable[None]]):
        """Capture the callback set by Home Assistant."""
        self._device_manager.set_update_callback(target)

    async def create_subscription(self):
        """Create the subscription."""
        return

    async def delete_subscription(self):
        """Delete the subscription."""
        return

    async def start_async(self):
        """Return the fake device manager."""
        return self._device_manager

    async def async_get_device_manager(self) -> DeviceManager:
        """Return the fake device manager."""
        return self._device_manager

    @property
    def cache_policy(self) -> CachePolicy:
        """Return the cache policy."""
        return self._device_manager.cache_policy

    def stop_async(self):
        """No-op to stop the subscriber."""
        self.stop_calls += 1

    async def async_receive_event(self, event_message: EventMessage):
        """Simulate a received pubsub message, invoked by tests."""
        # Update device state, then invoke HomeAssistant to refresh
        await self._device_manager.async_handle_event(event_message)


class CreateDevice:
    """Fixture used for creating devices."""

    def __init__(
        self,
        device_manager: DeviceManager,
        auth: AbstractAuth,
    ) -> None:
        """Initialize CreateDevice."""
        self.device_manager = device_manager
        self.auth = auth
        self.data = {"traits": {}}

    def create(
        self,
        raw_traits: dict[str, Any] | None = None,
        raw_data: dict[str, Any] | None = None,
    ) -> None:
        """Create a new device with the specifeid traits."""
        data = copy.deepcopy(self.data)
        data.update(raw_data if raw_data else {})
        data["traits"].update(raw_traits if raw_traits else {})
        self.device_manager.add_device(Device.MakeDevice(data, auth=self.auth))


class FakeAuth(AbstractAuth):
    """A fake implementation of the auth class that records requests.

    This class captures the outgoing requests, and can also be used by
    tests to set up fake responses.  This class is registered as a response
    handler for a fake aiohttp_server and can simulate successes or failures
    from the API.
    """

    def __init__(self) -> None:
        """Initialize FakeAuth."""
        super().__init__(None, None)
        # Tests can set fake responses here.
        self.responses = []
        # The last request is recorded here.
        self.captured_requests = []
        # Set up by fixture
        self.client = None

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        return ""

    async def request(self, method, url, **kwargs):
        """Capure the request arguments for tests to assert on."""
        self.captured_requests.append((method, url))
        return await self.client.get("/")

    async def response_handler(self, request):
        """Handle fake responess for aiohttp_server."""
        if len(self.responses) > 0:
            return self.responses.pop(0)
        return aiohttp.web.json_response()


@pytest.fixture
def aiohttp_client(
    event_loop: AbstractEventLoop,
    aiohttp_client: ClientSessionGenerator,
    socket_enabled: None,
) -> ClientSessionGenerator:
    """Return aiohttp_client and allow opening sockets."""
    return aiohttp_client


@pytest.fixture
async def auth(aiohttp_client: ClientSessionGenerator) -> FakeAuth:
    """Fixture for an AbstractAuth."""
    auth = FakeAuth()
    app = aiohttp.web.Application()
    app.router.add_get("/", auth.response_handler)
    app.router.add_post("/", auth.response_handler)
    auth.client = await aiohttp_client(app)
    return auth


@pytest.fixture
def subscriber() -> Generator[FakeSubscriber, None, None]:
    """Set up the FakeSusbcriber."""
    subscriber = FakeSubscriber()
    with patch(
        "homeassistant.components.nest.api.GoogleNestSubscriber",
        return_value=subscriber,
    ):
        yield subscriber


@pytest.fixture
async def create_device(
    subscriber: FakeSubscriber,
    auth: FakeAuth,
) -> CreateDevice:
    """Fixture for creating devices."""
    device_manager = await subscriber.async_get_device_manager()
    return CreateDevice(device_manager, auth)


@pytest.fixture(autouse=True)
async def mock_default_components(hass: HomeAssistant) -> None:
    """Fixture to setup required default components."""
    assert await async_setup_component(hass, "homeassistant", {})
    # assert await async_setup_component(hass, "ffmpeg", {})
    assert await async_setup_component(hass, "application_credentials", {})


@pytest.fixture(name="nest")
async def mock_nest(
    hass: HomeAssistant, create_device: CreateDevice, subscriber: FakeSubscriber
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


# @pytest.fixture(name="notify")
# async def mock_notify(hass: HomeAssistant) -> MockConfigEntry:
#     assert await async_setup_component(hass, "notify", {"notify": {"platform": "demo"}})


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
    subscriber: FakeSubscriber,
    auth: FakeAuth,
) -> None:
    """Collects model responses for area summaries."""

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

    assert aioclient_mock.call_count == 0

    nest_event = EventMessage.create_event(
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
        auth=None,
    )
    await subscriber.async_receive_event(nest_event)
    await hass.async_block_till_done()

    assert hass.services.has_service("notify", "mobile_app_pixel")

    assert aioclient_mock.call_count == 1
    data = aioclient_mock.mock_calls[0][2]["data"]
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
        content="image-bytes",
    )

    nest_event = EventMessage.create_event(
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
        auth=None,
    )
    await subscriber.async_receive_event(nest_event)
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 2
    data = aioclient_mock.mock_calls[1][2]["data"]
    assert data["group"] == "event.front_door_chime"
    assert data["tag"] == ENCODED_EVENT_ID
    assert data["image"]
    assert data["video"]
