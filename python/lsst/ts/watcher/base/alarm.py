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

__all__ = ["Alarm"]

import asyncio

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj


class Alarm:
    """A Watcher alarm.

    Parameters
    ----------
    name : `str`
        Name of alarm. This must be unique among all alarms
        and should be of the form system.[subsystem....]_name
        so that groups of related alarms can be acknowledged.
    """
    def __init__(self, name):
        self.name = name
        self.callback = None
        self.auto_acknowledge_delay = 0
        self.auto_unacknowledge_delay = 0
        self.auto_acknowledge_task = salobj.make_done_future()
        self.auto_unacknowledge_task = salobj.make_done_future()
        self.unmute_task = salobj.make_done_future()
        self.reset()

    @property
    def muted(self):
        """Is this alarm muted?
        """
        return self.muted_severity != AlarmSeverity.NONE

    @property
    def nominal(self):
        """True if alarm is in nominal state: severity = max severity = NONE.

        When the alarm is in nominal state it should not be displayed
        in the Watcher GUI.
        """
        return self.severity == AlarmSeverity.NONE \
            and self.max_severity == AlarmSeverity.NONE

    def configure(self, callback=None, auto_acknowledge_delay=0, auto_unacknowledge_delay=0):
        """Configure the callback function and auto ack/unack delays.

        Parameters
        ----------
        callback : callable (optional)
            Function or coroutine to call whenever the alarm changes state,
            or None if no callback wanted.
            The function receives one argument: this alarm.
        auto_acknowledge_delay : `float` (optional)
            Delay (in seconds) before a stale alarm is automatically
            acknowledged, or 0 for no automatic acknowledgement.
            A stale alarm is one that has not yet been acknowledged, but its
            severity has gone to NONE.
        auto_unacknowledge_delay : `float` (optional)
            Delay (in seconds) before an acknowledged alarm is automatically
            unacknowledged, or 0 for no automatic unacknowledgement.
            Automatic unacknowledgement only occurs if the alarm persists,
            because an acknowledged alarm is reset if severity goes to NONE.
        """
        if auto_acknowledge_delay < 0:
            raise ValueError(f"auto_acknowledge_delay={auto_acknowledge_delay} must be >= 0")
        if auto_unacknowledge_delay < 0:
            raise ValueError(f"auto_unacknowledge_delay={auto_unacknowledge_delay} must be >= 0")
        self.callback = callback
        self.auto_acknowledge_delay = auto_acknowledge_delay
        self.auto_unacknowledge_delay = auto_unacknowledge_delay

    def close(self):
        """Cancel pending tasks.
        """
        self.cancel_auto_acknowledge()
        self.cancel_auto_unacknowledge()
        self.unmute_task.cancel()

    def acknowledge(self, severity, user):
        """Acknowledge the alarm. A no-op if nominal or acknowledged.

        Parameters
        ----------
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to acknowledge. If the severity goes above
            this level the alarm will unacknowledge itself.
        user : `str`
            Name of user; used to set acknowledged_by.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (i.e. if any fields were modified),
            False otherwise.

        Raises
        ------
        ValueError
            If ``severity < self.max_severity``.

        Notes
        -----
        The reason ``severity`` is an argument is to handle the case that
        a user acknowledges an alarm just as the alarm severity increases.
        To avoid the danger of accidentally acknowledging at a higher
        severity than intended, the command must be rejected.
        """
        self.cancel_auto_acknowledge()
        self.cancel_auto_unacknowledge()
        if self.nominal or self.acknowledged:
            return False

        severity = AlarmSeverity(severity)
        if severity < self.max_severity:
            raise ValueError(f"severity {severity} < max_severity {self.max_severity}")
        curr_tai = salobj.current_tai()
        if self.severity == AlarmSeverity.NONE:
            # reset the alarm to nominal
            self.max_severity = AlarmSeverity.NONE
        else:
            if self.auto_unacknowledge_delay > 0:
                self.timestamp_auto_unacknowledge = salobj.current_tai() + self.auto_unacknowledge_delay
                self.auto_unacknowledge_task = asyncio.create_task(self.auto_unacknowledge())
            self.max_severity = severity
        self.acknowledged = True
        self.acknowledged_by = user
        self.timestamp_acknowledged = curr_tai
        self.timestamp_max_severity = curr_tai

        self._run_callback()
        return True

    async def auto_acknowledge(self):
        """Wait, then automatically cknowledge the alarm.
        """
        await asyncio.sleep(self.auto_acknowledge_delay)
        self.acknowledge(severity=self.max_severity, user="automatic")

    async def auto_unacknowledge(self):
        """Wait, then automatically unacknowledge the alarm.
        """
        await asyncio.sleep(self.auto_unacknowledge_delay)
        self.unacknowledge()

    def cancel_auto_acknowledge(self):
        """Cancel automatic acknowledgement, if pending.
        """
        self.timestamp_auto_acknowledge = 0
        self.auto_acknowledge_task.cancel()

    def cancel_auto_unacknowledge(self):
        """Cancel automatic unacknowledgement, if pending.
        """
        self.timestamp_auto_unacknowledge = 0
        self.auto_unacknowledge_task.cancel()

    def mute(self, duration, severity, user):
        """Mute this alarm for a specified duration and severity.

        Parameters
        ----------
        duration : `float`
            How long to mute the alarm (sec).
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to mute. If the alarm's current or max severity
            goes above this level the alarm should be displayed.
        user : `str`
            Name of user who muted this alarm. Used to set ``muted_by``.

        Raises
        ------
        ValueError
            If ``duration <= 0``, ``severity == AlarmSeverity.NONE``
            or ``severity`` is not a valid ``AlarmSeverity`` enum value.

        Notes
        -----
        An alarm cannot have multiple mute levels and durations.
        If mute is called multiple times, the most recent call
        overwrites information from earlier calls.
        """
        if duration <= 0:
            raise ValueError(f"duration={duration} must be positive")
        severity = AlarmSeverity(severity)
        if severity == AlarmSeverity.NONE:
            raise ValueError(f"severity={severity!r} must be > NONE")
        self.muted_by = user
        self.muted_severity = severity
        self.timestamp_unmute = salobj.current_tai() + duration
        self.unmute_task.cancel()
        self.unmute_task = asyncio.create_task(self.unmute_after(duration=duration))
        self._run_callback()

    def unmute(self, run_callback=True):
        """Unmute this alarm.

        Parameters
        ----------
        run_callback : `bool` (optional)
            Run the callback function?
        """
        self.muted_by = ""
        self.muted_severity = AlarmSeverity.NONE
        self.timestamp_unmute = 0
        self.unmute_task.cancel()
        if run_callback:
            self._run_callback()

    async def unmute_after(self, duration):
        """Unmute this alarm after a specified duration.

        Parameters
        ----------
        duration : `float`
            How long to mute the alarm (sec).
        """
        if duration <= 0:
            raise ValueError(f"duration={duration} must be positive")
        await asyncio.sleep(duration)
        self.unmute()

    def reset(self):
        """Reset the alarm to nominal state.

        Do not call the callback function.

        This is designed to be called when enabling the model.
        It sets too many fields to be called by set_severity.
        """
        self.severity = AlarmSeverity.NONE
        self.max_severity = AlarmSeverity.NONE
        self.reason = ""
        self.acknowledged = False
        self.acknowledged_by = ""
        self.escalated = False
        self.escalate_to = ""

        self.timestamp_severity_oldest = 0
        self.timestamp_severity_newest = 0
        self.timestamp_max_severity = 0
        self.timestamp_acknowledged = 0
        self.timestamp_auto_acknowledge = 0
        self.timestamp_auto_unacknowledge = 0
        self.timestamp_escalate = 0

        self.cancel_auto_acknowledge()
        self.cancel_auto_unacknowledge()

        self.unmute(run_callback=False)

    def set_severity(self, severity, reason):
        """Set the severity.

        Parameters
        ----------
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            New severity.
        reason : `str`
            The reason for this state; this should be a brief message
            explaining what is wrong. Ignored if severity is NONE.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (i.e. if any fields were modified),
            False otherwise.
        """
        severity = AlarmSeverity(severity)
        if severity == AlarmSeverity.NONE and self.nominal:
            # Ignore NONE severity when the alarm is already nominal
            # (meaning severity and max_severity are both NONE).
            return False

        curr_tai = salobj.current_tai()
        if self.severity != severity:
            self.timestamp_severity_oldest = curr_tai
            self.severity = severity
        if self.severity != AlarmSeverity.NONE:
            self.reason = reason
        self.timestamp_severity_newest = curr_tai
        if self.severity == AlarmSeverity.NONE:
            if self.acknowledged:
                # Reset the alarm.
                self.reason = ""
                self.acknowledged = False
                self.acknowledged_by = ""
                self.max_severity = AlarmSeverity.NONE
                self.timestamp_acknowledged = curr_tai
                self.timestamp_max_severity = curr_tai
                self.cancel_auto_acknowledge()
                self.cancel_auto_unacknowledge()
            else:
                # Stale alarm; start auto-acknowledge task, if not running
                if self.auto_acknowledge_delay > 0 and self.auto_acknowledge_task.done():
                    self.timestamp_auto_acknowledge = salobj.current_tai() + self.auto_acknowledge_delay
                    self.auto_acknowledge_task = asyncio.create_task(self.auto_acknowledge())
        else:
            self.cancel_auto_acknowledge()
            if self.severity > self.max_severity:
                if self.acknowledged:
                    self.acknowledged = False
                    self.acknowledged_by = ""
                    self.timestamp_acknowledged = curr_tai
                self.max_severity = self.severity
                self.timestamp_max_severity = curr_tai

        self._run_callback()
        return True

    def unacknowledge(self):
        """Unacknowledge the alarm. A no-op if nominal or not acknowledged.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (i.e. if any fields were modified),
            False otherwise.
        """
        self.cancel_auto_unacknowledge()

        if self.nominal or not self.acknowledged:
            return False

        curr_tai = salobj.current_tai()
        self.acknowledged = False
        self.acknowledged_by = ""
        self.timestamp_acknowledged = curr_tai

        self._run_callback()
        return True

    def __eq__(self, other):
        """Return True if two alarms are the same, including state.

        Primarily intended for unit testing.
        """
        for field in ("name",
                      "severity",
                      "reason",
                      "max_severity",
                      "acknowledged",
                      "acknowledged_by",
                      "escalated",
                      "escalate_to",
                      "muted",
                      "muted_severity",
                      "muted_by",
                      "timestamp_severity_oldest",
                      "timestamp_severity_newest",
                      "timestamp_max_severity",
                      "timestamp_acknowledged",
                      "timestamp_escalate",
                      "timestamp_unmute",
                      "callback",
                      ):
            if getattr(self, field) != getattr(other, field):
                return False
        return True

    def __ne__(self, other):
        """Return True if two alarms differ, including state.

        Primarily intended for unit testing.
        """
        return not self.__eq__(other)

    def __repr__(self):
        return f"Alarm(name={self.name})"

    def _run_callback(self):
        if self.callback:
            self.callback(self)
