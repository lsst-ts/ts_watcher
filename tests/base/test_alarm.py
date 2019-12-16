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
import time
import unittest

import asynctest

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts import watcher


STD_TIMEOUT = 2  # seconds


class AsyncCallback:
    """Callback functor with a future that is set done when called."""
    def __init__(self):
        self._future = asyncio.Future()

    def __call__(self, alarm):
        if not self._future.done():
            self._future.set_result(alarm)

    async def next(self, timeout):
        await asyncio.wait_for(self._future, timeout=timeout)
        self._future = asyncio.Future()


class AlarmTestCase(asynctest.TestCase):
    def setUp(self):
        self.ncalls = 0

    def callback(self, alarm):
        self.ncalls += 1

    def alarm_iter(self, callback, name="test.alarm"):
        """Return an iterator over alarms with all allowed values of
        severity and max_severity.

        Parameters
        ----------
        callback : callable or `None`
            Callback function; must take one argument: an alarm.
            None for no callback function.
        name : `str`
            Name of alarm.

        Notes
        -----
        Does not affect self.ncalls.
        """
        def _alarm_iter_impl():
            # generate alarms without a callback
            severities = list(AlarmSeverity)
            alarm = watcher.base.Alarm(name=name, callback=None)
            yield alarm
            for i, severity in enumerate(severities[1:]):
                alarm = watcher.base.Alarm(name=name, callback=None)
                reason = f"alarm_iter set severity={severity}"
                updated = alarm.set_severity(severity=severity, reason=reason)
                self.assertTrue(updated)
                yield alarm

            for i, max_severity in enumerate(severities[1:]):
                for severity in severities[0:i+1]:
                    alarm = watcher.base.Alarm(name=name, callback=None)
                    updated = alarm.set_severity(severity=max_severity, reason=reason)
                    self.assertTrue(updated)
                    reason = f"alarm_iter set severity to {severity} after setting it to {max_severity}"
                    updated = alarm.set_severity(severity=severity, reason=reason)
                    self.assertTrue(updated)
                    yield alarm

        for alarm in _alarm_iter_impl():
            alarm.callback = callback
            yield alarm

    def test_alarm_iter(self):
        name = "stella"
        severity_set = set()
        nitems = 0
        nseverities = len(AlarmSeverity)
        predicted_nitems = nseverities * (nseverities + 1) // 2
        for alarm in self.alarm_iter(name=name, callback=self.callback):
            nitems += 1
            self.assertEqual(self.ncalls, 0)
            self.assertEqual(alarm.name, name)
            self.assertGreaterEqual(alarm.max_severity, alarm.severity)
            self.assertFalse(alarm.acknowledged)
            self.assertEqual(alarm.acknowledged_by, "")
            self.assertFalse(alarm.escalated)
            self.assertEqual(alarm.escalate_to, "")
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
            self.assertGreaterEqual(alarm.timestamp_severity_newest, alarm.timestamp_severity_oldest)
            self.assertEqual(alarm.timestamp_acknowledged, 0)
            self.assertEqual(alarm.timestamp_auto_acknowledge, 0)
            self.assertEqual(alarm.timestamp_auto_unacknowledge, 0)
            self.assertEqual(alarm.timestamp_escalate, 0)
            self.assertEqual(alarm.timestamp_unmute, 0)
            severity_set.add((alarm.severity, alarm.max_severity))
        self.assertEqual(nitems, predicted_nitems)
        self.assertEqual(nitems, len(severity_set))

    def test_equality(self):
        """Test __eq__ and __ne__

        This is a rather crude test in that it sets fields to
        invalid values.
        """
        alarm0 = watcher.base.Alarm(name="foo", callback=self.callback)
        alarm = copy.copy(alarm0)
        self.assertTrue(alarm == alarm0)
        self.assertFalse(alarm != alarm0)
        properties = set(["muted", "nominal"])
        for fieldname in dir(alarm):
            with self.subTest(fieldname=fieldname):
                if fieldname.startswith("__"):
                    continue
                if fieldname in properties:
                    continue
                value = getattr(alarm, fieldname)
                # ignore methods
                if fieldname != "callback" and callable(value):
                    continue
                # ignore tasks
                if fieldname.endswith("_task"):
                    continue
                alarm = copy.copy(alarm0)
                setattr(alarm, fieldname, 5)
                self.assertFalse(alarm == alarm0)
                self.assertTrue(alarm != alarm0)

    def test_constructor(self):
        name = "test_fairly_long_alarm_name"
        alarm = watcher.base.Alarm(name=name, callback=self.callback)
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

    def test_none_severity_when_nominal(self):
        """Test that set_severity to NONE has no effect if nominal."""
        alarm = watcher.base.Alarm(name="an_alarm", callback=self.callback)
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
        self.assertEqual(alarm.timestamp_severity_oldest, prev_timestamp_severity_oldest)
        self.assertEqual(alarm.timestamp_severity_newest, prev_timestamp_severity_newest)
        self.assertEqual(alarm.timestamp_max_severity, prev_timestamp_max_severity)
        self.assertEqual(alarm.timestamp_acknowledged, prev_timestamp_acknowledged)
        self.assertEqual(self.ncalls, 0)

    def test_decreasing_severity(self):
        """Test that decreasing severity does not decrease max_severity."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = copy.copy(alarm)
            for severity in reversed(list(AlarmSeverity)):
                if severity >= alarm.severity:
                    continue
                curr_tai = salobj.tai_from_utc(time.time())
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
                self.assertEqual(alarm.timestamp_max_severity, alarm0.timestamp_max_severity)
                self.assertEqual(alarm.timestamp_acknowledged, alarm0.timestamp_acknowledged)
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertFalse(alarm.nominal)

        self.assertEqual(self.ncalls, desired_ncalls)

    def test_increasing_severity(self):
        """Test that max_severity tracks increasing severity."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            for severity in AlarmSeverity:
                if severity <= alarm.max_severity:
                    continue
                curr_tai = salobj.tai_from_utc(time.time())
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

    def test_repeating_severity(self):
        """Test setting the same severity multiple times."""
        desired_ncalls = 0
        for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = copy.copy(alarm)

            curr_tai = salobj.tai_from_utc(time.time())
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
                self.assertEqual(alarm.timestamp_severity_oldest, alarm0.timestamp_severity_oldest)
                self.assertGreaterEqual(alarm.timestamp_severity_newest, curr_tai)
                self.assertEqual(alarm.timestamp_max_severity, alarm0.timestamp_max_severity)
                self.assertEqual(alarm.timestamp_acknowledged, alarm0.timestamp_acknowledged)

        self.assertEqual(self.ncalls, desired_ncalls)

    def test_acknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            for ack_severity in AlarmSeverity:
                alarm = copy.copy(alarm0)
                if alarm0.nominal:
                    # ack has no effect
                    updated = alarm.acknowledge(severity=ack_severity, user=user)
                    self.assertFalse(updated)
                    self.assertEqual(alarm, alarm0)
                elif ack_severity < alarm.max_severity:
                    # ack severity too small
                    with self.assertRaises(ValueError):
                        alarm.acknowledge(severity=ack_severity, user=user)
                    self.assertEqual(alarm, alarm0)
                else:
                    tai1 = salobj.tai_from_utc(time.time())
                    updated = alarm.acknowledge(severity=ack_severity, user=user)
                    desired_ncalls += 1
                    self.assertTrue(updated)
                    self.assertEqual(alarm.severity, alarm0.severity)
                    self.assertTrue(alarm.acknowledged)
                    self.assertEqual(alarm.acknowledged_by, user)
                    if alarm0.severity == AlarmSeverity.NONE:
                        # alarm is reset to nominal
                        self.assertEqual(alarm.max_severity, AlarmSeverity.NONE)
                        self.assertTrue(alarm.nominal)
                    else:
                        # alarm is still active
                        self.assertEqual(alarm.max_severity, ack_severity)
                        self.assertFalse(alarm.nominal)
                    self.assertEqual(alarm.timestamp_severity_oldest, alarm0.timestamp_severity_oldest)
                    self.assertEqual(alarm.timestamp_severity_newest, alarm0.timestamp_severity_newest)
                    self.assertGreaterEqual(alarm.timestamp_max_severity, tai1)
                    self.assertGreaterEqual(alarm.timestamp_acknowledged, tai1)

                    # acknowledge again; this should have no affect
                    acked_alarm = copy.copy(alarm)
                    user2 = "a different user"
                    updated = alarm.acknowledge(severity=ack_severity, user=user2)
                    self.assertFalse(updated)
                    self.assertEqual(alarm, acked_alarm)

        self.assertEqual(self.ncalls, desired_ncalls)

    def test_unacknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # unack should have no effect initially because alarm is not acked
            alarm = copy.copy(alarm0)
            updated = alarm.unacknowledge()
            self.assertFalse(updated)
            self.assertEqual(alarm, alarm0)

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = copy.copy(alarm0)
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
                acked_alarm = copy.copy(alarm)
                tai0 = salobj.tai_from_utc(time.time())
                updated = alarm.unacknowledge()
                if acked_alarm.nominal:
                    self.assertFalse(updated)
                    self.assertEqual(alarm, acked_alarm)
                else:
                    desired_ncalls += 1
                    self.assertTrue(updated)
                    self.assertFalse(alarm.nominal)
                    self.assertFalse(alarm.acknowledged)
                    self.assertGreaterEqual(alarm.timestamp_acknowledged, tai0)
                    self.assertEqual(alarm.timestamp_severity_oldest, acked_alarm.timestamp_severity_oldest)
                    self.assertEqual(alarm.timestamp_severity_newest, acked_alarm.timestamp_severity_newest)
                    self.assertEqual(alarm.timestamp_max_severity, acked_alarm.timestamp_max_severity)

        self.assertEqual(self.ncalls, desired_ncalls)

    def test_reset(self):
        name = "alarm"
        blank_alarm = watcher.base.Alarm(name=name, callback=None)
        blank_alarm.callback = self.callback
        for alarm in self.alarm_iter(name=name, callback=self.callback):
            if not alarm.nominal:
                self.assertNotEqual(alarm, blank_alarm)
            alarm.reset()
            self.assertEqual(alarm, blank_alarm)

    async def test_mute_valid(self):
        user = "otho"
        timespan = 0.05
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            callback = AsyncCallback()
            for alarm in self.alarm_iter(name=user, callback=callback):
                alarm.mute(timespan=timespan, severity=severity, user=user)
                curr_tai = salobj.tai_from_utc(time.time())
                await callback.next(timeout=STD_TIMEOUT)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, user)
                self.assertEqual(alarm.muted_severity, severity)
                # Check that timestamp_unmute is close to and no less than
                # the current time + timespan.
                self.assertGreaterEqual(curr_tai + timespan, alarm.timestamp_unmute)
                self.assertAlmostEqual(alarm.timestamp_unmute, curr_tai + timespan, places=2)
                # Wait for the alrm to unmute itself.
                await callback.next(timeout=STD_TIMEOUT + timespan)
                self.assertFalse(alarm.muted)
                self.assertEqual(alarm.muted_by, "")
                self.assertEqual(alarm.muted_severity, AlarmSeverity.NONE)
                self.assertEqual(alarm.timestamp_unmute, 0)

    async def test_mute_invalid(self):
        good_user = "otho"
        failed_user = "user associated with invalid mute command"
        good_timespan = 5
        good_severity = AlarmSeverity.WARNING
        for alarm in self.alarm_iter(name=good_user, callback=None):
            for bad_timespan, bad_severity in itertools.product((0, -0.01), (AlarmSeverity.NONE, -53)):
                # check that mute raises ValueError for invalid values
                # and leaves the alarm state unchanged
                initial_alarm = copy.copy(alarm)
                with self.assertRaises(ValueError):
                    alarm.mute(timespan=bad_timespan, severity=good_severity, user=failed_user)
                with self.assertRaises(ValueError):
                    alarm.mute(timespan=good_timespan, severity=bad_severity, user=failed_user)
                with self.assertRaises(ValueError):
                    alarm.mute(timespan=bad_timespan, severity=bad_severity, user=failed_user)
                self.assertEqual(alarm, initial_alarm)

                # make sure failures also leave muted alarm state unchanged
                alarm.mute(timespan=good_timespan, severity=good_severity, user=good_user)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, good_user)
                self.assertEqual(alarm.muted_severity, good_severity)
                muted_alarm = copy.copy(alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(timespan=bad_timespan, severity=good_severity, user=failed_user)
                self.assertEqual(alarm, muted_alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(timespan=good_timespan, severity=bad_severity, user=failed_user)
                self.assertEqual(alarm, muted_alarm)

                with self.assertRaises(ValueError):
                    alarm.mute(timespan=bad_timespan, severity=bad_severity, user=failed_user)
                self.assertEqual(alarm, muted_alarm)

                alarm.unmute()  # kill unmute timer

    async def test_unmute(self):
        user = "otho"
        timespan = 5
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            for alarm in self.alarm_iter(name=user, callback=self.callback):
                self.ncalls = 0
                # check that unmute on unmuted alarm is a no-op
                original_alarm = copy.copy(alarm)
                alarm.unmute()
                self.assertEqual(alarm, original_alarm)
                self.assertEqual(self.ncalls, 1)

                # mute alarm and unmute it again before it unmutes itself
                alarm.mute(timespan=timespan, severity=severity, user=user)
                curr_tai = salobj.tai_from_utc(time.time())
                self.assertEqual(self.ncalls, 2)
                self.assertTrue(alarm.muted)
                self.assertEqual(alarm.muted_by, user)
                self.assertEqual(alarm.muted_severity, severity)
                self.assertGreaterEqual(curr_tai + timespan, alarm.timestamp_unmute)
                self.assertAlmostEqual(alarm.timestamp_unmute, curr_tai + timespan, places=2)

                alarm.unmute()
                self.assertEqual(self.ncalls, 3)
                # give asyncio a chance to cancel the mute task
                await asyncio.sleep(0)
                self.assertTrue(alarm.unmute_task.done())
                self.assertEqual(alarm, original_alarm)

    def test_repr(self):
        name = "Something.else"
        alarm = watcher.base.Alarm(name=name, callback=None)
        self.assertIn(name, repr(alarm))
        self.assertIn("Alarm", repr(alarm))

    def test_set_severity_when_acknowledged(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = copy.copy(alarm0)
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
                    alarm = copy.copy(acked_alarm)
                    tai0 = salobj.tai_from_utc(time.time())
                    reason = f"set severity to {severity} after ack"
                    updated = alarm.set_severity(severity, reason=reason)
                    if updated:
                        desired_ncalls += 1
                        self.assertEqual(alarm.severity, severity)
                        if severity == acked_alarm.severity:
                            self.assertEqual(alarm.timestamp_severity_oldest,
                                             acked_alarm.timestamp_severity_oldest)
                        else:
                            self.assertGreaterEqual(alarm.timestamp_severity_oldest, tai0)
                        self.assertGreaterEqual(alarm.timestamp_severity_newest, tai0)
                    if severity == AlarmSeverity.NONE:
                        if acked_alarm.nominal:
                            self.assertFalse(updated)
                            self.assertEqual(alarm, acked_alarm)
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
                            self.assertEqual(alarm.max_severity, acked_alarm.max_severity)
                            self.assertTrue(alarm.acknowledged)
                            self.assertEqual(alarm.timestamp_max_severity,
                                             acked_alarm.timestamp_max_severity)
                            self.assertEqual(alarm.timestamp_acknowledged,
                                             acked_alarm.timestamp_acknowledged)

        self.assertEqual(self.ncalls, desired_ncalls)


if __name__ == "__main__":
    unittest.main()
