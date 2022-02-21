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

__all__ = ["ConfiguredSeverities"]

import asyncio
import yaml

from lsst.ts import utils
from lsst.ts import watcher


class ConfiguredSeverities(watcher.BaseRule):
    """A test rule that transitions through a specified list of severities,
    repeatedly.

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
        super().__init__(
            config=config,
            name=f"test.ConfiguredSeverities.{config.name}",
            remote_info_list=[],
        )
        self.run_timer = utils.make_done_future()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for ConfiguredSeverities
            type: object
            properties:
                name:
                    description: Rule name (one field in a longer name).
                    type: string
                interval:
                    description: Interval between severities (seconds).
                    type: number
                delay:
                    description: Additional delay before the first severity (seconds).
                    type: number
                    default: 0
                severities:
                    description: A list of severities as lsst.ts.idl.enums.Watcher.AlarmSeverity constants.
                    type: array
                    items:
                        type: integer
                repeats:
                    description: How many times to repeat the pattern? 0 = forever.
                    type: integer
                    default: 0
            required: [name, interval, severities]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def start(self):
        self.run_timer.cancel()
        self.run_timer = asyncio.ensure_future(self.run())

    def stop(self):
        self.run_timer.cancel()

    async def run(self):
        """Run through the configured severities, repeatedly, forever."""
        await asyncio.sleep(self.config.delay)
        repeat = 0
        while True:
            for severity in self.config.severities:
                await asyncio.sleep(self.config.interval)
                await self.alarm.set_severity(
                    severity=severity, reason="Commanded severity"
                )
            repeat += 1
            if self.config.repeats > 0 and repeat >= self.config.repeats:
                break

    def __call__(self, topic_callback):
        raise RuntimeError("This should never be called")
