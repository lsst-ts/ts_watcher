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

__all__ = ["Heartbeat"]

import asyncio
import yaml

from lsst.ts import salobj
from lsst.ts.watcher import base


class Heartbeat(base.BaseRule):
    """Monitor the heartbeat event from a SAL component.

    Set alarm severity NONE whenever a heartbeat event arrives
    and SERIOUS if a heartbeat event does not arrive in time.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"Heartbeat.{name}:{index}",
    where name and index are derived from ``config.name``.
    """
    def __init__(self, config):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = base.RemoteInfo(name=remote_name,
                                      index=remote_index,
                                      callback_names=["evt_heartbeat"],
                                      poll_names=[])
        super().__init__(config=config,
                         name=f"Heartbeat.{remote_info.name}:{remote_info.index}",
                         remote_info_list=[remote_info])
        self.heartbeat_timer_task = salobj.make_done_future()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_watcher/Heartbeat.yaml
            description: Configuration for Heartbeat
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                timeout:
                    description: Maximum allowed time between heartbeat events (sec)
                    type: number
                    default: 3

            required: [name]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def is_usable(self, disabled_sal_components):
        remote_info = self.remote_info_list[0]
        return remote_info.key not in disabled_sal_components

    def __call__(self, topic_callback):
        self.restart_timer()
        return base.NoneNoReason

    async def heartbeat_timer(self):
        """Heartbeat timer."""
        await asyncio.sleep(self.config.timeout)
        self.alarm.set_severity(severity=base.AlarmSeverity.SERIOUS,
                                reason=f"Heartbeat event not seen in {self.config.timeout} seconds")

    def restart_timer(self):
        """Start or restart the heartbeat timer."""
        self.heartbeat_timer_task.cancel()
        self.heartbeat_timer_task = asyncio.ensure_future(self.heartbeat_timer())

    def start(self):
        self.restart_timer()

    def stop(self):
        self.heartbeat_timer_task.cancel()
