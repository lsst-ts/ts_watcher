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

__all__ = ["TriggeredSeverities"]

import asyncio
import yaml

from lsst.ts import watcher
from lsst.ts import utils

# Maximum time (seconds) to wait for the next severity to be reported.
NEXT_SEVERITY_TIMEOUT = 1


class TriggeredSeverities(watcher.BaseRule):
    """A test rule that transitions through a specified list of severities,
    repeatedly, when manually triggered by test code.

    This is only intended for unit tests, since it will not transition
    between severities on its own. It gives unit tests complete control
    over when to report the next severity.

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

    Attributes
    ----------
    run_task : `asyncio.Future` | `asyncio.Task`
        The task used to run the `run` method.
        Once started, you may check if this task is done to determine
        that all repeats have run.
    trigger_next_severity_event : `asyncio.Event`
        An event the user can set to trigger the next severity.

    Notes
    -----
    The alarm name is ``f"test.TriggeredSeverities.{config.name}"``
    """

    def __init__(self, config):
        super().__init__(
            config=config,
            name=f"test.TriggeredSeverities.{config.name}",
            remote_info_list=[],
        )
        self.run_task = utils.make_done_future()
        self.trigger_next_severity_event = asyncio.Event()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for TriggeredSeverities
            type: object
            properties:
                name:
                    description: Rule name (one field in a longer name).
                    type: string
                severities:
                    description: A list of severities as lsst.ts.idl.enums.Watcher.AlarmSeverity constants.
                    type: array
                    items:
                        type: integer
                repeats:
                    description: How many times to repeat the pattern? 0 = forever.
                    type: integer
                    default: 0
            required: [name, severities]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def run(self):
        """Run through the configured severities, repeatedly, forever."""
        repeat = 0
        while True:
            for severity in self.config.severities:
                await self.trigger_next_severity_event.wait()
                self.trigger_next_severity_event.clear()
                await self.alarm.set_severity(
                    severity=severity, reason="Commanded severity"
                )
            repeat += 1
            if self.config.repeats > 0 and repeat >= self.config.repeats:
                break

    def start(self):
        self.run_task.cancel()
        self.run_task = asyncio.ensure_future(self.run())

    def stop(self):
        self.run_task.cancel()

    def __call__(self, topic_callback):
        raise RuntimeError("This should never be called")
