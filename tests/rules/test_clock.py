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
import types
import unittest

import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity


class HeartbeatWriter(salobj.topics.ControllerEvent):
    """A heartbeat event writer with incorrect private_sndStamp."""

    def __init__(self, salinfo):
        super().__init__(salinfo=salinfo, name="heartbeat")
        # TODO DM-36679: remove this flag and the code that uses it
        # once we switch to Kafka or decide not to.
        # Set true if using the DDS version of ts_salobj,
        # false if using the Kafka version
        self._is_dds = hasattr(self, "_writer")

    async def alt_write(self, dt):
        """Write the current data with private_sndStamp offset by dt"""
        self.data.private_sndStamp = utils.current_tai() + dt
        self.data.private_origin = self.salinfo.domain.origin
        self.data.private_identity = self.salinfo.identity
        if self._seq_num_generator is not None:
            self.data.private_seqNum = next(self._seq_num_generator)
        # when index is 0 use the default of 0 and give senders a chance
        # to override it.
        if self.salinfo.index != 0:
            self.data.salIndex = self.salinfo.index

        if self._is_dds:
            self._writer.write(self.data)
        else:
            data = copy.copy(self.data)
            data_dict = vars(data)
            await self.salinfo.write_data(
                topic_info=self.topic_info, data_dict=data_dict
            )
            return data

    async def write(self):
        raise NotImplementedError()

    async def set_write(self, **kwargs):
        raise NotImplementedError()


class ClockTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    def make_config(self, name, threshold):
        """Make a config for the Clock rule.

        Parameters
        ----------
        name : `str`
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        threshold : `float`
            Maximum allowed time between heartbeat events (sec).
        """
        schema = watcher.rules.Clock.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name, threshold=threshold)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            assert getattr(config, key) == config_dict[key]
        return config

    async def test_basics(self):
        schema = watcher.rules.Clock.get_schema()
        assert schema is not None
        name = "ScriptQueue"
        threshold = 1.2
        config = self.make_config(name=name, threshold=threshold)
        desired_rule_name = f"Clock.{name}:0"

        rule = watcher.rules.Clock(config=config)
        assert rule.name == desired_rule_name
        assert rule.threshold == threshold
        assert isinstance(rule.alarm, watcher.Alarm)
        assert rule.alarm.name == rule.name
        assert rule.alarm.nominal
        assert len(rule.remote_info_list) == 1
        remote_info = rule.remote_info_list[0]
        assert remote_info.name == name
        assert remote_info.index == 0
        assert name in repr(rule)
        assert "Clock" in repr(rule)

    async def test_operation(self):
        name = "ScriptQueue"
        index = 5
        # Set margin (seconds) to a value large enough to handle
        # timing uncertainties (including Docker's clock
        # non-monotonicity on macOS and slow systems).
        margin = 1
        threshold = margin * 2

        watcher_config_dict = yaml.safe_load(
            f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Clock
              configs:
              - name: {name}:{index}
                threshold: {threshold}
            escalation: []
            """
        )
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name=name, index=index)
            heartbeat_writer = HeartbeatWriter(salinfo=salinfo)
            await salinfo.start()
            async with watcher.Model(domain=domain, config=watcher_config) as model:
                model.enable()

                assert len(model.rules) == 1
                rule_name = f"Clock.{name}:{index}"
                rule = model.rules[rule_name]
                alarm = rule.alarm
                alarm.init_severity_queue()

                # Sending fewer than Clock.min_errors heartbeat events
                # with excessive error should leave the alarm in its
                # original nominal state, because we require
                # ``min_errors`` sequential time errors for an alarm.
                bad_dt = threshold + margin
                good_dt = threshold - margin
                for i in range(rule.min_errors - 1):
                    await heartbeat_writer.alt_write(dt=bad_dt)
                    await alarm.assert_next_severity(AlarmSeverity.NONE)
                    assert alarm.nominal

                # The next heartbeat event with bad dt should set
                # alarm severity to WARNING. The sign of the clock
                # error should not matter, so try a negative error.
                await heartbeat_writer.alt_write(dt=-bad_dt)
                await alarm.assert_next_severity(AlarmSeverity.WARNING)
                assert not alarm.nominal
                assert alarm.severity == AlarmSeverity.WARNING
                assert "mean" in alarm.reason

                # A valid value should return alarm severity to NONE.
                await heartbeat_writer.alt_write(dt=good_dt)
                await alarm.assert_next_severity(AlarmSeverity.NONE)

                # Sending fewer than Clock.min_errors heartbeat events
                # with excessive error should leave the alarm severity
                # at NONE
                for i in range(rule.min_errors - 1):
                    await heartbeat_writer.alt_write(dt=bad_dt)
                    await alarm.assert_next_severity(AlarmSeverity.NONE)

                await heartbeat_writer.alt_write(dt=bad_dt)
                await alarm.assert_next_severity(AlarmSeverity.WARNING)
