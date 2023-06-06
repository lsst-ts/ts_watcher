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

__all__ = ["AlarmSeverityReasonType", "OneAlarmCallbackRule"]

import abc
import typing

from lsst.ts.idl.enums.Watcher import AlarmSeverity

from .base_rule import BaseRule
from .topic_callback import TopicCallback

if typing.TYPE_CHECKING:
    from lsst.ts.salobj import BaseMsgType

# Type alias for (alarm severity, reason str)
AlarmSeverityReasonType: typing.TypeAlias = tuple[AlarmSeverity, str]


class OneAlarmCallbackRule(BaseRule):
    """Base class for a Watcher rule with a single alarm
    whose severity is determined using one or more topic callbacks.

    Subclasses must override synchronous method `compute_alarm_severity`.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    name : `str`
        Name of alarm. This must be unique among all alarms
        and should be of the form system.[subsystem....]_name
        so that groups of related alarms can be acknowledged.
    remote_info_list : `list` [`RemoteInfo`]
        Information about the remotes used by this rule.

    Attributes
    ----------
    alarm : `Alarm`
        The alarm associated with this rule.
    remote_keys : `frozenset` [`tuple` [`str`, `int`]]
        Set of remote keys. Each element is a tuple of:

        * SAL component name (e.g. "ATPtg")
        * SAL index

    Notes
    -----
    `Model.add_rule` adds an attribute
    ``{lowerremotename}_{index} = `` `RemoteWrapper`
    to the rule for each remote in `remote_info_list`, where
    ``lowerremotename`` is the name of the SAL component cast to lowercase,
    and ``index`` is the SAL index (0 if not an indexed component).
    For example: ``atdome_0`` for ATDome (which is not indexed).
    This gives each rule ready access to its remote wrappers.
    """

    def __init__(self, config, name, remote_info_list):
        super().__init__(config=config, name=name, remote_info_list=remote_info_list)

    @abc.abstractmethod
    def compute_alarm_severity(
        self, data: BaseMsgType, topic_callback: TopicCallback | None
    ) -> AlarmSeverityReasonType:
        """Compute and return alarm severity, reason.

        Parameters
        ----------
        data : `BaseMsgType`
            Message data.
        topic_callback : `TopicCallback`
            Topic callback wrapper.

        Returns
        -------
        A tuple of two values:

        severity: `lsst.ts.idl.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm states is ``NONE``.

        To defer setting the alarm state, start a task that calls
        ``self.alarm.set_severity`` later. For example the heartbeat rule's
        ``__call__`` method is called when the heartbeat event is seen,
        and this restarts a timer and returns `NoneNoReason`. If the timer
        finishes, meaning the next heartbeat event was not seen in time,
        the timer sets alarm severity > ``NONE``.
        """
        raise NotImplementedError()

    async def __call__(
        self, data: BaseMsgType, topic_callback: TopicCallback | None
    ) -> None:
        """Run the rule and set alarm severity and reason."""
        severity, reason = self.compute_alarm_severity(
            data=data, topic_callback=topic_callback
        )
        await self.alarm.set_severity(severity=severity, reason=reason)

    def __repr__(self):
        return f"{type(self).__name__}(name={self.name})"
