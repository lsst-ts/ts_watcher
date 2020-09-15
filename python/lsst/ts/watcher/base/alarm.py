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

    # Field to ignore when testing for equality.
    _eq_ignore_fields = set(
        (
            "auto_acknowledge_task",
            "auto_unacknowledge_task",
            "escalate_task",
            "unmute_task",
        )
    )

    def __init__(self, name):
        self.name = name
        self.callback = None
        self.auto_acknowledge_delay = 0
        self.auto_unacknowledge_delay = 0
        self.escalate_to = ""
        self.escalate_delay = 0
        self.auto_acknowledge_task = salobj.make_done_future()
        self.auto_unacknowledge_task = salobj.make_done_future()
        self.escalate_task = salobj.make_done_future()
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
        return (
            self.severity == AlarmSeverity.NONE
            and self.max_severity == AlarmSeverity.NONE
        )

    def configure(
        self,
        callback=None,
        auto_acknowledge_delay=0,
        auto_unacknowledge_delay=0,
        escalate_to="",
        escalate_delay=0,
    ):
        """Configure the callback function and auto ack/unack delays.

        Parameters
        ----------
        callback : callable, optional
            Function or coroutine to call whenever the alarm changes state,
            or None if no callback wanted.
            The function receives one argument: this alarm.
        auto_acknowledge_delay : `float`, optional
            Delay (in seconds) before a stale alarm is automatically
            acknowledged, or 0 for no automatic acknowledgement.
            A stale alarm is one that has not yet been acknowledged, but its
            severity has gone to NONE.
        auto_unacknowledge_delay : `float`, optional
            Delay (in seconds) before an acknowledged alarm is automatically
            unacknowledged, or 0 for no automatic unacknowledgement.
            Automatic unacknowledgement only occurs if the alarm persists,
            because an acknowledged alarm is reset if severity goes to NONE.
        escalate_to : `str`, optional
            Who or what to escalate the alarm to.
            If "" (the default) the alarm is not escalated.
        escalate_delay : `float`, optional
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 (the default) the alarm is not escalated.
        """
        if auto_acknowledge_delay < 0:
            raise ValueError(
                f"auto_acknowledge_delay={auto_acknowledge_delay} must be >= 0"
            )
        if auto_unacknowledge_delay < 0:
            raise ValueError(
                f"auto_unacknowledge_delay={auto_unacknowledge_delay} must be >= 0"
            )
        self.callback = callback
        self.auto_acknowledge_delay = auto_acknowledge_delay
        self.auto_unacknowledge_delay = auto_unacknowledge_delay
        self.escalate_to = escalate_to
        self.escalate_delay = escalate_delay

    def close(self):
        """Cancel pending tasks.
        """
        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalate()
        self._cancel_unmute()

    def acknowledge(self, severity, user):
        """Acknowledge the alarm.

        Almost a no-op if nominal or acknowledged.
        If acknowledged restart the auto-unack timer, if wanted.

        Parameters
        ----------
        severity : `lsst.ts.idl.enums.Watcher.AlarmSeverity` or `int`
            Severity to acknowledge. Must be >= self.max_severity.
            If the severity goes above this level the alarm will
            unacknowledge itself.
        user : `str`
            Name of user; used to set acknowledged_by.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (any fields were modified
            other than tasks being cancelled),
            False otherwise.

        Raises
        ------
        ValueError
            If ``severity < self.max_severity``
            and the alarm was not already acknowledged.

        Notes
        -----
        The reason ``severity`` is an argument is to handle the case that
        a user acknowledges an alarm just as the alarm severity increases.
        To avoid the danger of accidentally acknowledging at a higher
        severity than intended, the command must be rejected.
        """
        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalate()
        if self.nominal:
            return False

        if self.acknowledged:
            # Restart the auto-unack timer, if relevant.
            if self.severity > AlarmSeverity.NONE and self.auto_unacknowledge_delay > 0:
                self._start_auto_acknowledge_timer()
                return True
            else:
                return False

        curr_tai = salobj.current_tai()

        severity = AlarmSeverity(severity)
        if severity < self.max_severity:
            raise ValueError(f"severity {severity} < max_severity {self.max_severity}")
        if self.severity == AlarmSeverity.NONE:
            # reset the alarm to nominal
            self.max_severity = AlarmSeverity.NONE
        else:
            if self.auto_unacknowledge_delay > 0:
                self._start_auto_acknowledge_timer()
            self.max_severity = severity
        self.acknowledged = True
        self.acknowledged_by = user
        self.timestamp_acknowledged = curr_tai
        self.timestamp_max_severity = curr_tai

        self._run_callback()
        return True

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
        self._cancel_unmute()
        self.muted_by = user
        self.muted_severity = severity
        self.timestamp_unmute = salobj.current_tai() + duration
        self.unmute_task = asyncio.create_task(self._unmute_timer(duration=duration))
        self._run_callback()

    def unmute(self):
        """Unmute this alarm.
        """
        self._cancel_unmute()
        self._run_callback()

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

        self.timestamp_severity_oldest = 0
        self.timestamp_severity_newest = 0
        self.timestamp_max_severity = 0
        self.timestamp_acknowledged = 0

        # These cancel methods reset all associated attributes.
        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalate()
        self._cancel_unmute()

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
                self._cancel_auto_acknowledge()
                self._cancel_auto_unacknowledge()
                self._cancel_escalate()
            else:
                # Stale alarm; start auto-acknowledge task, if not running
                if (
                    self.auto_acknowledge_delay > 0
                    and self.auto_acknowledge_task.done()
                ):
                    # Set the timestamp here, rather than the timer method,
                    # so it is set before the callback runs.
                    self.timestamp_auto_acknowledge = (
                        salobj.current_tai() + self.auto_acknowledge_delay
                    )
                    self.auto_acknowledge_task = asyncio.create_task(
                        self._auto_acknowledge_timer()
                    )
        else:
            self._cancel_auto_acknowledge()
            if self.severity > self.max_severity:
                if self.acknowledged:
                    self.acknowledged = False
                    self.acknowledged_by = ""
                    self.timestamp_acknowledged = curr_tai
                self.max_severity = self.severity
                self.timestamp_max_severity = curr_tai

                # If alarm is newly critical and escalation wanted,
                # start the escalation timer.
                if (
                    self.severity == AlarmSeverity.CRITICAL
                    and self.escalate_delay > 0
                    and self.escalate_to != ""
                ):
                    self._cancel_escalate()
                    # Set the timestamp here, rather than the timer method,
                    # so it is set before the callback runs.
                    self.timestamp_escalate = salobj.current_tai() + self.escalate_delay
                    self.escalate_task = asyncio.create_task(self._escalate_timer())

        self._run_callback()
        return True

    def unacknowledge(self, escalate=True):
        """Unacknowledge the alarm. Basically a no-op if nominal
        or not acknowledged.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (i.e. if any fields were modified),
            False otherwise.
        escalate : `bool`, optional
            Restart the escalation timer?
            Only relevant if max_severity is CRITICAL.
        """
        self._cancel_auto_unacknowledge()

        if self.nominal or not self.acknowledged:
            return False

        curr_tai = salobj.current_tai()
        self.acknowledged = False
        self.acknowledged_by = ""
        self.timestamp_acknowledged = curr_tai
        if escalate and self.max_severity == AlarmSeverity.CRITICAL:
            self.escalate_task = asyncio.create_task(self._escalate_timer())

        self._run_callback()
        return True

    def assert_equal(self, other, ignore_attrs=()):
        """Assert that this alarm equals another alarm.

        Compares all attributes except tasks and those specified
        in ignore_attrs.

        Parameters
        ----------
        other : `Alarm`
            Alarm to compare.
        ignore_attrs : `list` [`str`], optional
            Sequence of attribute names to ignore (in addition to task
            attributes, which are always ignored.)
        """
        self_vars = vars(self)
        other_vars = vars(other)
        all_ignore_fields = set(ignore_attrs) | self._eq_ignore_fields
        diffs = [
            f"self.{name}={self_vars[name]} != other.{name}={other_vars[name]}"
            for name in self_vars
            if name not in all_ignore_fields and self_vars[name] != other_vars[name]
        ]
        if diffs:
            error_str = ", ".join(diffs)
            raise AssertionError(error_str)

    def __eq__(self, other):
        """Return True if two alarms are the same, including state.

        All fields are compared except task fields.

        Primarily intended for unit testing, though `assert_equal`
        gives more useful output.
        """
        self_vars = vars(self)
        other_vars = vars(other)
        return all(
            self_vars[name] == other_vars[name]
            for name in self_vars
            if name not in self._eq_ignore_fields
        )

    def __ne__(self, other):
        """Return True if two alarms differ, including state.

        Primarily intended for unit testing.
        """
        return not self.__eq__(other)

    def __repr__(self):
        return f"Alarm(name={self.name})"

    async def _auto_acknowledge_timer(self):
        """Wait, then automatically acknowledge the alarm.
        """
        await asyncio.sleep(self.auto_acknowledge_delay)
        self.acknowledge(severity=self.max_severity, user="automatic")

    async def _auto_unacknowledge_timer(self):
        """Wait, then automatically unacknowledge the alarm.

        Does not restart the escalation timer
        (unlike manual unacknowledgement).
        """
        await asyncio.sleep(self.auto_unacknowledge_delay)
        self.unacknowledge(escalate=False)

    async def _escalate_timer(self):
        """Wait, then escalate this alarm.
        """
        await asyncio.sleep(self.escalate_delay)
        self.escalated = True
        self._run_callback()

    async def _unmute_timer(self, duration):
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

    def _cancel_auto_acknowledge(self):
        """Cancel the auto acknowledge timer, if pending.
        """
        self.timestamp_auto_acknowledge = 0
        self.auto_acknowledge_task.cancel()

    def _cancel_auto_unacknowledge(self):
        """Cancel the auto unacknowledge timer, if pending.
        """
        self.timestamp_auto_unacknowledge = 0
        self.auto_unacknowledge_task.cancel()

    def _cancel_escalate(self):
        """Cancel the escalate timer, if pending.
        """
        self.timestamp_escalate = 0
        self.escalate_task.cancel()

    def _cancel_unmute(self):
        """Cancel the unmute timer, if running.
        """
        self.muted_by = ""
        self.muted_severity = AlarmSeverity.NONE
        self.timestamp_unmute = 0
        self.unmute_task.cancel()

    def _run_callback(self):
        """Run the callback function, if present.
        """
        if self.callback:
            self.callback(self)

    def _start_auto_acknowledge_timer(self):
        """Start the auto_acknowledge timer.
        """
        self.auto_unacknowledge_task.cancel()
        # Set the timestamp here, rather than the timer method,
        # so it is set before the background task starts.
        self.timestamp_auto_unacknowledge = (
            salobj.current_tai() + self.auto_unacknowledge_delay
        )
        self.auto_unacknowledge_task = asyncio.create_task(
            self._auto_unacknowledge_timer()
        )
