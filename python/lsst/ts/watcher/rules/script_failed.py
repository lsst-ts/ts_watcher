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

__all__ = ["ScriptFailed"]

import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import watcher
from lsst.ts.idl.enums.Script import ScriptState


class ScriptFailed(watcher.BaseRule):
    """Monitor the status of the ScriptQueue.

    Set alarm severity to WARNING if the ScriptQueue is paused and the current
    Script state is FAILED, NONE otherwise.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"ScriptFailed.ScriptQueue:{index}",
    where index are derived from ``config.index``.
    """

    def __init__(self, config):
        remote_name = "ScriptQueue"
        remote_index = config.index
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_queue", "evt_script"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"ScriptFailed.ScriptQueue:{remote_index}",
            remote_info_list=[remote_info],
        )

        self.queue_running = None
        self.queue_enabled = None
        self.current_script_sal_index = None
        self.current_script_state = ScriptState.UNKNOWN

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for Enabled
            type: object
            properties:
                index:
                    description: >-
                        Index of the ScriptQueue to monitor.
                    type: integer

            required: [index]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def __call__(self, topic_callback):

        if topic_callback.attr_name == "evt_queue":
            queue = topic_callback.get()
            self.queue_enabled = queue.enabled
            self.queue_running = queue.running
            self.current_script_sal_index = queue.currentSalIndex
        elif self.current_script_sal_index is not None:
            script = topic_callback.get()
            if script.scriptSalIndex == self.current_script_sal_index:
                self.current_script_state = ScriptState(script.scriptState)

        if (
            self.queue_enabled is True
            and self.queue_running is False
            and self.current_script_state == ScriptState.FAILED
        ):
            return (
                AlarmSeverity.WARNING,
                f"Current Script {self.current_script_sal_index} FAILED.",
            )
        else:
            return watcher.NoneNoReason
