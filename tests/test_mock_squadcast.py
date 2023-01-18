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

import unittest
import uuid
from http import HTTPStatus

import aiohttp

from lsst.ts import utils
from lsst.ts import watcher


class MockSquadCastTestCase(unittest.IsolatedAsyncioTestCase):
    def run(self, result=None):
        with utils.modify_environ(ESCALATION_KEY="arbitrary string"):
            super().run(result)

    async def asyncSetUp(self):
        self.server = watcher.MockSquadCast(port=0)
        self.http_client = aiohttp.ClientSession()
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.close()
        await self.http_client.close()

    async def resolve_incident(self, event_id):
        """Create an incident and test that it was correctly created.

        Return the incident as a dict.

        Parameters
        ----------
        event_id : `str`
            event_id of incident.
        """
        data = dict(
            event_id=event_id,
            status="resolve",
        )
        async with self.http_client.post(
            url=self.server.endpoint_url,
            json=data,
        ) as response:
            assert response.status == HTTPStatus.ACCEPTED

    async def trigger_incident(
        self,
        message="Alert message",
        description="Alert description",
        alarm_name="Enabled.ScriptQueue:1",
        responder="watcher team",
        reject_request=False,
    ):
        """Create an incident and test that it was correctly created.

        Parameters
        ----------
        message : `str`
            Message for the incident
        description : `str`
            Description for the incident
        alarm_name : `str`
            Alarm name.
        responder : 'str'
            Message responder.
        reject_request : `bool`
            Should SquadCast reject the request?

        Returns
        -------
        incident : `dict` | `None`
            The incident, if created, else None
        """
        if reject_request:
            expected_status = HTTPStatus.INTERNAL_SERVER_ERROR
        else:
            expected_status = HTTPStatus.ACCEPTED

        event_id = str(uuid.uuid4())
        data = dict(
            message=message,
            description=description,
            tags=dict(
                alarm_name=alarm_name,
                responder=responder,
            ),
            event_id=event_id,
            status="trigger",
        )
        if reject_request:
            self.server.reject_next_request = True
        async with self.http_client.post(
            url=self.server.endpoint_url,
            json=data,
        ) as response:
            assert response.status == expected_status
            if expected_status != HTTPStatus.ACCEPTED:
                return None
        assert not self.server.reject_next_request

        incident = self.server.incidents[event_id]
        assert incident["event_id"] == event_id
        return incident

    async def test_trigger_incident(self):
        num_incidents = 10
        kwargs_list = []
        for i in range(num_incidents):
            kwargs = dict(
                message=f"Message text {i}",
                description=f"Message description {i}",
                alarm_name=f"Enabled.ESS:{i}",
                responder=f"Responder {i}",
            )

            kwargs_list.append(kwargs)
            await self.trigger_incident(**kwargs)
            assert len(self.server.incidents) == i + 1
        assert len(kwargs_list) == num_incidents

        # Rejecting the create request should prevent incident creation
        await self.trigger_incident(reject_request=True)
        assert len(self.server.incidents) == num_incidents

        # Now check that we have exactly the expected incidents
        for kwargs, incident in zip(kwargs_list, self.server.incidents.values()):
            for arg in ("message", "description"):
                assert incident[arg] == kwargs[arg]
            for tag_name in ("alarm_name", "responder"):
                assert incident["tags"][tag_name] == kwargs[tag_name]

    async def test_resolve_incident(self):
        # Delete 1 of several incidents
        num_incidents = 3  # an arbitrary smallish integer > 1
        for i in range(num_incidents):
            incident = await self.trigger_incident()
            assert incident is not None
            if i == 1:
                event_id_to_resolve = incident["event_id"]
        assert len(self.server.incidents) == num_incidents
        for incident in self.server.incidents.values():
            assert incident["status"] == "trigger"

        # First try various ways the request can fail;
        # these should not affect the incidents
        bad_event_id = "no such incident"
        await self.resolve_incident(event_id=bad_event_id)
        assert len(self.server.incidents) == num_incidents
        for incident in self.server.incidents.values():
            assert incident["status"] == "trigger"

        await self.resolve_incident(event_id=event_id_to_resolve)
        assert len(self.server.incidents) == num_incidents
        for incident in self.server.incidents.values():
            if incident["event_id"] == event_id_to_resolve:
                assert incident["status"] == "resolve"
            else:
                assert incident["status"] == "trigger"
