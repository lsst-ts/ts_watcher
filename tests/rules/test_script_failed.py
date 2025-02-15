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
import dataclasses
import types
import unittest

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Script import ScriptState
from lsst.ts.xml.enums.ScriptQueue import ScriptProcessState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


@dataclasses.dataclass
class CallTestParams:
    """Params for test_call.

    The name does not start with "Test" to avoid a warning.
    """

    queue_enabled: bool
    queue_running: bool
    current_script_sal_index: int
    script_sal_index: int
    process_state: ScriptProcessState
    script_state: ScriptState
    expected_severity: list[AlarmSeverity]
    description: str


class ScriptFailedTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_basics(self):
        schema = watcher.rules.ScriptFailed.get_schema()
        assert schema is not None
        index = 1
        config = watcher.rules.ScriptFailed.make_config(index=1)
        desired_rule_name = f"ScriptFailed.ScriptQueue:{index}"

        rule = watcher.rules.ScriptFailed(config=config)
        assert rule.name == desired_rule_name
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == "ScriptQueue"
        assert remote_info.index == index
        assert rule.name in repr(rule)
        assert "ScriptFailed" in repr(rule)

    async def test_call(self):
        index = 1

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: ScriptFailed
              configs:
              - index: {index}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name="ScriptQueue", index=index) as script_queue:
            async with watcher.Model(
                domain=script_queue.domain, config=watcher_config
            ) as model:
                await model.enable()

                assert len(model.rules) == 1
                rule_name = f"ScriptFailed.ScriptQueue:{index}"
                rule = model.rules[rule_name]
                rule.alarm.init_severity_queue()

                severity_1 = None
                for test_params in self.get_test_call_params():
                    await script_queue.evt_queue.set_write(
                        enabled=test_params.queue_enabled,
                        running=test_params.queue_running,
                        currentSalIndex=test_params.script_sal_index,
                    )

                    try:
                        severity = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        if severity_1 is None:
                            raise
                    else:
                        severity_1 = severity

                    await script_queue.evt_script.set_write(
                        scriptSalIndex=test_params.script_sal_index,
                        processState=test_params.process_state,
                        scriptState=test_params.script_state,
                    )

                    # if severity_2 = severity_1 alarm won't change and
                    # retrieving it will timeout
                    severity_2 = severity_1
                    try:
                        severity_2 = await asyncio.wait_for(
                            rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        pass

                    # This will publish 2 alarm states for each set of test
                    # parameters: one for the queue ScriptQueue event, the next
                    # for the script ScriptQueue event.
                    for expected_severity, severity in zip(
                        test_params.expected_severity, [severity_1, severity_2]
                    ):
                        with self.subTest(
                            description=test_params.description,
                            expected_severity=expected_severity,
                        ):
                            assert severity == expected_severity
                    assert rule.alarm.severity_queue.empty()

    def get_test_call_params(self):
        return [
            CallTestParams(
                queue_enabled=True,
                queue_running=True,
                current_script_sal_index=1000,
                script_sal_index=1000,
                process_state=ScriptProcessState.RUNNING,
                script_state=ScriptState.RUNNING,
                expected_severity=[AlarmSeverity.NONE, AlarmSeverity.NONE],
                description="Current Script is running.",
            ),
            CallTestParams(
                queue_enabled=True,
                queue_running=True,
                current_script_sal_index=1001,
                script_sal_index=1001,
                process_state=ScriptProcessState.DONE,
                script_state=ScriptState.DONE,
                expected_severity=[AlarmSeverity.NONE, AlarmSeverity.NONE],
                description="Current Script completed successfully.",
            ),
            CallTestParams(
                queue_enabled=True,
                queue_running=False,
                current_script_sal_index=1002,
                script_sal_index=1002,
                process_state=ScriptProcessState.DONE,
                script_state=ScriptState.FAILED,
                expected_severity=[AlarmSeverity.NONE, AlarmSeverity.WARNING],
                description="Current Script failed",
            ),
            CallTestParams(
                queue_enabled=True,
                queue_running=True,
                current_script_sal_index=1003,
                script_sal_index=1004,
                process_state=ScriptProcessState.RUNNING,
                script_state=ScriptState.FAILED,
                expected_severity=[AlarmSeverity.NONE, AlarmSeverity.NONE],
                description="A different Script failed.",
            ),
        ]
