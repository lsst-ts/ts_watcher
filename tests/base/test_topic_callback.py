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

import asynctest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher

STD_TIMEOUT = 5  # Max time to send/receive a topic (seconds)
LONG_TIMEOUT = 60  # Max Remote startup time (seconds)

index_gen = salobj.index_generator()


class MockModel:
    def __init__(self, enabled=False):
        self.enabled = enabled


class TopicCallbackTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.index = next(index_gen)

    def make_enabled_rule(self):
        """Make an Enabled rule and callback.

        Returns
        -------
        A tuple of:

        * rule: the constructed EnabledRule
        * read_severities: a list of severities read from the rule.
            This will be updated as the rule is called.
        """
        config = types.SimpleNamespace(name=f"Test:{self.index}")
        rule = watcher.rules.Enabled(config=config)

        read_severities = []

        def alarm_callback(alarm):
            nonlocal read_severities
            read_severities.append(alarm.severity)

        rule.alarm.callback = alarm_callback

        return rule, read_severities

    async def test_basics(self):
        model = MockModel(enabled=True)

        rule, read_severities = self.make_enabled_rule()

        async with salobj.Controller(
            name="Test", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="Test",
            index=self.index,
            readonly=True,
            include=["summaryState"],
        ) as remote:
            topic_callback = watcher.TopicCallback(
                topic=remote.evt_summaryState, rule=rule, model=model
            )
            self.assertEqual(topic_callback.attr_name, "evt_summaryState")
            self.assertEqual(topic_callback.remote_name, "Test")
            self.assertEqual(topic_callback.remote_index, self.index)
            self.assertEqual(topic_callback.get(), None)
            self.assertEqual(read_severities, [])

            controller.evt_summaryState.set_put(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await asyncio.sleep(0.001)
            self.assertEqual(read_severities, [AlarmSeverity.WARNING])

    async def test_add_rule(self):
        model = MockModel(enabled=True)

        rule, read_severities = self.make_enabled_rule()
        rule2, read_severities2 = self.make_enabled_rule()

        async with salobj.Controller(
            name="Test", index=self.index
        ) as controller, salobj.Remote(
            domain=controller.domain,
            name="Test",
            index=self.index,
            readonly=True,
            include=["summaryState"],
        ) as remote:
            topic_callback = watcher.TopicCallback(
                topic=remote.evt_summaryState, rule=rule, model=model
            )

            self.assertEqual(read_severities, [])
            self.assertEqual(read_severities2, [])

            controller.evt_summaryState.set_put(
                summaryState=salobj.State.DISABLED, force_output=True
            )
            await asyncio.sleep(0.001)

            self.assertEqual(read_severities, [AlarmSeverity.WARNING])
            # rule2 has not been added so read_severities2 should be empty
            self.assertEqual(read_severities2, [])

            # cannot add a rule with the same name as an existing rule
            with self.assertRaises(ValueError):
                topic_callback.add_rule(rule2)

            # modify the rule and try again
            rule2.alarm.name = rule2.alarm.name + "modified"
            topic_callback.add_rule(rule2)
            controller.evt_summaryState.set_put(
                summaryState=salobj.State.FAULT, force_output=True
            )
            await asyncio.sleep(0.001)
            self.assertEqual(
                read_severities, [AlarmSeverity.WARNING, AlarmSeverity.SERIOUS]
            )
            self.assertEqual(read_severities2, [AlarmSeverity.SERIOUS])


if __name__ == "__main__":
    unittest.main()
