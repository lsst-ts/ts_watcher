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

__all__ = ["ConfiguredSeverities"]

import asyncio
import yaml

from lsst.ts import salobj
from lsst.ts.watcher import base


class ConfiguredSeverities(base.BaseRule):
    """A test rule that transitions through a specified list of severities.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Raises
    ------
    RuntimeError
        If ``__call__`` is called. When used as a normal rule
        this method should never be called because the rule
        specifies topics to call it.

    Notes
    -----
    The alarm name is ``f"test.ConfiguredSeverities.{config.name}"``
    """
    def __init__(self, config):
        super().__init__(config=config,
                         name=f"test.ConfiguredSeverities.{config.name}",
                         remote_info_list=[])
        self.run_timer = salobj.make_done_future()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_watcher/ConfiguredSeverities.yaml
            description: Configuration for ConfiguredSeverities
            type: object
            properties:
                name:
                    description: Rule name (one field in a longer name).
                    type: string
                interval:
                    descrption: Interval between severities (seconds).
                    type: number
                severities:
                    description: A list of severities as lsst.ts.idl.enums.Watcher.AlarmSeverity constants.
                    type: array
                    items:
                        type: integer
            required: [name, interval, severities]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def is_usable(self, disabled_sal_components):
        return True

    def start(self):
        self.run_timer.cancel()
        self.run_timer = asyncio.ensure_future(self.run())

    def stop(self):
        self.run_timer.cancel()

    async def run(self):
        """Run through the configured severities."""
        for severity in self.config.severities:
            await asyncio.sleep(self.config.interval)
            self.alarm.set_severity(severity=severity, reason="Commanded severity")

    def __call__(self, topic_callback):
        raise RuntimeError("This should never be called")
