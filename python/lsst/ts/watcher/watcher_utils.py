# This file is part of ts_watcher.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

__all__ = ["AlarmInfo", "AlarmRuleInfo"]

import asyncio
import inspect
import logging
import typing
from dataclasses import dataclass

from lsst.ts.xml.enums.Watcher import AlarmSeverity


@dataclass
class AlarmRuleInfo:
    """Information about an alarm rule.

    Attributes
    ----------
    classname : `str`
        Name of the alarm rule class.
    config : dict[str, `dict`]
        Configuration parameters for the alarm rule.
    process : `asyncio.subprocess.Process`
        The process in which the AlarmRule runs.
    rule_names : list[str]
        List of rule names associated with the alarm rule.
    """

    classname: str
    config: dict[str, typing.Any]
    process: asyncio.subprocess.Process
    rule_names: list


class AlarmInfo:
    """Placeholder with Alarm information.

    Attributes
    ----------
    name : str
        The name of the alarm.
    severity : int
        The severity of the alarm.
    reason : str
        The reason for the alarm.
    max_severity : int
        The maximum severity of the alarm.
    acknowledged : bool
        Has the alarm been acknowledged?
    acknowledged_by : str
        The person who acknowledged the alarm.
    escalated_id : str
        The escalated id of the alarm.
    escalate_to : str
        The person the alarm was escalated to.
    muted_severity : int
        The muted severity of the alarm.
    muted_by : str
        The person who muted the alarm.
    timestamp_severity_oldest : float
        The oldest timestamp of the alarm.
    timestamp_severity_newest : float
        The newest timestamp of the alarm.
    timestamp_max_severity : float
        Timestamp when the maximum alarm severity was set.
    timestamp_acknowledged : float
        Timestamp when the alarm was acknowledged.
    timestamp_auto_acknowledge : float
        Timestamp when the alarm was automatically acknowledged.
    timestamp_auto_unacknowledge : float
        Timestamp when the alarm was automatically unacknowledged.
    timestamp_escalate : float
        Timestamp when the alarm was escalated.
    timestamp_unmute : float
        Timestamp when the alarm was unmuted.
    do_escalate : bool
        Escalate the alarm or not.
    """

    def __init__(self, name: str, log: logging.Logger):
        self.name = name
        self.log = log.getChild(type(self).__name__)

        # Additional alarm info.
        self.severity = None
        self.reason = None
        self.max_severity = None
        self.acknowledged = None
        self.acknowledged_by = None
        self.muted_severity = None
        self.muted_by = None
        self.escalate_to = None
        self.escalated_id = None
        self.timestamp_severity_oldest = None
        self.timestamp_severity_newest = None
        self.timestamp_max_severity = None
        self.timestamp_acknowledged = None
        self.timestamp_auto_acknowledge = None
        self.timestamp_auto_unacknowledge = None
        self.timestamp_escalate = None
        self.timestamp_unmute = None

    @property
    def nominal(self):
        """True if alarm is in nominal state: severity = max severity = NONE.

        When the alarm is in a nominal state, it should not be displayed
        in the Watcher GUI.
        """
        return self.severity == AlarmSeverity.NONE and self.max_severity == AlarmSeverity.NONE

    @property
    def callback(self):
        """Get the callback function."""
        return self._callback

    @callback.setter
    def callback(self, callback: typing.Callable[[AlarmInfo], None]):
        """Set or clear the callback function.

        Parameters
        ----------
        callback : callable, optional
            Coroutine (async function) to call whenever the alarm
            changes state, or None if no callback is wanted.
            The coroutine receives one argument: this alarm.

        Raises
        ------
        TypeError
            If callback is not None and not a coroutine.
        """
        if callback is not None and not inspect.iscoroutinefunction(callback):
            raise TypeError(f"callback={callback} must be async")
        self._callback = callback

    async def set_from_data(self, data):
        self.severity = data.severity
        self.reason = data.reason
        self.max_severity = data.maxSeverity
        self.acknowledged = data.acknowledged
        self.acknowledged_by = data.acknowledgedBy
        self.muted_severity = data.mutedSeverity
        self.muted_by = data.mutedBy
        self.escalate_to = data.escalateTo
        self.escalated_id = data.escalatedId
        self.timestamp_severity_oldest = data.timestampSeverityOldest
        self.timestamp_severity_newest = data.timestampSeverityNewest
        self.timestamp_max_severity = data.timestampMaxSeverity
        self.timestamp_acknowledged = data.timestampAcknowledged
        self.timestamp_auto_acknowledge = data.timestampAutoAcknowledge
        self.timestamp_auto_unacknowledge = data.timestampAutoUnacknowledge
        self.timestamp_escalate = data.timestampEscalate
        self.timestamp_unmute = data.timestampUnmute
