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

import glob
import pathlib
import types
import unittest

import yaml
import jsonschema

from lsst.ts import salobj


class WatcherSchemaTestCase(unittest.TestCase):
    """Test the Watcher schema.
    """
    def setUp(self):
        schemapath = pathlib.Path(__file__).resolve().parents[1] / "schema" / "Watcher.yaml"
        with open(schemapath, "r") as f:
            rawschema = f.read()
        self.schema = yaml.safe_load(rawschema)
        self.validator = salobj.DefaultingValidator(schema=self.schema)
        self.configpath = pathlib.Path(__file__).resolve().parent / "data" / "config"

    def read_dict(self, path):
        with open(path, "r") as f:
            raw_config = f.read()
            return yaml.safe_load(raw_config)

    def test_invalid_files(self):
        paths = glob.glob(str(self.configpath / "invalid_*.yaml"))
        for path in paths:
            config_dict = self.read_dict(path)
            with self.assertRaises(jsonschema.exceptions.ValidationError):
                self.validator.validate(config_dict)

    def test_basic_file(self):
        config_dict = self.read_dict(self.configpath / "basic.yaml")
        validated_dict = self.validator.validate(config_dict)
        config = types.SimpleNamespace(**validated_dict)
        self.assertEqual(config.disabled_sal_components, [])
        self.assertEqual(len(config.rules), 2)
        rule0_dict = config.rules[0]
        self.assertEqual(rule0_dict["classname"], "test.ConfiguredSeverities")
        self.assertEqual(rule0_dict["configs"], [dict(severities=[2, 3, 1], interval=1, name="aname")])
        rule1_dict = config.rules[1]
        self.assertEqual(rule1_dict["classname"], "test.NoConfig")
        self.assertEqual(rule1_dict["configs"], [{}])

    def test_enabled_file(self):
        config_dict = self.read_dict(self.configpath / "enabled.yaml")
        validated_dict = self.validator.validate(config_dict)
        config = types.SimpleNamespace(**validated_dict)
        self.assertEqual(config.disabled_sal_components, ["ATCamera"])
        self.assertEqual(len(config.rules), 1)
        rule0_dict = config.rules[0]
        self.assertEqual(rule0_dict["classname"], "Enabled")
        self.assertEqual(rule0_dict["configs"],
                         [dict(name="ATDome"), dict(name="ATCamera"), dict(name="ScriptQueue:2")])


if __name__ == "__main__":
    unittest.main()
