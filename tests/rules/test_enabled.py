# This file is part of ts_watcher.
#
# Developed for the LSST Data Management System.
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

import asynctest
import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher

LONG_TIMEOUT = 60  # timeout for starting all watcher remotes (sec)


class EnabledTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def make_config(self, name):
        """Make a config for the Enabled rule.

        Parameters
        ----------
        name : `str`
            CSC name and index in the form `name` or `name:index`.
            The default index is 0.
        """
        schema = watcher.rules.Enabled.get_schema()
        validator = salobj.DefaultingValidator(schema)
        config_dict = dict(name=name)

        full_config_dict = validator.validate(config_dict)
        config = types.SimpleNamespace(**full_config_dict)
        for key in config_dict:
            self.assertEqual(getattr(config, key), config_dict[key])
        return config

    def test_basics(self):
        schema = watcher.rules.Enabled.get_schema()
        self.assertIsNotNone(schema)
        name = "ScriptQueue"
        config = self.make_config(name=name)
        desired_rule_name = f"Enabled.{name}:0"

        rule = watcher.rules.Enabled(config=config)
        self.assertEqual(rule.name, desired_rule_name)
        self.assertIsInstance(rule.alarm, watcher.Alarm)
        self.assertEqual(rule.alarm.name, rule.name)
        self.assertTrue(rule.alarm.nominal)
        self.assertEqual(len(rule.remote_info_list), 1)
        remote_info = rule.remote_info_list[0]
        self.assertEqual(remote_info.name, name)
        self.assertEqual(remote_info.index, 0)
        self.assertIn(name, repr(rule))
        self.assertIn("Enabled", repr(rule))

    async def test_call(self):
        name = "ScriptQueue"
        index = 5

        watcher_config_dict = yaml.safe_load(f"""
            disabled_sal_components: []
            auto_acknowledge_delay: 3600
            auto_unacknowledge_delay: 3600
            rules:
            - classname: Enabled
              configs:
              - name: {name}:{index}
            """)
        watcher_config = types.SimpleNamespace(**watcher_config_dict)

        async with salobj.Controller(name=name, index=index) as controller:
            async with watcher.Model(domain=controller.domain, config=watcher_config) as model:
                model.enable()

                self.assertEqual(len(model.rules), 1)
                rule_name = f"Enabled.{name}:{index}"
                rule = model.rules[rule_name]

                read_severities = []

                def alarm_callback(alarm):
                    nonlocal read_severities
                    read_severities.append(alarm.severity)

                rule.alarm.callback = alarm_callback

                expected_severities = []
                for state in (salobj.State.STANDBY,
                              salobj.State.DISABLED,
                              salobj.State.ENABLED,
                              salobj.State.FAULT,
                              salobj.State.STANDBY,
                              salobj.State.DISABLED,
                              salobj.State.FAULT,
                              salobj.State.STANDBY,
                              salobj.State.DISABLED,
                              salobj.State.ENABLED):
                    if state == salobj.State.ENABLED:
                        expected_severities.append(AlarmSeverity.NONE)
                    elif state == salobj.State.FAULT:
                        expected_severities.append(AlarmSeverity.SERIOUS)
                    else:
                        expected_severities.append(AlarmSeverity.WARNING)

                    controller.evt_summaryState.set_put(summaryState=state, force_output=True)
                    # give the remote a chance to read the data
                    await asyncio.sleep(0.001)

                self.assertEqual(read_severities, expected_severities)


if __name__ == "__main__":
    unittest.main()
