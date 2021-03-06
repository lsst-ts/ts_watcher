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

import asyncio
import copy
import itertools
import unittest

import asynctest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


STD_TIMEOUT = 2  # seconds


class AlarmTestCase(asynctest.TestCase):
    # NOTE: almost all test methods must be async, even with no visible
    # async code, so that Alarm has an event loop.
    def setUp(self):
        self.callback_queue = asyncio.Queue()
        self._alarms = []  # Alarms to close in tearDown.

    def tearDown(self):
        for alarm in self._alarms:
            alarm.close()

    def callback(self, alarm):
        self.callback_queue.put_nowait(alarm)

    async def next_queued_alarm(self, expected_alarm=None, timeout=STD_TIMEOUT):
        """Get the next alarm queued by `callback`.

        Parameters
        ----------
        expected_alarm : `lsst.ts.watcher.base.Alarm` or `None`, optional
            The alarm that should be returned.
            If None (the default) then this is not checked.
        timeout : `float`
            Time limit for waiting (seconds).
        """
        alarm = await asyncio.wait_for(self.callback_queue.get(), timeout=STD_TIMEOUT)
        if expected_alarm is not None:
            self.assertIs(alarm, expected_alarm)
        return alarm

    @property
    def ncalls(self):
        return self.callback_queue.qsize()

    def alarm_iter(
        self,
        callback,
        name="test.alarm",
        auto_acknowledge_delay=0,
        auto_unacknowledge_delay=0,
        escalate_to="",
        escalate_delay=0,
    ):
        """An iterator over alarms with all allowed values of
        severity and max_severity.

        Parameters
        ----------
        callback : callable or `None`
            Callback function; must take one argument: an alarm.
            None for no callback function.
        name : `str`, optional
            Name of alarm.
        auto_acknowledge_delay : `float`, optional
            Delay (in seconds) before a stale alarm is automatically
            acknowledged, or 0 for no automatic acknowledgement.
        auto_unacknowledge_delay : `float`, optional
            Delay (in seconds) before an acknowledged alarm is automatically
            unacknowledged, or 0 for no automatic unacknowledgement.
        escalate_to : `str`, optional
            Who or what to escalate the alarm to.
            If "" (the default) the alarm is not escalated.
        escalate_delay : `float`, optional
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 (the default) the alarm is not escalated.

        Notes
        -----
        The callback function is not called by this iterator,
        so this iterator does not change `self.ncalls`.
        """

        def _alarm_iter_impl():
            """An iterator over alarms with all allowed values of
            severity and max_severity and no callback function.

            Assign the callback later, if desired.
            """
            alarm_kwargs = dict(
                name=name,
                auto_acknowledge_delay=auto_acknowledge_delay,
                auto_unacknowledge_delay=auto_unacknowledge_delay,
                escalate_to=escalate_to,
                escalate_delay=escalate_delay,
            )

            severities = list(AlarmSeverity)
            yield self.make_alarm(**alarm_kwargs)
            for i, severity in enumerate(severities[1:]):
                alarm = self.make_alarm(**alarm_kwargs)
                reason = f"alarm_iter set severity={severity}"
                updated = alarm.set_severity(severity=severity, reason=reason)
                self.assertTrue(updated)
                yield alarm

            for i, max_severity in enumerate(severities[1:]):
                for severity in severities[0 : i + 1]:
                    alarm = self.make_alarm(**alarm_kwargs)
                    updated = alarm.set_severity(severity=max_severity, reason=reason)
                    self.assertTrue(updated)
                    reason = f"alarm_iter set severity to {severity} after setting it to {max_severity}"
                    updated = alarm.set_severity(severity=severity, reason=reason)
                    self.assertTrue(updated)
                    yield alarm

        for alarm in _alarm_iter_impl():
            alarm.callback = callback
            yield alarm

    def copy_alarm(self, alarm):
        """Return a shallow copy of an alarm and schedule it to be closed.

        Parameters
        ----------
        alarm : `lsst.ts.watcher.base.Alarm`
            The alarm to copy.
        """
        alarm_copy = copy.copy(alarm)
        self._alarms.append(alarm_copy)
        return alarm_copy

    def make_alarm(
        self,
        name,
        callback=None,
        auto_acknowledge_delay=0,
        auto_unacknowledge_delay=0,
        escalate_to="",
        escalate_delay=0,
    ):
        """Make an alarm and keep a reference so tearDown can close it.

        Parameters
        ----------
        name : `str`
            Name of alarm.
        callback : callable or `None`, optional
            Callback function; must take one argument: an alarm.
            None for no callback function.
        auto_acknowledge_delay : `float`, optional
            Delay (in seconds) before a stale alarm is automatically
            acknowledged, or 0 for no automatic acknowledgement.
        auto_unacknowledge_delay : `float`, optional
            Delay (in seconds) before an acknowledged alarm is automatically
            unacknowledged, or 0 for no automatic unacknowledgement.
        escalate_to : `str`, optional
            Who or what to escalate the alarm to.
            If "" (the default) the alarm is not escalated.
        escalate_delay : `float`, optional
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 (the default) the alarm is not escalated.
        """
        alarm = watcher.base.Alarm(name=name)
        alarm.configure(
            callback=callback,
            auto_acknowledge_delay=auto_acknowledge_delay,
            auto_unacknowledge_delay=auto_unacknowledge_delay,
            escalate_to=escalate_to,
            escalate_delay=escalate_delay,
        )
        self._alarms.append(alarm)
        return alarm

    async def test_auto_acknowledge(self):
        auto_acknowledge_delay = 0.5
        # The timer should not start until the alarm is stale.
        alarm = self.make_alarm(
            name="test",
            callback=self.callback,
            auto_acknowledge_delay=auto_acknowledge_delay,
        )
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.auto_acknowledge_delay, auto_acknowledge_delay)
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

        alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        self.assertFalse(alarm.nominal)
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

        # Now set severity None, making the alarm stale
        t0 = salobj.current_tai()
        alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        # Give the auto acknowledgement task time to start
        curr_tai = salobj.current_tai()
        dt = curr_tai - t0
        predicted_auto_ack_tai = curr_tai + auto_acknowledge_delay
        self.assertFalse(alarm.nominal)
        self.assertAlmostEqual(
            alarm.timestamp_auto_acknowledge, predicted_auto_ack_tai, delta=dt
        )
        await asyncio.sleep(0)
        self.assertFalse(alarm.auto_acknowledge_task.done())

        # Wait less than auto_acknowledge_delay and check that
        # the alarm has not yet been automatically acknowledged
        await asyncio.sleep(auto_acknowledge_delay / 2)
        self.assertEqual(alarm.max_severity, AlarmSeverity.WARNING)
        self.assertFalse(alarm.acknowledged)
        self.assertFalse(alarm.nominal)

        # Set alarm severity > NONE and check that the automatic
        # acknowledgement task has been canceled.
        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        self.assertFalse(alarm.nominal)
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        await asyncio.sleep(0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

        # Make the alarm stale again and wait for automatic acknowledgement
        alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        self.assertFalse(alarm.nominal)
        await asyncio.sleep(0)
        self.assertFalse(alarm.auto_acknowledge_task.done())

        # Wait the rest of the needed time and check that the alarm
        # has been automatically acknowledged.
        await asyncio.sleep(auto_acknowledge_delay + 0.001)
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.acknowledged_by, "automatic")

    async def test_auto_unacknowledge(self):
        user = "chaos"
        auto_unacknowledge_delay = 0.5
        # The timer should not start until the alarm is stale.
        alarm = self.make_alarm(
            name="test",
            callback=self.callback,
            auto_unacknowledge_delay=auto_unacknowledge_delay,
        )
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.auto_unacknowledge_delay, auto_unacknowledge_delay)
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

        # Make an alarm condition and check that the auto-unack task
        # is not running yet.
        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        self.assertFalse(alarm.acknowledged)
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        await asyncio.sleep(0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

        # Acknowledge the alarm; the auto-unack task should now be running
        t0 = salobj.current_tai()
        alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        curr_tai = salobj.current_tai()
        dt = curr_tai - t0
        predicted_auto_unack_tai = curr_tai + auto_unacknowledge_delay
        self.assertAlmostEqual(
            alarm.timestamp_auto_unacknowledge, predicted_auto_unack_tai, delta=dt
        )
        self.assertTrue(alarm.acknowledged)
        await asyncio.sleep(0)
        self.assertFalse(alarm.auto_unacknowledge_task.done())

        # Wait less time than auto unack and manually unack the alarm;
        # this should cancel the auto unack task.
        await asyncio.sleep(auto_unacknowledge_delay / 2)
        self.assertTrue(alarm.acknowledged)
        alarm.unacknowledge()
        self.assertFalse(alarm.acknowledged)
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        await asyncio.sleep(0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

        # Acknowledge the alarm again
        alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        self.assertTrue(alarm.acknowledged)
        self.assertGreater(alarm.timestamp_auto_unacknowledge, 0)
        await asyncio.sleep(0)
        self.assertFalse(alarm.auto_unacknowledge_task.done())

        # Wait less time than auto unack and set severity NONE;
        # this should make the alarm nominal and cancel the auto unack
        await asyncio.sleep(auto_unacknowledge_delay / 2)
        alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        await asyncio.sleep(0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

        # Set severity > NONE again, acknowledge,
        # and wait the full time for auto unack
        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        self.assertTrue(alarm.acknowledged)
        self.assertGreater(alarm.timestamp_auto_unacknowledge, 0)
        await asyncio.sleep(0)
        self.assertFalse(alarm.auto_unacknowledge_task.done())

        await asyncio.sleep(auto_unacknowledge_delay + 0.001)
        self.assertFalse(alarm.acknowledged)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

    async def test_noauto_acknowledge(self):
        # Set auto_acknowledge_delay = 0 to prevent automatic acknowledgement
        alarm = self.make_alarm(
            name="test", callback=self.callback, auto_acknowledge_delay=0
        )
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.auto_acknowledge_delay, 0)
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

        # Make alarm stale by setting severity > NONE then to NONE
        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="why not?")
        alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        self.assertFalse(alarm.nominal)
        self.assertFalse(alarm.acknowledged)

        # Verify that auto acknowledgement is not running.
        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
        self.assertTrue(alarm.auto_acknowledge_task.done())

    async def test_noauto_unacknowledge(self):
        # Set auto_unacknowledge_delay = 0 to prevent automatic unack
        alarm = self.make_alarm(
            name="test", callback=self.callback, auto_unacknowledge_delay=0
        )
        self.assertTrue(alarm.nominal)
        self.assertEqual(alarm.auto_unacknowledge_delay, 0)
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

        # Make an acknowledged alarm.
        alarm.set_severity(severity=AlarmSeverity.WARNING, reason="why not?")
        alarm.acknowledge(severity=alarm.severity, user="chaos")
        self.assertFalse(alarm.nominal)
        self.assertTrue(alarm.acknowledged)

        # Verify that auto unacknowledgement is not running.
        self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
        self.assertTrue(alarm.auto_unacknowledge_task.done())

    async def test_alarm_iter(self):
        nseverities = len(AlarmSeverity)

        # Default arguments to self.alarm_iter
        default_kwargs = dict(
            name="test.alarm",
            auto_acknowledge_delay=0,
            auto_unacknowledge_delay=0,
            escalate_to="",
            escalate_delay=0,
        )
        for callback, kwargs in itertools.product(
            (None, self.callback),
            (
                dict(),
                dict(name="foo"),
                dict(auto_acknowledge_delay=1),
                dict(auto_unacknowledge_delay=2),
                # Set both escalate_to and escalate_delay
                # to enable escalation.
                dict(escalate_to="chaos", escalate_delay=3),
            ),
        ):

            def assert_expected(alarm):
                """Assert that all alarm fields that can be specified
                when calling `alarm_iter` have the expected value.
                """
                for argname, default_value in default_kwargs.items():
                    expected_value = kwargs.get(argname, default_value)
                    self.assertEqual(
                        getattr(alarm, argname), expected_value, msg=argname
                    )

            severity_set = set()
            nitems = 0
            predicted_nitems = nseverities * (nseverities + 1) // 2
            for alarm in self.alarm_iter(callback=callback, **kwargs):
                nitems += 1
                self.assertEqual(self.ncalls, 0)
                self.assertEqual(alarm.callback, callback)
                assert_expected(alarm)

                self.assertGreaterEqual(alarm.max_severity, alarm.severity)
                self.assertFalse(alarm.acknowledged)
                self.assertEqual(alarm.acknowledged_by, "")
                self.assertFalse(alarm.escalated)
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertEqual(alarm.muted_by, "")
                if nitems == 1:
                    # first state is NONE, alarm is nominal
                    self.assertTrue(alarm.nominal)
                    self.assertEqual(alarm.timestamp_severity_oldest, 0)
                    self.assertEqual(alarm.timestamp_severity_newest, 0)
                    self.assertEqual(alarm.timestamp_max_severity, 0)
                else:
                    self.assertFalse(alarm.nominal)
                    self.assertGreater(alarm.timestamp_severity_oldest, 0)
                    self.assertGreater(alarm.timestamp_severity_newest, 0)
                    self.assertGreater(alarm.timestamp_max_severity, 0)

                self.assertEqual(alarm.timestamp_acknowledged, 0)
                self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)

                stale_alarm = (
                    alarm.severity == AlarmSeverity.NONE
                    and alarm.max_severity > AlarmSeverity.NONE
                )
                if stale_alarm and alarm.auto_acknowledge_delay > 0:
                    self.assertGreater(alarm.timestamp_auto_acknowledge, 0)
                else:
                    self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
                self.assertGreaterEqual(
                    alarm.timestamp_severity_newest, alarm.timestamp_severity_oldest
                )

                auto_escalate = (
                    alarm.max_severity == AlarmSeverity.CRITICAL
                    and alarm.escalate_delay > 0
                    and alarm.escalate_to != ""
                )
                if auto_escalate:
                    self.assertGreater(alarm.timestamp_escalate, 0)
                else:
                    self.assertEqual(alarm.timestamp_escalate, 0)
                self.assertEqual(alarm.timestamp_unmute, 0)
                severity_set.add((alarm.severity, alarm.max_severity))
            self.assertEqual(nitems, predicted_nitems)
            self.assertEqual(nitems, len(severity_set))

    async def test_equality(self):
        """Test __eq__ and __ne__

        This is a rather crude test in that it sets fields to
        invalid values.
        """
        alarm0 = self.make_alarm(name="foo", callback=self.callback)
        alarm = self.copy_alarm(alarm0)
        self.assertTrue(alarm == alarm0)
        self.assertFalse(alarm != alarm0)
        alarm.assert_equal(alarm0)
        for fieldname, value in vars(alarm).items():
            if fieldname.endswith("_task"):
                continue
            with self.subTest(fieldname=fieldname):
                alarm = self.copy_alarm(alarm0)
                setattr(alarm, fieldname, 5)
                self.assertFalse(alarm == alarm0)
                self.assertTrue(alarm != alarm0)
                alarm.assert_equal(alarm0, ignore_attrs=[fieldname])

    async def test_constructor(self):
        name = "test_fairly_long_alarm_name"
        alarm = self.make_alarm(name=name, callback=self.callback)
        self.assertEqual(alarm.name, name)
        self.assertEqual(alarm.callback, self.callback)
        self.assertTrue(alarm.nominal)
        self.assertFalse(alarm.acknowledged)
        self.assertEqual(alarm.severity, AlarmSeverity.NONE)
        self.assertEqual(alarm.max_severity, AlarmSeverity.NONE)
        self.assertEqual(alarm.reason, "")
        self.assertEqual(alarm.acknowledged_by, "")
        self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
        self.assertTrue(alarm.nominal)

    async def test_config_errors(self):
        alarm = self.make_alarm(name="test")
        with self.assertRaises(ValueError):
            alarm.configure(auto_acknowledge_delay=-0.001)
        with self.assertRaises(ValueError):
            alarm.configure(auto_unacknowledge_delay=-0.001)

    async def test_none_severity_when_nominal(self):
        """Test that set_severity to NONE has no effect if nominal."""
        alarm = self.make_alarm(name="an_alarm", callback=self.callback)
        self.assertTrue(alarm.nominal)
        prev_timestamp_severity_oldest = alarm.timestamp_severity_oldest
        prev_timestamp_severity_newest = alarm.timestamp_severity_newest
        prev_timestamp_max_severity = alarm.timestamp_max_severity
        prev_timestamp_acknowledged = alarm.timestamp_acknowledged

        reason = "this reason will be ignored"
        updated = alarm.set_severity(severity=AlarmSeverity.NONE, reason=reason)
        self.assertFalse(updated)
        self.assertEqual(alarm.severity, AlarmSeverity.NONE)
        self.assertEqual(alarm.max_severity, AlarmSeverity.NONE)
        self.assertEqual(alarm.reason, "")
        self.assertFalse(alarm.acknowledged)
        self.assertEqual(alarm.acknowledged_by, "")
        self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
        self.assertTrue(alarm.nominal)
        self.assertEqual(
            alarm.timestamp_severity_oldest, prev_timestamp_severity_oldest
        )
        self.assertEqual(
            alarm.timestamp_severity_newest, prev_timestamp_severity_newest
        )
        self.assertEqual(alarm.timestamp_max_severity, prev_timestamp_max_severity)
        self.assertEqual(alarm.timestamp_acknowledged, prev_timestamp_acknowledged)
        self.assertEqual(self.ncalls, 0)

    async def test_decreasing_severity(self):
        """Test that decreasing severity does not decrease max_severity."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = self.copy_alarm(alarm)
            for severity in reversed(list(AlarmSeverity)):
                if severity >= alarm.severity:
                    continue
                curr_tai = salobj.current_tai()
                reason = f"set to {severity}"
                updated = alarm.set_severity(severity=severity, reason=reason)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertEqual(alarm.severity, severity)
                self.assertEqual(alarm.max_severity, alarm0.max_severity)
                self.assertFalse(alarm.acknowledged)
                self.assertEqual(alarm.acknowledged_by, "")
                self.assertGreaterEqual(alarm.timestamp_severity_oldest, curr_tai)
                self.assertGreaterEqual(alarm.timestamp_severity_newest, curr_tai)
                self.assertEqual(
                    alarm.timestamp_max_severity, alarm0.timestamp_max_severity
                )
                self.assertEqual(
                    alarm.timestamp_acknowledged, alarm0.timestamp_acknowledged
                )
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertFalse(alarm.nominal)

        self.assertEqual(self.ncalls, desired_ncalls)

    async def test_increasing_severity(self):
        """Test that max_severity tracks increasing severity."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            for severity in AlarmSeverity:
                if severity <= alarm.max_severity:
                    continue
                curr_tai = salobj.current_tai()
                reason = f"set to {severity}"
                updated = alarm.set_severity(severity=severity, reason=reason)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertEqual(alarm.severity, severity)
                self.assertEqual(alarm.max_severity, severity)
                self.assertEqual(alarm.reason, reason)
                self.assertFalse(alarm.acknowledged)
                self.assertEqual(alarm.acknowledged_by, "")
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertFalse(alarm.nominal)
                self.assertGreaterEqual(alarm.timestamp_severity_oldest, curr_tai)
                self.assertGreaterEqual(alarm.timestamp_severity_newest, curr_tai)
                self.assertGreaterEqual(alarm.timestamp_max_severity, curr_tai)
                self.assertLess(alarm.timestamp_acknowledged, curr_tai)
        self.assertEqual(self.ncalls, desired_ncalls)

    async def test_repeating_severity(self):
        """Test setting the same severity multiple times."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = self.copy_alarm(alarm)

            curr_tai = salobj.current_tai()
            reason = f"set again to {alarm.severity}"
            self.assertNotEqual(alarm.reason, reason)
            updated = alarm.set_severity(severity=alarm.severity, reason=reason)
            if alarm0.nominal:
                self.assertFalse(updated)
                self.assertEqual(alarm, alarm0)
            else:
                self.assertTrue(updated)
                desired_ncalls += 1
                self.assertEqual(alarm.severity, alarm0.severity)
                self.assertEqual(alarm.max_severity, alarm0.max_severity)
                if alarm0.severity == AlarmSeverity.NONE:
                    self.assertEqual(alarm.reason, alarm0.reason)
                else:
                    self.assertEqual(alarm.reason, reason)
                self.assertFalse(alarm.acknowledged)
                self.assertEqual(alarm.acknowledged_by, "")
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertEqual(
                    alarm.timestamp_severity_oldest, alarm0.timestamp_severity_oldest
                )
                self.assertGreaterEqual(alarm.timestamp_severity_newest, curr_tai)
                self.assertEqual(
                    alarm.timestamp_max_severity, alarm0.timestamp_max_severity
                )
                self.assertEqual(
                    alarm.timestamp_acknowledged, alarm0.timestamp_acknowledged
                )

        self.assertEqual(self.ncalls, desired_ncalls)

    async def test_acknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        for auto_unacknowledge_delay in (0, 1):
            for alarm0 in self.alarm_iter(
                callback=self.callback,
                auto_unacknowledge_delay=auto_unacknowledge_delay,
            ):
                if alarm0.nominal:
                    continue
                for ack_severity in AlarmSeverity:
                    alarm = self.copy_alarm(alarm0)
                    self.assertEqual(
                        alarm.auto_unacknowledge_delay, auto_unacknowledge_delay
                    )
                    if alarm0.nominal:
                        # ack has no effect
                        updated = alarm.acknowledge(severity=ack_severity, user=user)
                        self.assertFalse(updated)
                        self.assertEqual(alarm, alarm0)
                    elif ack_severity < alarm.max_severity:
                        # ack severity too small
                        with self.assertRaises(ValueError):
                            alarm.acknowledge(severity=ack_severity, user=user)
                    else:
                        tai1 = salobj.current_tai()
                        updated = alarm.acknowledge(severity=ack_severity, user=user)
                        desired_ncalls += 1
                        self.assertTrue(updated)
                        self.assertEqual(alarm.severity, alarm0.severity)
                        self.assertTrue(alarm.acknowledged)
                        self.assertEqual(alarm.acknowledged_by, user)
                        self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
                        self.assertEqual(alarm.timestamp_escalate, 0)
                        if alarm0.severity == AlarmSeverity.NONE:
                            # alarm is reset to nominal
                            self.assertEqual(alarm.max_severity, AlarmSeverity.NONE)
                            self.assertTrue(alarm.nominal)
                        else:
                            # alarm is still active
                            self.assertEqual(alarm.max_severity, ack_severity)
                            self.assertFalse(alarm.nominal)
                        self.assertEqual(
                            alarm.timestamp_severity_oldest,
                            alarm0.timestamp_severity_oldest,
                        )
                        self.assertEqual(
                            alarm.timestamp_severity_newest,
                            alarm0.timestamp_severity_newest,
                        )
                        self.assertGreaterEqual(alarm.timestamp_max_severity, tai1)
                        self.assertGreaterEqual(alarm.timestamp_acknowledged, tai1)
                        await asyncio.sleep(0)

                        # Check task state; sleep first to let task cancellation
                        # happen.
                        self.assertTrue(alarm.auto_acknowledge_task.done())
                        self.assertTrue(alarm.escalate_task.done())
                        if (
                            auto_unacknowledge_delay == 0
                            or alarm.severity == AlarmSeverity.NONE
                        ):
                            self.assertTrue(alarm.auto_unacknowledge_task.done())
                        else:
                            self.assertFalse(alarm.auto_unacknowledge_task.done())
                        # Alarm was never muted.
                        self.assertTrue(alarm.unmute_task.done())

                        # Acknowledge again; this should have no affect
                        # except possibly restarting the unack timer.
                        restart_unack_timer = (
                            alarm.severity > AlarmSeverity.NONE
                            and alarm.auto_unacknowledge_delay > 0
                        )
                        acked_alarm = self.copy_alarm(alarm)
                        user2 = "a different user"
                        updated = alarm.acknowledge(severity=ack_severity, user=user2)
                        if restart_unack_timer:
                            self.assertTrue(updated)
                            alarm.assert_equal(
                                acked_alarm,
                                ignore_attrs=["timestamp_auto_unacknowledge"],
                            )
                            self.assertGreater(
                                alarm.timestamp_auto_unacknowledge,
                                acked_alarm.timestamp_auto_unacknowledge,
                            )
                        else:
                            self.assertFalse(updated)
                            alarm.assert_equal(acked_alarm)

            self.assertEqual(self.ncalls, desired_ncalls)

    async def test_unacknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # unacknowledge should have no effect initially
            # because alarm is not acknowledged
            alarm = self.copy_alarm(alarm0)
            updated = alarm.unacknowledge()
            self.assertFalse(updated)
            alarm.assert_equal(alarm0)

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = self.copy_alarm(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = alarm.acknowledge(severity=ack_severity, user=user)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertTrue(alarm.acknowledged)
                if alarm0.severity == AlarmSeverity.NONE:
                    self.assertTrue(alarm.nominal)
                else:
                    self.assertFalse(alarm.nominal)

                # unacknowledge the alarm
                acked_alarm = self.copy_alarm(alarm)
                tai0 = salobj.current_tai()
                updated = alarm.unacknowledge()
                if acked_alarm.nominal:
                    self.assertFalse(updated)
                    alarm.assert_equal(acked_alarm)
                else:
                    desired_ncalls += 1
                    self.assertTrue(updated)
                    self.assertFalse(alarm.nominal)
                    self.assertFalse(alarm.acknowledged)
                    self.assertGreaterEqual(alarm.timestamp_acknowledged, tai0)
                    self.assertEqual(
                        alarm.timestamp_severity_oldest,
                        acked_alarm.timestamp_severity_oldest,
                    )
                    self.assertEqual(
                        alarm.timestamp_severity_newest,
                        acked_alarm.timestamp_severity_newest,
                    )
                    self.assertEqual(
                        alarm.timestamp_max_severity, acked_alarm.timestamp_max_severity
                    )

        self.assertEqual(self.ncalls, desired_ncalls)

    async def test_escalate(self):
        escalate_delay = 0.1
        escalate_to = "chaos"

        for alarm in self.alarm_iter(
            name="user",
            callback=self.callback,
            escalate_delay=escalate_delay,
            escalate_to=escalate_to,
        ):
            self.assertFalse(alarm.escalated)
            self.assertEqual(alarm.escalate_delay, escalate_delay)
            self.assertEqual(alarm.escalate_to, escalate_to)
            if alarm.max_severity < AlarmSeverity.CRITICAL:
                self.assertEqual(alarm.timestamp_escalate, 0)
                self.assertTrue(alarm.escalate_task.done())
            else:
                self.assertGreater(alarm.timestamp_escalate, 0)
                self.assertFalse(alarm.escalate_task.done())
                await self.next_queued_alarm(expected_alarm=alarm)
                self.assertTrue(alarm.escalated)

    async def test_reset(self):
        name = "alarm"
        blank_alarm = self.make_alarm(name=name, callback=None)
        blank_alarm.callback = self.callback
        self.assertTrue(blank_alarm.nominal)
        for alarm in self.alarm_iter(name=name, callback=self.callback):
            if not alarm.nominal:
                self.assertNotEqual(alarm, blank_alarm)
            alarm.reset()
            alarm.assert_equal(blank_alarm)

    async def test_mute_valid(self):
        user = "otho"
        duration = 0.05
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            for alarm in self.alarm_iter(name=user, callback=self.callback):
                t0 = salobj.current_tai()
                alarm.mute(duration=duration, severity=severity, user=user)
                curr_tai = salobj.current_tai()
                dt = curr_tai - t0
                await self.next_queued_alarm(expected_alarm=alarm)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, user)
                self.assertEqual(alarm.muted_severity, severity)
                # Check that timestamp_unmute is close to and no less than
                # the current time + duration.
                self.assertGreaterEqual(curr_tai + duration, alarm.timestamp_unmute)
                self.assertAlmostEqual(
                    alarm.timestamp_unmute, curr_tai + duration, delta=dt
                )
                # Wait for the alrm to unmute itself.
                await self.next_queued_alarm(
                    expected_alarm=alarm, timeout=STD_TIMEOUT + duration
                )
                self.assertFalse(alarm.muted)
                self.assertEqual(alarm.muted_by, "")
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertEqual(alarm.timestamp_unmute, 0)

    async def test_mute_invalid(self):
        good_user = "otho"
        failed_user = "user associated with invalid mute command"
        good_delay = 5
        good_severity = AlarmSeverity.WARNING
        for alarm in self.alarm_iter(name=good_user, callback=None):
            for bad_delay, bad_severity in itertools.product(
                (0, -0.01), (AlarmSeverity.NONE, -53)
            ):
                # check that mute raises ValueError for invalid values
                # and leaves the alarm state unchanged
                initial_alarm = self.copy_alarm(alarm)
                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=bad_delay, severity=good_severity, user=failed_user
                    )
                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=good_delay, severity=bad_severity, user=failed_user
                    )
                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=bad_delay, severity=bad_severity, user=failed_user
                    )
                alarm.assert_equal(initial_alarm)

                # make sure failures also leave muted alarm state unchanged
                alarm.mute(duration=good_delay, severity=good_severity, user=good_user)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, good_user)
                self.assertEqual(alarm.muted_severity, good_severity)
                muted_alarm = self.copy_alarm(alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=bad_delay, severity=good_severity, user=failed_user
                    )
                alarm.assert_equal(muted_alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=good_delay, severity=bad_severity, user=failed_user
                    )
                alarm.assert_equal(muted_alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(
                        duration=bad_delay, severity=bad_severity, user=failed_user
                    )
                alarm.assert_equal(muted_alarm)

                alarm.unmute()  # kill unmute timer

    async def test_unmute(self):
        user = "otho"
        duration = 5
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            for alarm in self.alarm_iter(name=user, callback=self.callback):
                ncalls0 = self.ncalls
                # check that unmute on unmuted alarm is a no-op
                original_alarm = self.copy_alarm(alarm)
                alarm.unmute()
                alarm.assert_equal(original_alarm)
                self.assertEqual(self.ncalls, ncalls0 + 1)

                # mute alarm and unmute it again before it unmutes itself
                t0 = salobj.current_tai()
                alarm.mute(duration=duration, severity=severity, user=user)
                curr_tai = salobj.current_tai()
                dt = curr_tai - t0
                self.assertEqual(self.ncalls, ncalls0 + 2)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, user)
                self.assertEqual(alarm.muted_severity, severity)
                self.assertGreaterEqual(curr_tai + duration, alarm.timestamp_unmute)
                self.assertAlmostEqual(
                    alarm.timestamp_unmute, curr_tai + duration, delta=dt
                )

                alarm.unmute()
                self.assertEqual(self.ncalls, ncalls0 + 3)
                # Give asyncio a chance to cancel the mute task.
                await asyncio.sleep(0)
                self.assertTrue(alarm.unmute_task.done())
                # Compare equality.
                alarm.assert_equal(original_alarm)

    async def test_repr(self):
        name = "Something.else"
        alarm = self.make_alarm(name=name, callback=None)
        self.assertIn(name, repr(alarm))
        self.assertIn("Alarm", repr(alarm))

    async def test_set_severity_when_acknowledged(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = self.copy_alarm(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = alarm.acknowledge(severity=ack_severity, user=user)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertTrue(alarm.acknowledged)
                if alarm0.severity == AlarmSeverity.NONE:
                    self.assertTrue(alarm.nominal)
                else:
                    self.assertFalse(alarm.nominal)

                acked_alarm = alarm
                for severity in AlarmSeverity:
                    alarm = self.copy_alarm(acked_alarm)
                    tai0 = salobj.current_tai()
                    reason = f"set severity to {severity} after ack"
                    updated = alarm.set_severity(severity, reason=reason)
                    if updated:
                        desired_ncalls += 1
                        self.assertEqual(alarm.severity, severity)
                        if severity == acked_alarm.severity:
                            self.assertEqual(
                                alarm.timestamp_severity_oldest,
                                acked_alarm.timestamp_severity_oldest,
                            )
                        else:
                            self.assertGreaterEqual(
                                alarm.timestamp_severity_oldest, tai0
                            )
                        self.assertGreaterEqual(alarm.timestamp_severity_newest, tai0)
                    if severity == AlarmSeverity.NONE:
                        if acked_alarm.nominal:
                            self.assertFalse(updated)
                            alarm.assert_equal(acked_alarm)
                        else:
                            # alarm should be reset
                            self.assertTrue(updated)
                            self.assertEqual(alarm.max_severity, AlarmSeverity.NONE)
                            self.assertEqual(alarm.reason, "")
                            self.assertFalse(alarm.acknowledged)
                            self.assertGreaterEqual(alarm.timestamp_max_severity, tai0)
                            self.assertGreaterEqual(alarm.timestamp_acknowledged, tai0)
                    else:
                        self.assertTrue(updated)
                        self.assertEqual(alarm.reason, reason)
                        if severity > acked_alarm.max_severity:
                            # alarm should be unacknowledged
                            self.assertEqual(alarm.max_severity, severity)
                            self.assertFalse(alarm.acknowledged)
                            self.assertGreaterEqual(alarm.timestamp_max_severity, tai0)
                            self.assertGreaterEqual(alarm.timestamp_acknowledged, tai0)
                        else:
                            # alarm should remain acknowledged
                            self.assertEqual(
                                alarm.max_severity, acked_alarm.max_severity
                            )
                            self.assertTrue(alarm.acknowledged)
                            self.assertEqual(
                                alarm.timestamp_max_severity,
                                acked_alarm.timestamp_max_severity,
                            )
                            self.assertEqual(
                                alarm.timestamp_acknowledged,
                                acked_alarm.timestamp_acknowledged,
                            )

        self.assertEqual(self.ncalls, desired_ncalls)


if __name__ == "__main__":
    unittest.main()
