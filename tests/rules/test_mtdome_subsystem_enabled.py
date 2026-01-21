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

import pytest
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.MTDome import EnabledState
from lsst.ts.xml.enums.Watcher import AlarmSeverity
from lsst.ts.xml.sal_enums import State

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class MTDomeSubsystemEnabledTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_operation(self):
        salobj.set_test_topic_subname()

        # Only testing with the evt_azEnabled event but should work with the
        # other MTDome subsystem Enabled events as well.
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[
                dict(
                    classname="MTDomeSubsystemEnabled",
                    configs=[
                        {
                            "subsystem_name": "azimuth rotation",
                            "event_name": "evt_azEnabled",
                            "csc_state": ["ENABLED"],
                            "severity": "CRITICAL",
                        }
                    ],
                )
            ],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)
        async with (
            salobj.Controller(name="MTDome", index=0) as controller,
            watcher.Model(domain=controller.domain, config=watcher_config) as model,
        ):
            # The first item should not and the second item should raise an
            # alarm when the MTDome CSC is in ENABLED state.
            test_data_items = [
                {
                    "topic": controller.evt_azEnabled,
                    "fault_code": "",
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller.evt_azEnabled,
                    "fault_code": "Ethercat problem.",
                    "expected_severity": AlarmSeverity.CRITICAL,
                },
            ]

            rule_name = "MTDomeAzEnabled.MTDome"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()
            assert len(rule.remote_info_list) == 1

            await model.enable()

            num_telemetry = 0
            for csc_state in [State.DISABLED, State.ENABLED]:
                await watcher.write_and_wait(
                    model=model,
                    topic=controller.evt_summaryState,
                    summaryState=csc_state,
                )
                if csc_state == State.ENABLED:
                    # When switching the MTDome CSC from DISABLED to ENABLED,
                    # the rule triggers and will raise a CRITICAL alarm.
                    severity = await asyncio.wait_for(rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT)
                    assert severity == AlarmSeverity.CRITICAL

                for data_item in test_data_items:
                    num_telemetry += 1
                    await watcher.write_and_wait(
                        model=model,
                        topic=data_item["topic"],
                        state=EnabledState.ENABLED,
                        faultCode=data_item["fault_code"],
                    )
                    if num_telemetry == 2:
                        # With the MTDome CSC in DISABLED no alarms are
                        # triggered and the NONE alarm isn't raised despite of
                        # the AZ fault code.
                        with pytest.raises(TimeoutError):
                            severity = await asyncio.wait_for(
                                rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                            )
                    else:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )

                        if csc_state == State.DISABLED:
                            assert severity == AlarmSeverity.NONE
                        else:
                            assert severity == data_item["expected_severity"]
                            assert rule.alarm.severity_queue.empty()
