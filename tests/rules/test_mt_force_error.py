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

from lsst.ts import salobj, watcher
from lsst.ts.watcher.rules import MTForceError
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)


class TestData:

    def __init__(
        self,
        lut_gravity: list[float],
        lut_temperature: list[float],
        applied: list[float],
        measured: list[float],
        hardpoint_correction: list[float],
    ) -> None:
        self.lutGravity = lut_gravity
        self.lutTemperature = lut_temperature
        self.applied = applied
        self.measured = measured
        self.hardpointCorrection = hardpoint_correction


class MTForceErrorTestCase(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_constructor(self) -> None:

        schema = watcher.rules.MTForceError.get_schema()
        assert schema is not None

        rule = MTForceError(None)
        assert len(rule.remote_info_list) == 2
        assert len(rule.remote_info_list[0].poll_names) == 2
        assert len(rule.remote_info_list[1].poll_names) == 2

    async def test_operation(self) -> None:
        watcher_config_dict = dict(
            disabled_sal_components=[],
            auto_acknowledge_delay=3600,
            auto_unacknowledge_delay=3600,
            rules=[dict(classname="MTForceError", configs=[{}])],
            escalation=(),
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller("MTM2", 0) as controller_m2, salobj.Controller(
            "MTMount", 0
        ) as controller_mtmount, watcher.Model(
            domain=controller_m2.domain, config=watcher_config
        ) as model:

            rule_name = "MTForceError.MTM2"
            rule = model.rules[rule_name]
            rule.alarm.init_severity_queue()

            await model.enable()

            # 72 axial actuators and 6 tangent links
            hardpoint_correction_axial = [1.0] * 72
            hardpoint_correction_tangent = [1.0] * 6
            test_data_items = [
                {
                    "topic": controller_m2.tel_axialForce,
                    "fields": {
                        "measured": [0.0] * 72,
                        "hardpointCorrection": hardpoint_correction_axial,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller_mtmount.tel_azimuth,
                    "fields": {
                        "actualAcceleration": rule.config.threshold_mtmount_acceleration,
                    },
                },
                {
                    "topic": controller_m2.tel_axialForce,
                    "fields": {
                        "measured": [100.0] * 72,
                        "hardpointCorrection": hardpoint_correction_axial,
                    },
                    "expected_severity": AlarmSeverity.SERIOUS,
                },
                {
                    "topic": controller_m2.tel_axialForce,
                    "fields": {
                        "measured": [100.0] * 10 + [0.0] * 62,
                        "hardpointCorrection": hardpoint_correction_axial,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller_mtmount.tel_elevation,
                    "fields": {
                        "actualAcceleration": rule.config.threshold_mtmount_acceleration,
                    },
                },
                {
                    "topic": controller_m2.tel_tangentForce,
                    "fields": {
                        "measured": [100.0] * 6,
                        "hardpointCorrection": hardpoint_correction_tangent,
                    },
                    "expected_severity": AlarmSeverity.SERIOUS,
                },
                {
                    "topic": controller_m2.tel_tangentForce,
                    "fields": {
                        "measured": [100.0] * 2 + [0.0] * 4,
                        "hardpointCorrection": hardpoint_correction_tangent,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
                {
                    "topic": controller_m2.tel_tangentForce,
                    "fields": {
                        "measured": [100.0] * 6,
                        "hardpointCorrection": hardpoint_correction_tangent,
                    },
                    "expected_severity": AlarmSeverity.SERIOUS,
                },
                {
                    "topic": controller_mtmount.tel_elevation,
                    "fields": {
                        "actualAcceleration": -rule.config.threshold_mtmount_acceleration
                        - 1.0,
                    },
                },
                {
                    "topic": controller_m2.tel_tangentForce,
                    "fields": {
                        "measured": [100.0] * 6,
                        "hardpointCorrection": hardpoint_correction_tangent,
                    },
                    "expected_severity": AlarmSeverity.NONE,
                },
            ]

            for data_item in test_data_items:
                await data_item["topic"].set_write(**data_item["fields"])

                if "expected_severity" in data_item.keys():
                    severity = await asyncio.wait_for(
                        rule.alarm.severity_queue.get(), timeout=STD_TIMEOUT
                    )
                    assert severity == data_item["expected_severity"]

            assert rule.alarm.severity_queue.empty()

    def test_check_out_of_range(self) -> None:

        # Normal
        data_normal = TestData(
            [0.0] * 5,
            [0.0] * 5,
            [1.0] * 5,
            [1.0] * 5,
            [1.0, 0.0, 0.0, 1.0, 1.0],
        )

        rule = MTForceError(watcher.rules.MTForceError.get_schema())
        list_actuators = rule._check_out_of_range(data_normal, 1.0)
        assert list_actuators == []

        # Out of range
        data_normal = TestData(
            [0.0] * 5,
            [0.0] * 5,
            [1.0] * 5,
            [10.0] * 5,
            [1.0, 0.0, 0.0, 1.0, 1.0],
        )

        list_actuators = rule._check_out_of_range(data_normal, 1.0)
        assert list_actuators == [0, 3, 4]
