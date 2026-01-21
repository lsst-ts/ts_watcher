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
import logging
import types
import unittest

from lsst.ts import salobj, watcher
from lsst.ts.watcher.rules import ATeStop
from lsst.ts.xml.enums.Watcher import AlarmSeverity
from lsst.ts.xml.sal_enums import State

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class ATeStopTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_test_topic_subname()

    async def test_constructor(self):
        rule = ATeStop(config=None)
        assert len(rule.remote_info_list) == 1

    async def test_operation(self):
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="ATeStop", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="ATPneumatics", index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            test_data_items = [False, True]

            rule_name = "eStop.ATPneumatics"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            for csc_state in [State.DISABLED, State.ENABLED]:
                await watcher.write_and_wait(
                    model=model,
                    topic=controller.evt_summaryState,
                    summaryState=csc_state,
                )
                for data_item in test_data_items:
                    await watcher.write_and_wait(model=model, topic=controller.evt_eStop, triggered=data_item)
                    if (csc_state == State.DISABLED and data_item is False) or (
                        csc_state == State.ENABLED and data_item is True
                    ):
                        logging.debug(f"{csc_state=}, {data_item=}")
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                        assert (
                            severity == AlarmSeverity.NONE
                            if csc_state == State.DISABLED and data_item is False
                            else AlarmSeverity.CRITICAL
                        )
