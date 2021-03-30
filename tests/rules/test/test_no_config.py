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

import types
import unittest

from lsst.ts import watcher


class TestNoConfigTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_basics(self):
        self.assertIsNone(watcher.rules.test.NoConfig.get_schema())

        desired_rule_name = "test.NoConfig"
        rule = watcher.rules.test.NoConfig(config=types.SimpleNamespace())
        self.assertEqual(rule.remote_info_list, [])
        self.assertEqual(rule.name, desired_rule_name)
        self.assertIsInstance(rule.alarm, watcher.Alarm)
        self.assertEqual(rule.alarm.name, rule.name)
        self.assertTrue(rule.alarm.nominal)
        with self.assertRaises(RuntimeError):
            rule(topic_callback=None)
        self.assertIn(rule.name, repr(rule))
        self.assertIn(desired_rule_name, repr(rule))


if __name__ == "__main__":
    unittest.main()
