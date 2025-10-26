from __future__ import annotations

# This file is part of ts_watcher.
#
# Developed for Vera C. Rubin Observatory Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
__all__ = ["MockPagerDuty"]

import os
import types
import typing
import uuid
from http import HTTPStatus

from aiohttp import web


def get_event_key() -> str:
    """Return a new unique request key."""
    return str(uuid.uuid4())


class MockPagerDuty:
    """A mock PagerDuty service to support Watcher escalation in unit tests.

    Parameters
    ----------
    port : `int`
        The TCP/IP port for the service. 0 to choose a free port.
        The default is 80 because that is what PagerDuty uses.

    Notes
    -----
    To use::

        async with MockPagerDuty(port=...) as server:
            # ... use the server

        # Or if you prefer explicit start/stop:

        server = MockPagerDuty(port=...)
        await server.start()
        # ... use the server
        await server.close()

    Known limitations:

    * At present this only supports event creation.
      We would probably want need add support for close and/or delete
      if we decide to use PagerDuty for the Watcher.
    * The events dict is never purged (though it would be if we add
      delete support). This is an explicit memory leak.

    Raises
    ------
    `RuntimeError`
        If env var ``ESCALATION_KEY`` not set.

    Attributes
    ----------
    port : `int`
        The port. The port argument, except if that was 0 then this is
        updated to the chosen port when `start` is run.
    url : `str`
        The root URL of the service. "" until `start` has run.
    escalation_key : `str`
        The value of env var ESCALATION_KEY.
    events : `dict` [`str`, `dict`]
        Dict of event ID: event data in PagerDuty's format.
        See ALLOWED_KEYS for the allowed keys; all values are str
        except "payload", which is a dict of [str, str].
        "payload" has the information about what went wrong;
        its keys are described in ALLOWED_PAYLOAD_KEYS.
    reject_next_request : `bool`
        If the user sets this true then the mock will reject the next request
        with `web.HTTPInternalServerError` and reset this flag. For unit tests.
    """

    ALLOWED_KEYS = frozenset(
        (
            "payload",
            "routing_key",
            "event_action",
            "dedup_key",
            "client",
            "client_url",
            "links",
            "images",
        )
    )

    ALLOWED_PAYLOAD_KEYS = frozenset(
        (
            "summary",
            "timestamp",
            "severity",
            "source",
            "component",
            "group",
            "class",
            "custom_details",
        )
    )

    def __init__(self, port: int = 80) -> None:
        self.port = port
        try:
            self.escalation_key = os.environ["ESCALATION_KEY"]
        except KeyError:
            raise RuntimeError("env variable ESCALATION_KEY must be set")
        self.events: dict[str, dict] = dict()
        self.url: str = ""
        self.reject_next_request = False
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def make_app(self) -> web.Application:
        """Make an instance of the web application."""
        app = web.Application()
        app.add_routes([web.post("/v2/enqueue", self.send_event)])
        return app

    async def start(self) -> None:
        """Start the service.

        Raises
        ------
        `RuntimeError`
            If port = 0 and serving on more than one socket
            (in which case the served port cannot be determined),
            or if this method has already been called.
        """
        if self._runner is not None:
            raise RuntimeError("Already started")
        app = self.make_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", port=self.port)
        await self._site.start()
        server = self._site._server
        if self.port == 0:
            if len(server.sockets) != 1:
                raise RuntimeError("Serving on more than one socket; cannot determine the port")
            self.port = server.sockets[0].getsockname()[1]  # type: ignore
        self.url = f"http://127.0.0.1:{self.port}"

    async def close(self) -> None:
        """Stop the service, if running."""
        if self._runner is not None:
            await self._runner.cleanup()

    def assert_authorized(self, routing_key: str) -> None:
        """Raise an error if self.reject_next_request true or not authorized.

        Always reset self.reject_next_request to False.

        Parameters
        ----------
        routing_key : `str`
            Routing key.

        Raises
        ------
        `web.HTTPInternalServerError`
            If self.reject_next_request True.
        `web.HTTPForbidden`
            If the request is not authorized.
        """
        if self.reject_next_request:
            self.reject_next_request = False
            raise web.HTTPInternalServerError(text="Failed by request: reject_next_request true")

        if routing_key != self.escalation_key:
            raise web.HTTPForbidden(text="Authorization key does not match")

    async def send_event(self, request: web.Request) -> web.json_response:
        """Request handler for "send event".

        Parameters
        ----------
        request : `aiohttp.web.Request`
            Request.
        """
        event_data = await request.json()
        self.assert_authorized(routing_key=event_data["routing_key"])
        try:
            extra_keys = event_data.keys() - self.ALLOWED_KEYS
            if extra_keys:
                raise RuntimeError(text=f"Unknown keys {sorted(extra_keys)}")

            action = event_data["event_action"]
            match action:
                case "trigger":
                    payload = event_data["payload"]
                    extra_payload_keys = payload.keys() - self.ALLOWED_PAYLOAD_KEYS
                    if extra_payload_keys:
                        raise RuntimeError(text=f"Unknown payload keys {sorted(extra_payload_keys)}")

                    event_key = get_event_key()
                    event_data["dedup_key"] = event_key
                    self.events[event_key] = event_data
                case "acknowledge" | "resolve":
                    event_key = event_data["dedup_key"]
                    event_data = self.events.get(event_key, None)
                    if event_data is not None:
                        event_data["event_action"] = action
                case _:
                    raise RuntimeError(text=f"Unsupported {action=}")
            return web.json_response(
                data=dict(
                    status="success",
                    dedup_key=event_key,
                    message="Event processed",
                ),
                status=HTTPStatus.ACCEPTED,
            )
        except Exception as e:
            raise web.HTTPBadRequest(text=str(e))

    async def __aenter__(self) -> MockPagerDuty:
        await self.start()
        return self

    async def __aexit__(
        self,
        type: None | typing.Type[BaseException],
        value: None | BaseException,
        traceback: None | types.TracebackType,
    ) -> None:
        await self.close()
