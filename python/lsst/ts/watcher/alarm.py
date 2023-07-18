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

__all__ = ["Alarm"]

import asyncio
import inspect

from lsst.ts import utils
from lsst.ts.idl.enums.Watcher import AlarmSeverity

# Default timeout for Alarm.assert_next_severity
DEFAULT_NEXT_SEVERITY_TIMEOUT = 10


class Alarm:
    """A Watcher alarm.

    Parameters
    ----------
    name : `str`
        Name of alarm. This must be unique among all alarms
        and should be of the form system.[subsystem....]_name
        so that groups of related alarms can be acknowledged.

    Attributes
    ----------
    name : `str`
        Name of alarm.
    acknowledged_by : `str`
        The ``user`` argument when the alarm is acknowledged.
        "" if not acknowledged.
    auto_acknowledge_delay : `float`
        The delay (seconds) after which an alarm will be automatically
        acknowledged. Never if 0 (the default).
    auto_unacknowledge_delay : `float`
        The delay (seconds) after which an alarm will be automatically
        unacknowleddged. Never if 0 (the default).
    do_escalate : `bool`
        Should the alarm be escalated? The value is set by this class
        and is intended to be read by the alarm callback.
    escalation_delay : `float`
        If an alarm goes to critical state and remains unacknowledged
        for this period of time (seconds), the alarm should be escalated.
        If 0, the alarm will not be escalated.
    escalation_responder : `str`
        Who or what to escalate the alarm to.
        If blank, the alarm will not be escalated.
    escalated_id : `str`
        ID of the SquadCast escalation alert. "" if not escalated.
        Set to "Failed: {reason}" if escalation failed.
        This is set to "" by `reset`, and intended to be set to
        non-empty values by the alarm callback.
    severity_queue : `asyncio.Queue` or `None`
        Intended only for unit tests.
        Defaults to None. If a unit test sets this to an `asyncio.Queue`,
        `set_severity` will queue the severity every time it returns True.
    auto_acknowledge_task :  : `asyncio.Future`
        A task that monitors the automatic acknowledge timer.
    auto_unacknowledge_task :  : `asyncio.Future`
        A task that monitors the automatic unacknowledge timer.
    escalating_task : `asyncio.Future`
        A task that monitors the process of escalating an alarm to a
        notification service such as SquadCast. This timer is managed
        by WatcherCsc, because it knows how to communicate with the
        notification service.
    escalation_timer_task : `asyncio.Future`
        A task that monitors the escalation timer. When this timer fires,
        it sets do_escalate to true and calls the callback. It is then
        up the CSC to actually escalate the alarm (see escalating_task).
    unmute_task :  : `asyncio.Future`
        A task that monitors the unmute timer.
    """

    # Field to ignore when testing for equality.
    _eq_ignore_fields = set(
        (
            "auto_acknowledge_task",
            "auto_unacknowledge_task",
            "escalation_timer_task",
            "escalating_task",
            "unmute_task",
            "severity_queue",
        )
    )

    def __init__(self, name):
        self.name = name
        self._callback = None
        self.auto_acknowledge_delay = 0
        self.auto_unacknowledge_delay = 0
        self.configure_escalation(escalation_delay=0, escalation_responder="")
        self.auto_acknowledge_task = utils.make_done_future()
        self.auto_unacknowledge_task = utils.make_done_future()
        self.escalating_task = utils.make_done_future()
        self.escalation_timer_task = utils.make_done_future()
        self.unmute_task = utils.make_done_future()
        self.severity_queue = None
        self.reset()

    @property
    def muted(self):
        """Is this alarm muted?"""
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

    def configure_basics(
        self,
        callback=None,
        auto_acknowledge_delay=0,
        auto_unacknowledge_delay=0,
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

    def configure_escalation(self, escalation_delay, escalation_responder):
        """Configure escalation.

        Set the following attributes:

        * escalation_delay
        * escalation_responder

        Parameters
        ----------
        escalation_delay : `float`
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 the alarm is not escalated.
        escalation_responder : `str`
            Who or what to escalate the alarm to.
            If blank, the alarm will not be escalated.

        Raises
        ------
        ValueError
            If escalation_delay < 0.
            If escalation_delay > 0 and escalation_responder empty,
            or escalation_delay = 0 and escalation_responder not empty.
        TypeError
            If escalation_responder is not a str.
        """
        if escalation_delay < 0:
            raise ValueError(f"{escalation_delay=} must be ≥ 0")
        if (escalation_delay == 0) != (len(escalation_responder) == 0):
            raise ValueError(
                f"{escalation_delay=} must be > 0 if and only if"
                f"{escalation_responder=} is not empty"
            )
        if not isinstance(escalation_responder, str):
            raise TypeError(f"{escalation_responder=!r} must be a str")
        self.escalation_responder = escalation_responder
        self.escalation_delay = escalation_delay

    def close(self):
        """Cancel pending tasks."""
        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalation_timer()
        self._cancel_unmute()

    async def acknowledge(self, severity, user):
        """Acknowledge the alarm.

        Halt the escalation timer, if running, and set do_escalate False.
        Restart the auto unacknowledge timer, if configured
        (self.auto_unacknowledge_delay > 0).

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
            If ``severity < self.max_severity``. In this case the acknowledge
            method does not change the alarm state.

        Notes
        -----
        The reason ``severity`` is an argument is to handle the case that
        a user acknowledges an alarm just as the alarm severity increases.
        To avoid the danger of accidentally acknowledging an alarm at a
        higher severity than intended, the acknowledgement is rejected.
        """
        severity = AlarmSeverity(severity)
        if severity < self.max_severity:
            raise ValueError(f"severity {severity} < max_severity {self.max_severity}")

        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalation_timer()
        self.escalating_task.cancel()
        self.do_escalate = False
        if self.nominal:
            return False

        if self.acknowledged:
            # Restart the auto-unack timer, if relevant.
            if self.severity > AlarmSeverity.NONE and self.auto_unacknowledge_delay > 0:
                self._start_auto_acknowledge_timer()
                return True
            else:
                return False

        curr_tai = utils.current_tai()

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

        await self.run_callback()
        return True

    async def mute(self, duration, severity, user):
        """Mute this alarm for a specified duration and severity.

        Muting also cancels the escalation timer.

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
        self._cancel_escalation_timer()
        self.muted_by = user
        self.muted_severity = severity
        self.timestamp_unmute = utils.current_tai() + duration
        self.unmute_task = asyncio.create_task(self._unmute_timer(duration=duration))
        await self.run_callback()

    async def unmute(self):
        """Unmute this alarm."""
        self._cancel_unmute()
        if self.max_severity == AlarmSeverity.CRITICAL and not self.acknowledged:
            self._start_escalation_timer()
        await self.run_callback()

    def reset(self):
        """Reset the alarm to nominal state.

        Do not call the callback function.
        This is designed to be called by Model.enable,
        which first resets alarms and then feeds them data
        before writing alarm state.

        It sets too many fields to be called by set_severity.
        """
        self.severity = AlarmSeverity.NONE
        self.max_severity = AlarmSeverity.NONE
        self.reason = ""
        self.acknowledged = False
        self.acknowledged_by = ""
        self.do_escalate = False
        self.escalated_id = ""

        self.timestamp_severity_oldest = 0
        self.timestamp_severity_newest = 0
        self.timestamp_max_severity = 0
        self.timestamp_acknowledged = 0

        # These cancel methods reset all associated attributes.
        self._cancel_auto_acknowledge()
        self._cancel_auto_unacknowledge()
        self._cancel_escalation_timer()
        self._cancel_unmute()

    async def set_severity(self, severity, reason):
        """Set the severity.

        Call the callback function unless the alarm was nominal
        and remains nominal.
        Put the new severity on the severity queue (if it exists),
        regardless of whether the alarm was nominal.

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
            # (meaning severity and max_severity are both NONE),
            # except queue the severity if there is a queue.
            if self.severity_queue is not None:
                self.severity_queue.put_nowait(severity)
            return False

        curr_tai = utils.current_tai()
        if self.severity != severity:
            self.timestamp_severity_oldest = curr_tai
            self.severity = severity
        if self.severity != AlarmSeverity.NONE:
            self.reason = reason
        if (
            self.severity != AlarmSeverity.CRITICAL
            and not self.escalation_timer_task.done()
        ):
            # Cancel escalation if alarm is no longer critical. The Observing
            # Specialists will never get used to acknowledging alarms that are
            # no longer critical. It is best to cancel escalation if they
            # resolve the issue in time.
            self._cancel_escalation_timer()

        self.timestamp_severity_newest = curr_tai
        if self.severity == AlarmSeverity.NONE:
            if self.acknowledged:
                # Reset the alarm.
                self.reason = ""
                self.acknowledged = False
                self.acknowledged_by = ""
                self.do_escalate = False
                self.max_severity = AlarmSeverity.NONE
                self.timestamp_acknowledged = curr_tai
                self.timestamp_max_severity = curr_tai
                self._cancel_auto_acknowledge()
                self._cancel_auto_unacknowledge()
                self.escalating_task.cancel()
            else:
                # Stale alarm; start auto-acknowledge task, if not running
                if (
                    self.auto_acknowledge_delay > 0
                    and self.auto_acknowledge_task.done()
                ):
                    # Set the timestamp here, rather than the timer method,
                    # so it is set before the callback runs.
                    self.timestamp_auto_acknowledge = (
                        utils.current_tai() + self.auto_acknowledge_delay
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
                if self.severity == AlarmSeverity.CRITICAL:
                    self._start_escalation_timer()

        if self.severity_queue is not None:
            self.severity_queue.put_nowait(severity)
        await self.run_callback()
        return True

    async def unacknowledge(self, escalate=True):
        """Unacknowledge the alarm. Basically a no-op if nominal
        or not acknowledged.

        Parameters
        ----------
        escalate : `bool`, optional
            Escalate the alarm, if max_severity is critical? Defaults to true.
            Only set false if automatically unacknowledging the alarm.

        Returns
        -------
        updated : `bool`
            True if the alarm state changed (i.e. if any fields were modified),
            False otherwise.
        """
        self._cancel_auto_unacknowledge()

        if self.nominal or not self.acknowledged:
            return False

        curr_tai = utils.current_tai()
        self.acknowledged = False
        self.acknowledged_by = ""
        self.timestamp_acknowledged = curr_tai
        if escalate and self.max_severity == AlarmSeverity.CRITICAL:
            self._start_escalation_timer()

        await self.run_callback()
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

    async def assert_next_severity(
        self,
        expected_severity,
        check_empty=True,
        flush=False,
        timeout=DEFAULT_NEXT_SEVERITY_TIMEOUT,
    ):
        """Wait for and check the next severity.

        Only intended for tests.
        In order to call this you must first call `init_severity_queue`
        (once) to set up a severity queue.

        Parameters
        ----------
        expected_severity : `AlarmSeverity`
            The expected severity.
        check_empty : `bool`, optional
            If true (the default): check that the severity queue is empty,
            after getting the severity.
        flush : `bool`, optional
            If true (not the default): flush all existing values
            from the queue, then wait for the next severity.
            This is useful for polling alarms.
        timeout : `float`, optional
            Maximum time to wait (seconds)

        Raises
        ------
        AssertionError
            If the severity is not as expected, or if ``check_empty`` true
            and there are additional queued severities.
        asyncio.TimeoutError
            If no new severity is seen in time.
        RuntimeError
            If you never called `init_severity_queue`.

        Notes
        -----
        Here is the typical way to use this method:
        * Create a rule
        * Call `rule.alarm.init_severity_queue()`
        * Write SAL messages that are expected to change the alarm severity.
        * After writing each such message, call::

            await rule.alarm.assert_next_severity(expected_severity)
        """
        if self.severity_queue is None:
            raise RuntimeError(
                "No severity queue; you must call init_severity_queue "
                "(once) before calling assert_next_severity"
            )
        if flush:
            while not self.severity_queue.empty():
                self.severity_queue.get_nowait()
        severity = await asyncio.wait_for(self.severity_queue.get(), timeout=timeout)
        if check_empty:
            extra_severities = [
                self.severity_queue.get_nowait()
                for i in range(self.severity_queue.qsize())
            ]
            if extra_severities:
                raise AssertionError(
                    f"severity_queue was not empty; it contained {extra_severities}"
                )
        if severity != expected_severity:
            raise AssertionError(
                f"severity={severity!r} != expected_severity{expected_severity!r}"
            )

    def init_severity_queue(self):
        """Initialize the severity queue.

        You must call this once before calling `assert_next_severity`.
        You may call it again to reset the queue, but that is uncommon.

        Warnings
        --------
        Only tests should call this method.
        Calling this in production code will cause a memory leak.
        """
        self.severity_queue = asyncio.Queue()

    def __eq__(self, other):
        """Return True if two alarms are the same, including state.

        All fields are compared except task fields and the severity queue.

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

    @property
    def callback(self):
        """Get the callback function."""
        return self._callback

    @callback.setter
    def callback(self, callback):
        """Set or clear the callback function.

        Parameters
        ----------
        callback : callable, optional
            Coroutine (async function) to call whenever the alarm
            changes state, or None if no callback wanted.
            The coroutine receives one argument: this alarm.

        Raises
        ------
        TypeError
            If callback is not None and not a coroutine.
        """
        if callback is not None and not inspect.iscoroutinefunction(callback):
            raise TypeError(f"callback={callback} must be async")
        self._callback = callback

    async def _auto_acknowledge_timer(self):
        """Wait, then automatically acknowledge the alarm."""
        await asyncio.sleep(self.auto_acknowledge_delay)
        await self.acknowledge(severity=self.max_severity, user="automatic")

    async def _auto_unacknowledge_timer(self):
        """Wait, then automatically unacknowledge the alarm.

        Does not restart the escalation timer
        (unlike manual unacknowledgement).
        """
        await asyncio.sleep(self.auto_unacknowledge_delay)
        await self.unacknowledge(escalate=False)

    async def _escalation_timer(self):
        """Wait, then escalate this alarm."""
        await asyncio.sleep(self.escalation_delay)
        self.do_escalate = True
        await self.run_callback()

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
        await self.unmute()

    def _cancel_auto_acknowledge(self):
        """Cancel the auto acknowledge timer, if pending."""
        self.timestamp_auto_acknowledge = 0
        self.auto_acknowledge_task.cancel()

    def _cancel_auto_unacknowledge(self):
        """Cancel the auto unacknowledge timer, if pending."""
        self.timestamp_auto_unacknowledge = 0
        self.auto_unacknowledge_task.cancel()

    def _cancel_escalation_timer(self):
        """Cancel the escalate timer, if pending."""
        self.timestamp_escalate = 0
        self.escalation_timer_task.cancel()

    def _cancel_unmute(self):
        """Cancel the unmute timer, if running."""
        self.muted_by = ""
        self.muted_severity = AlarmSeverity.NONE
        self.timestamp_unmute = 0
        self.unmute_task.cancel()

    async def run_callback(self):
        """Run the callback function, if present."""
        if self._callback:
            await self._callback(self)

    def _start_auto_acknowledge_timer(self):
        """Start or restart the auto_acknowledge timer."""
        self.auto_unacknowledge_task.cancel()
        # Set the timestamp here, rather than the timer method,
        # so it is set before the background task starts.
        self.timestamp_auto_unacknowledge = (
            utils.current_tai() + self.auto_unacknowledge_delay
        )
        self.auto_unacknowledge_task = asyncio.create_task(
            self._auto_unacknowledge_timer()
        )

    def _start_escalation_timer(self):
        """Start or restart the escalation timer, if escalation configured.

        A no-op if escalation is not configured.
        """
        if self.escalation_delay <= 0 or not self.escalation_responder:
            # Escalation not configured
            return
        self._cancel_escalation_timer()
        # Set the timestamp here, rather than the timer method,
        # so it is set before the callback runs.
        self.timestamp_escalate = utils.current_tai() + self.escalation_delay
        self.escalation_timer_task = asyncio.create_task(self._escalation_timer())
