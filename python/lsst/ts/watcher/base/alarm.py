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
import time

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
    callback : ``callable``
        Function or coroutine to call whenever the alarm changes state.
    """
    def __init__(self, name, callback):
        self.name = name
        self.callback = callback
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
            If ``severity < self.max_severity``

        Notes
        -----
        The reason ``severity`` is an argument is to handle the case that
        a user acknowledges an alarm just as the alarm severity increases.
        To avoid the danger of accidentally acknowledging at a higher
        severity than intended, the command must be rejected.
        """
        if self.nominal or self.acknowledged:
            return False

        severity = AlarmSeverity(severity)
        if severity < self.max_severity:
            raise ValueError(f"severity {severity} < max_severity {self.max_severity}")
        curr_tai = salobj.tai_from_utc(time.time())
        if self.severity == AlarmSeverity.NONE:
            # reset the alarm to nominal
            self.max_severity = AlarmSeverity.NONE
        else:
            self.max_severity = severity
        self.acknowledged = True
        self.acknowledged_by = user
        self.timestamp_acknowledged = curr_tai
        self.timestamp_max_severity = curr_tai

        self._run_callback()
        return True

    def mute(self, duration, severity, user):
        """Mute this alarm for a specified duration.

        Parameters
        ----------
        duration : `float`
            How long to mute the alarm (sec)
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to mute. If the severity goes above
            this level the alarm will be shown.
        user : `str`
            Name of user; used to set muted_by.

        Raises
        ------
        ValueError
            If ``duration <= 0``, ``severity == AlarmSeverity.NONE``
            or ``severity`` is not a valid ``AlarmSeverity`` enum value.
        """
        if duration <= 0:
            raise ValueError(f"duration={duration} must be positive")
        severity = AlarmSeverity(severity)
        if severity == AlarmSeverity.NONE:
            raise ValueError(f"severity={severity!r} must be > NONE")
        self.muted_by = user
        self.muted_severity = severity
        curr_tai = salobj.tai_from_utc(time.time())
        self.timestamp_unmute = curr_tai + duration
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
            How long to mute the alarm (sec)
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
            # ignore NONE state when alarm is alread nominal
            return False

        curr_tai = salobj.tai_from_utc(time.time())
        if self.severity != severity:
            self.timestamp_severity_oldest = curr_tai
            self.severity = severity
        if self.severity != AlarmSeverity.NONE:
            self.reason = reason
        self.timestamp_severity_newest = curr_tai
        if self.severity == AlarmSeverity.NONE and self.acknowledged:
            # reset the alarm
            self.reason = ""
            self.acknowledged = False
            self.acknowledged_by = ""
            self.max_severity = AlarmSeverity.NONE
            self.timestamp_acknowledged = curr_tai
            self.timestamp_max_severity = curr_tai
        elif self.severity > self.max_severity:
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
        if self.nominal or not self.acknowledged:
            return False

        curr_tai = salobj.tai_from_utc(time.time())
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
                      "timestamp_auto_acknowledge",
                      "timestamp_auto_unacknowledge",
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
