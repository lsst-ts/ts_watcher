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

import asyncio
import types
import unittest

import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


class MTCCWFollowingRotatorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_basics(self):
        schema = watcher.rules.MTCCWFollowingRotator.get_schema()
        assert schema is None

        rule = watcher.rules.MTCCWFollowingRotator(config=None)
        assert rule.name == "MTCCWFollowingRotator"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "MTMount"
        assert remote_info.index == 0

    async def test_call(self):
        watcher_config_dict = yaml.safe_load(
            """
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: MTCCWFollowingRotator
              configs:
              - {}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name="MTMount", index=0) as controller:
            async with watcher.Model(
                domain=controller.domain, config=watcher_config
            ) as model:
                model.enable()

                self.assertEqual(len(model.rules), 1)
                rule = model.rules["MTCCWFollowingRotator"]

                read_severities = []

                def alarm_callback(alarm):
                    nonlocal read_severities
                    read_severities.append(alarm.severity)

                rule.alarm.callback = alarm_callback

                expected_severities = []
                for following_enabled in (False, True, False, True, False):
                    if following_enabled:
                        expected_severities.append(AlarmSeverity.NONE)
                    else:
                        expected_severities.append(AlarmSeverity.WARNING)

                    controller.evt_cameraCableWrapFollowing.set_put(
                        enabled=following_enabled, force_output=True
                    )
                    # give the remote a chance to read the data
                    await asyncio.sleep(0.001)

                self.assertEqual(read_severities, expected_severities)
