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
import datetime
import logging
import types
import unittest
from unittest import mock

import pytest

from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTMountAzimuthTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(salobj, "set_random_topic_subname"):
            salobj.set_random_topic_subname()
        else:
            salobj.set_random_lsst_dds_partition_prefix()
        self.rule_config_dict = {
            "time_range_start": 7,
            "time_range_end": 12,
            "mtmount_azimuth_low_threshold": 0.0,
            "mtmount_azimuth_high_threshold": 180.0,
        }
        self.log = logging.getLogger("MTMountAzimuthTestCase")

    async def test_constructor(self):
        config = watcher.rules.MTMountAzimuth.make_config(**self.rule_config_dict)
        rule = watcher.rules.MTMountAzimuth(config=config, log=self.log)

        assert rule.name == "MTMountAzimuth"
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 2

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTMountAzimuth", configs=[self.rule_config_dict])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="MTDome", index=0) as mtdome,
            salobj.Controller(name="MTMount", index=0) as mtmount,
            watcher.Model(domain=mtdome.domain, config=watcher_config) as model,
        ):
            rule: watcher.rules.MTMountAzimuth = model.rules["MTMountAzimuth"]

            # Patch the `get_now_utc` method of the rule so the test can
            # control the time.
            get_now_utc = mock.MagicMock()
            rule.get_now_utc = get_now_utc

            rule.alarm.init_severity_queue()
            await model.enable()
            rule.stop()

            # Test outside of the configured time range.
            get_now_utc.return_value = datetime.time(hour=5, tzinfo=datetime.UTC)
            await watcher.write_and_wait(
                model=model,
                topic=mtdome.tel_apertureShutter,
                positionActual=[0.0, 0.0],
            )
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.NONE

            # Make sure that we are inside the alarm time range.
            get_now_utc.return_value = datetime.time(hour=8, tzinfo=datetime.UTC)
            await watcher.write_and_wait(
                model=model,
                topic=mtdome.tel_apertureShutter,
                positionActual=[0.0, 0.0],
            )
            # The alarm doesn't change so no new alarm raised.
            with pytest.raises(TimeoutError):
                severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

            # Make sure that the aperture shutter is open.
            get_now_utc.return_value = datetime.time(hour=8, tzinfo=datetime.UTC)
            await watcher.write_and_wait(
                model=model,
                topic=mtdome.tel_apertureShutter,
                positionActual=[10.0, 10.0],
            )
            # The alarm doesn't change so no new alarm raised.
            with pytest.raises(TimeoutError):
                severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)

            # Make sure that the MTMount is in the azimuth range.
            await watcher.write_and_wait(model=model, topic=mtmount.tel_azimuth, actualPosition=10.0)
            # Now there should be a serious alarm.
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.SERIOUS

            # Make sure that the aperture shutter is closed.
            get_now_utc.return_value = datetime.time(hour=8, tzinfo=datetime.UTC)
            await watcher.write_and_wait(
                model=model,
                topic=mtdome.tel_apertureShutter,
                positionActual=[0.0, 0.0],
            )
            # Now there should be a warning alarm.
            severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
            assert severity == AlarmSeverity.WARNING
