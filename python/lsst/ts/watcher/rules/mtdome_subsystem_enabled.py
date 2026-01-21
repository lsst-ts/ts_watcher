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

__all__ = ["MTDomeSubsystemEnabled"]

import typing
from dataclasses import dataclass

import yaml

from lsst.ts import salobj
from lsst.ts.xml import component_info
from lsst.ts.xml.enums.MTDome import EnabledState
from lsst.ts.xml.enums.Watcher import AlarmSeverity
from lsst.ts.xml.sal_enums import State

from ..base_rule import AlarmSeverityReasonType, BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


@dataclass
class SubsystemState:
    state: str
    fault_code: str


class MTDomeSubsystemEnabled(BaseRule):
    """Monitor the MTDome subsystem Enabled events for any alarming states.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):
        remote_name = "MTDome"
        remote_index = 0
        remote_info_list = [
            RemoteInfo(
                name=remote_name,
                index=remote_index,
                callback_names=[config.event_name, "evt_summaryState"],
                poll_names=[],
            )
        ]
        event_name: str = config.event_name
        rule_name = "MTDome" + event_name[4].upper() + event_name[5:]
        super().__init__(
            config=config,
            name=f"{rule_name}.{remote_name}",
            remote_info_list=remote_info_list,
            log=log,
        )

        self.may_raise = False
        self.subsystem_state: SubsystemState | None = None

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        enum_str = ", ".join(
            f"{severity.name}" for severity in AlarmSeverity if severity is not AlarmSeverity.NONE
        )
        state_str = ", ".join(state.name for state in State)
        ci = component_info.ComponentInfo(name="MTDome", topic_subname="")
        events = [topic for topic in ci.topics if topic.startswith("evt_") and topic.endswith("Enabled")]
        schema_yaml = f"""
$schema: 'http://json-schema.org/draft-07/schema#'
description: Configuration for MTDomeSubsystemEnabled rule.
type: object
properties:
    subsystem_name:
        description: The name of the MTDome subsystem.
        type: string
    event_name:
        description: The name of the event to monitor.
        enum: {events}
    csc_state:
        description: The state(s) of the CSC for which the alarm is active.
        type: array
        minItems: 1
        items:
            enum: [{state_str}]
    severity:
          description: Alarm severity.
          enum: [{enum_str}]

required:
- subsystem_name
- event_name
- csc_state
- severity
additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> AlarmSeverityReasonType:
        """Compute and set alarm severity and reason.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
              Message from the topic described by topic_callback.
        **kwargs : `dict` [`str`, `typing.Any`]
            Keyword arguments. If triggered by `TopicCallback` calling
            `update_alarm_severity`, the arguments will be as follows:

            * topic_callback : `TopicCallback`
              Topic callback wrapper.

        Returns
        -------
        None, if no change or unknown, or a tuple of two values:

        severity: `lsst.ts.xml.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm state is ``NONE``.
        """

        if hasattr(data, "faultCode"):
            self.subsystem_state = SubsystemState(state=EnabledState(data.state), fault_code=data.faultCode)
            self.log.debug(f"{self.subsystem_state.fault_code=!r}")
        if hasattr(data, "summaryState"):
            self.may_raise = State(data.summaryState).name in self.config.csc_state
            self.log.debug(f"{State(data.summaryState).name=!r}, {self.may_raise=}")

        if not self.may_raise or (not self.subsystem_state or not self.subsystem_state.fault_code):
            severity_and_reason = NoneNoReason
        else:
            severity_and_reason = (
                AlarmSeverity[self.config.severity],
                f"MTDome {self.config.subsystem_name} state {self.subsystem_state.state!r}: "
                f"{self.subsystem_state.fault_code}.",
            )
        return severity_and_reason
