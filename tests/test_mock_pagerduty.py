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

import copy
import datetime
import os
import unittest
from http import HTTPStatus

import aiohttp

from lsst.ts import utils
from lsst.ts import watcher


class MockPagerDutyTestCase(unittest.IsolatedAsyncioTestCase):
    def run(self, result=None):
        with utils.modify_environ(ESCALATION_KEY="arbitrary string"):
            super().run(result)

    async def asyncSetUp(self):
        self.server = watcher.MockPagerDuty(port=0)
        self.http_client = aiohttp.ClientSession()
        self.escalation_key = os.environ["ESCALATION_KEY"]
        await self.server.start()
        self.send_event_url = f"{self.server.url}/v2/enqueue"

    async def asyncTearDown(self):
        await self.server.close()

    async def create_event(
        self,
        summary="Event summary",
        description="Event description",
        source="Source",
        component="Component",
        group="Group",
        headers=None,
        reject_request=False,
    ):
        """Create an event and test that it was correctly created.

        Return the event as a dict.

        Parameters
        ----------
        summary : `str`, optional
            Brief description of the event.
        description : `str`, optional
            Full description of the event.
        source : `str`, optional
            Source of event. Perhaps the Watcher alarm name?
        component : `str`, optional
            Component.
        group : `str`, optional
            Logical group to which the component belongs.
        reject_request : `bool`, optional
            Should PagerDuty reject the request?

        Returns
        -------
        The event (as a dict), if created, else None.
        """
        if reject_request:
            expected_status = HTTPStatus.INTERNAL_SERVER_ERROR
        else:
            expected_status = HTTPStatus.ACCEPTED

        data = dict(
            payload=dict(
                summary=summary,
                timestamp=datetime.datetime.now().isoformat(),
                severity="critical",
                source=source,
                component=component,
                group=group,
                custom_details=dict(description=description),
            ),
            routing_key=self.escalation_key,
            event_action="trigger",
            client="Watcher",
        )
        if reject_request:
            self.server.reject_next_request = True
        async with self.http_client.post(
            url=self.send_event_url,
            json=data,
            headers=headers,
        ) as response:
            assert response.status == expected_status
            if expected_status != HTTPStatus.ACCEPTED:
                return None
            response_data = await response.json()
        assert not self.server.reject_next_request

        event_id = response_data["dedup_key"]
        event = self.server.events[event_id]
        assert event["dedup_key"] == event_id
        for key, value in data.items():
            assert event[key] == value
        assert event["event_action"] == "trigger"
        return event

    async def test_create_event(self):
        NumEvents = 10
        kwargs_list = []
        for i in range(NumEvents):
            kwargs = dict(
                summary=f"Message text {i}",
                description=f"Message description {i}",
            )

            kwargs_list.append(kwargs)
            await self.create_event(**kwargs)
            assert len(self.server.events) == i + 1
        assert len(kwargs_list) == NumEvents

        # Rejecting the create request should prevent event creation
        await self.create_event(reject_request=True)
        assert len(self.server.events) == NumEvents

        # Now check that we have exactly the expected events
        for kwargs, event in zip(kwargs_list, self.server.events.values()):
            payload = event["payload"]
            assert payload["summary"] == kwargs["summary"]
            assert payload["custom_details"]["description"] == kwargs["description"]
            assert event["event_action"] == "trigger"

    async def test_acknowledge_event(self):
        await self.check_acknowledge_or_resolve_event(action="acknowledge")

    async def test_resolve_event(self):
        await self.check_acknowledge_or_resolve_event(action="resolve")

    async def test_unsupported_action(self):
        await self.check_acknowledge_or_resolve_event(action="no_such_action")

    async def check_acknowledge_or_resolve_event(self, action):
        """Check acknowledge or resolve event.

        Parameters
        ----------
        action : `str`
            The desired action. Should be "acknowledge" or "resolve"
        """
        event = await self.create_event()
        assert event is not None
        event_id = event["dedup_key"]
        kwargs = dict(
            url=self.send_event_url,
            json=dict(
                routing_key=self.escalation_key,
                dedup_key=event_id,
                event_action=action,
            ),
        )

        # Fail: tell the mock client to reject the next request,
        # even though it is valid.
        self.server.reject_next_request = True
        async with self.http_client.post(**kwargs) as response:
            assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
        event = self.server.events[event_id]
        assert event["event_action"] == "trigger"

        # Fail: bad URL.
        bad_kwargs = copy.deepcopy(kwargs)
        bad_kwargs["url"] = f"{self.server.url}/no_such_location"
        async with self.http_client.post(**bad_kwargs) as response:
            assert response.status == HTTPStatus.NOT_FOUND
        assert event["event_action"] == "trigger"

        # Fail: not authorized (incorrect routing key).
        bad_kwargs = copy.deepcopy(kwargs)
        bad_kwargs["json"]["routing_key"] = "Incorrect key"
        async with self.http_client.post(**bad_kwargs) as response:
            assert response.status == HTTPStatus.FORBIDDEN
        assert event["event_action"] == "trigger"

        # Send the specified action correctly.
        if action in {"acknowledge", "resolve"}:
            async with self.http_client.post(**kwargs) as response:
                assert response.status == HTTPStatus.ACCEPTED
            event = self.server.events[event_id]
            assert event["event_action"] == action
        else:
            async with self.http_client.post(**kwargs) as response:
                assert response.status == HTTPStatus.BAD_REQUEST
