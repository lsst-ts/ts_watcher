from __future__ import annotations

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

import typing

import yaml
from lsst.ts import watcher
from lsst.ts.xml.enums.Script import ScriptState
from lsst.ts.xml.enums.Watcher import AlarmSeverity

if typing.TYPE_CHECKING:
    from lsst.ts.salobj import BaseMsgType


class ScriptFailed(watcher.BaseRule):
    """Monitor the status of the ScriptQueue.

    Set alarm severity to WARNING if the ScriptQueue is paused and the current
    Script state is FAILED, NONE otherwise.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is f"ScriptFailed.ScriptQueue:{index}",
    where index are derived from ``config.index``.
    """

    def __init__(self, config, log=None):
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
            log=log,
        )

        self.queue_running = None
        self.queue_enabled = None
        self.current_script_sal_index = None
        self.current_script_state = ScriptState.UNKNOWN

    @classmethod
    def get_schema(cls):
        ident = "                    "
        severity_values = "\n".join(
            [f"{ident}- {severity.name}" for severity in AlarmSeverity]
        )

        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for Enabled
            type: object
            properties:
                index:
                    description: >-
                        Index of the ScriptQueue to monitor.
                    type: integer
                severity:
                    description: >-
                        Alarm severity for when Scripts fail.
                    type: string
                    default: {AlarmSeverity.CRITICAL.name}
                    enum:
{severity_values}
            required: [index]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: BaseMsgType, topic_callback: watcher.TopicCallback | None
    ) -> watcher.AlarmSeverityReasonType:
        assert topic_callback is not None
        if topic_callback.attr_name == "evt_queue":
            self.queue_enabled = data.enabled
            self.queue_running = data.running
            self.current_script_sal_index = data.currentSalIndex
        elif self.current_script_sal_index is not None:
            # attr_name is evt_script
            if data.scriptSalIndex == self.current_script_sal_index:
                self.current_script_state = ScriptState(data.scriptState)

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
