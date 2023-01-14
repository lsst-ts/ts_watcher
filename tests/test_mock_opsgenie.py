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

import os
import unittest
from http import HTTPStatus

import aiohttp

from lsst.ts import utils
from lsst.ts import watcher


class MockOpsGenieTestCase(unittest.IsolatedAsyncioTestCase):
    def run(self, result=None):
        with utils.modify_environ(ESCALATION_KEY="arbitrary string"):
            super().run(result)

    async def asyncSetUp(self):
        self.server = watcher.MockOpsGenie(port=0)
        self.http_client = aiohttp.ClientSession()
        self.escalation_key = os.environ["ESCALATION_KEY"]
        self.headers = dict(Authorization=f"GenieKey {self.escalation_key}")
        self.bad_headers_list = [
            dict(),
            dict(Authorization="GenieKey"),
            dict(Authorization=f"NotGenieKey {self.escalation_key}"),
            dict(Authorization=f"GenieKey extra-{self.escalation_key}"),
        ]
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.close()

    async def create_alert(
        self,
        message="Alert message",
        description="Alert description",
        responders=None,
        headers=None,
        reject_request=False,
    ):
        """Create an alert and test that it was correctly created.

        Return the alert as a dict.

        Parameters
        ----------
        message : `str`
            Message for the alert
        description : `str`
            Description for the alert
        responders : `None` | `dict`
            Message responders as a list of dicts.
            Each dict has two keys, which are often "name" and "type"
            (but OpsGenie accepts other values, as well).
            If None then use [{"id": "Responder ID", "name": "team"}].
        headers : `None` | `dict`
            The headers to send. If None then send self.headers.
            Any value other than None or self.headers is assumed
            to result in the request being rejected.
        reject_request : `bool`
            Should OpsGenie reject the request?

        Returns
        -------
        The alert (as a dict), if created, else None.
        """
        if headers is None:
            headers = self.headers
        if reject_request:
            expected_status = HTTPStatus.INTERNAL_SERVER_ERROR
        elif headers == self.headers:
            expected_status = HTTPStatus.ACCEPTED
        else:
            expected_status = HTTPStatus.FORBIDDEN

        if responders is None:
            responders = [dict(id="Responder ID", type="team")]
        data = dict(
            message=message,
            description=description,
            responders=responders,
        )
        if reject_request:
            self.server.reject_next_request = True
        async with self.http_client.post(
            url=self.server.url,
            json=data,
            headers=headers,
        ) as response:
            assert response.status == expected_status
            if expected_status != HTTPStatus.ACCEPTED:
                return None
            response_data = await response.json()
        assert not self.server.reject_next_request

        alert_id = response_data["requestId"]
        alert = self.server.alerts[alert_id]
        assert alert["id"] == alert_id
        for key, value in data.items():
            assert alert[key] == value
        assert alert["status"] == "open"
        return alert

    async def test_create_alert(self):
        NumAlerts = 10
        kwargs_list = []
        for i in range(NumAlerts):
            kwargs = dict(
                message=f"Message text {i}",
                description=f"Message description {i}",
                responders=[
                    dict(name=f"Responder_user_{i}@host", type="user"),
                    dict(name=f"Responder team {i}", type="team"),
                ],
            )

            kwargs_list.append(kwargs)
            await self.create_alert(**kwargs)
            assert len(self.server.alerts) == i + 1
        assert len(kwargs_list) == NumAlerts

        # Bad headers should prevent alert creation
        for bad_headers in self.bad_headers_list:
            await self.create_alert(headers=bad_headers)
        assert len(self.server.alerts) == NumAlerts

        # Rejecting the create request should prevent alert creation
        await self.create_alert(reject_request=True)
        assert len(self.server.alerts) == NumAlerts

        # Now check that we have exactly the expected alerts
        for kwargs, alert in zip(kwargs_list, self.server.alerts.values()):
            assert alert["message"] == kwargs["message"]
            assert alert["description"] == kwargs["description"]
            assert alert["responders"] == kwargs["responders"]
            assert alert["status"] == "open"

    async def test_close_alert(self):
        alert = await self.create_alert()
        assert alert is not None
        alert_id = alert["id"]
        kwargs = dict(
            url=f"{self.server.url}/:{alert_id}/close",
            json=dict(),
        )

        # First try various ways the request can fail;
        # these should not affect the alert
        self.server.reject_next_request = True
        async with self.http_client.post(**kwargs, headers=self.headers) as response:
            assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
        alert = self.server.alerts[alert_id]
        assert alert["status"] == "open"

        for bad_headers in self.bad_headers_list:
            async with self.http_client.post(**kwargs, headers=bad_headers) as response:
                assert response.status == HTTPStatus.FORBIDDEN
        assert alert["status"] == "open"

        bad_id_kwargs = kwargs.copy()
        bad_id_kwargs["url"] = f"{self.server.url}/:no_such_id/close"
        async with self.http_client.post(
            **bad_id_kwargs, headers=self.headers
        ) as response:
            # This returns ACCEPTED instead of some kind of error,
            # because that is how the real OpsGenie is documented to work.
            assert response.status == HTTPStatus.ACCEPTED
        assert alert["status"] == "open"

        # Now close the alert properly
        async with self.http_client.post(**kwargs, headers=self.headers) as response:
            assert response.status == HTTPStatus.ACCEPTED
            response_data = await response.json()
        # The close request should have a different ID
        # than the create request.
        assert response_data["requestId"] != alert_id
        alert = self.server.alerts[alert_id]
        assert alert["status"] == "closed"

    async def test_delete_alert(self):
        # Delete 1 of several alerts
        NumAlerts = 3
        for i in range(NumAlerts):
            alert = await self.create_alert()
            assert alert is not None
            if i == 1:
                alert_id_to_delete = alert["id"]
        assert len(self.server.alerts) == NumAlerts
        kwargs = dict(
            url=f"{self.server.url}/:{alert_id_to_delete}",
            json=dict(),
        )

        # First try various ways the request can fail;
        # these should not affect the alerts
        self.server.reject_next_request = True
        async with self.http_client.delete(**kwargs, headers=self.headers) as response:
            assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert len(self.server.alerts) == NumAlerts

        for bad_headers in self.bad_headers_list:
            async with self.http_client.delete(
                **kwargs, headers=bad_headers
            ) as response:
                assert response.status == HTTPStatus.FORBIDDEN
        assert len(self.server.alerts) == NumAlerts

        bad_id_kwargs = kwargs.copy()
        bad_id_kwargs["url"] = f"{self.server.url}/:no_such_id"
        async with self.http_client.delete(
            **bad_id_kwargs, headers=self.headers
        ) as response:
            # This returns ACCEPTED instead of some kind of error,
            # because that is how the real OpsGenie is documented to work.
            assert response.status == HTTPStatus.ACCEPTED
        assert len(self.server.alerts) == NumAlerts

        for alert in self.server.alerts.values():
            assert alert["status"] == "open"

        async with self.http_client.delete(**kwargs, headers=self.headers) as response:
            assert response.status == HTTPStatus.ACCEPTED
            response_data = await response.json()
        # The delete request should have a different ID
        # than the create request.
        assert response_data["requestId"] != alert_id_to_delete
        assert alert_id_to_delete not in self.server.alerts
        assert len(self.server.alerts) == NumAlerts - 1
        for alert in self.server.alerts.values():
            assert alert["status"] == "open"
