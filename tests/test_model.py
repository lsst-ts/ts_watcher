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

import unittest

from lsst.ts import watcher


class GetRuleClassTestCase(unittest.TestCase):
    def test_good_names(self):
        for classname, desired_class in (
            ("Enabled", watcher.rules.Enabled),
            ("test.NoConfig", watcher.rules.test.NoConfig),
            ("test.ConfiguredSeverities", watcher.rules.test.ConfiguredSeverities),
        ):
            rule_class = watcher.get_rule_class(classname)
            self.assertEqual(rule_class, desired_class)

    def test_bad_names(self):
        for bad_name in (
            "NoSuchRule",  # no such rule
            "test.NoSuchRule",  # no such rule
            "test.Enabled",  # wrong module
            "NoConfig",  # wrong module
            "test_NoConfig",  # wrong separator
        ):
            with self.assertRaises(ValueError):
                watcher.get_rule_class(bad_name)


if __name__ == "__main__":
    unittest.main()
