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

import glob
import pathlib
import types
import unittest

import jsonschema
import pytest
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class WatcherSchemaTestCase(unittest.TestCase):
    """Test the Watcher schema."""

    def setUp(self):
        self.schema = watcher.CONFIG_SCHEMA
        self.validator = salobj.StandardValidator(schema=self.schema)
        self.configpath = pathlib.Path(__file__).resolve().parent / "data" / "config" / "csc"

    def read_dict(self, path):
        with open(path, "r") as f:
            raw_config = f.read()
            return yaml.safe_load(raw_config)

    def test_invalid_files(self):
        paths = glob.glob(str(self.configpath / "invalid_*.yaml"))
        for path in paths:
            config_dict = self.read_dict(path)
            with pytest.raises(jsonschema.exceptions.ValidationError):
                self.validator.validate(config_dict)

    def test_basic_file(self):
        config_dict = self.read_dict(self.configpath / "_init.yaml")
        config_dict.update(self.read_dict(self.configpath / "basic.yaml"))
        self.validator.validate(config_dict)
        config = types.SimpleNamespace(**config_dict)
        assert config.disabled_sal_components == []
        assert config.auto_acknowledge_delay == 3600
        assert config.auto_unacknowledge_delay == 3600
        assert len(config.rules) == 2
        rule0_dict = config.rules[0]
        assert rule0_dict["classname"] == "test.ConfiguredSeverities"
        assert rule0_dict["configs"] == [dict(severities=[2, 3, 1], interval=1, name="aname")]
        rule1_dict = config.rules[1]
        assert rule1_dict["classname"] == "test.NoConfig"
        assert rule1_dict["configs"] == [{}]
        assert config.escalation == []

    def test_enabled_file(self):
        config_dict = self.read_dict(self.configpath / "_init.yaml")
        config_dict.update(self.read_dict(self.configpath / "enabled.yaml"))
        self.validator.validate(config_dict)
        config = types.SimpleNamespace(**config_dict)
        assert config.disabled_sal_components == ["ATCamera"]
        assert config.auto_acknowledge_delay == 1001
        assert config.auto_unacknowledge_delay == 1002
        assert len(config.rules) == 1
        rule0_dict = config.rules[0]
        assert rule0_dict["classname"] == "Enabled"
        assert rule0_dict["configs"] == [
            dict(
                name="ATDome",
                disabled_severity=AlarmSeverity.WARNING,
                standby_severity=AlarmSeverity.WARNING,
            ),
            dict(
                name="ATCamera",
                disabled_severity=AlarmSeverity.WARNING,
                standby_severity=AlarmSeverity.WARNING,
            ),
            dict(
                name="ScriptQueue:2",
                disabled_severity=AlarmSeverity.WARNING,
                standby_severity=AlarmSeverity.WARNING,
            ),
        ]
        assert len(config.escalation) == 2
        assert config.escalation[0] == dict(
            alarms=["Enabled.AT*"],
            responder="stella",
            delay=0.11,
        )
        assert config.escalation[1] == dict(
            alarms=["Enabled.ATCamera"],
            responder="someone",
            delay=0.12,
        )
