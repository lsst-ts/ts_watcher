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

import copy
import time
import unittest

from lsst.ts import salobj
from lsst.ts import watcher


class AlarmTestCase(unittest.TestCase):
    def setUp(self):
        self.ncalls = 0

    def callback(self, alarm):
        self.ncalls += 1

    def alarm_iter(self, name="test.alarm"):
        """Return an iterator over alarms with all allowed values of
        severity and max_severity.

        Parameters
        ----------
        name : `str`
            Name of alarm.

        Notes
        -----
        Does not affect self.ncalls.
        """
        def _alarm_iter_impl():
            # generate alarms without a callback
            severities = list(watcher.base.AlarmSeverity)
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
            alarm.callback = self.callback
            yield alarm

    def test_alarm_iter(self):
        name = "stella"
        severity_set = set()
        nitems = 0
        nseverities = len(watcher.base.AlarmSeverity)
        predicted_nitems = nseverities * (nseverities + 1) // 2
        for alarm in self.alarm_iter(name=name):
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
        properties = set(["nominal"])
        for fieldname in dir(alarm):
            if fieldname.startswith("__"):
                continue
            if fieldname in properties:
                continue
            value = getattr(alarm, fieldname)
            if fieldname != "callback" and callable(value):
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
        self.assertEqual(alarm.severity, watcher.base.AlarmSeverity.NONE)
        self.assertEqual(alarm.max_severity, watcher.base.AlarmSeverity.NONE)
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
        updated = alarm.set_severity(severity=watcher.base.AlarmSeverity.NONE, reason=reason)
        self.assertFalse(updated)
        self.assertEqual(alarm.severity, watcher.base.AlarmSeverity.NONE)
        self.assertEqual(alarm.max_severity, watcher.base.AlarmSeverity.NONE)
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
        for alarm in self.alarm_iter():
            alarm0 = copy.copy(alarm)
            for severity in reversed(list(watcher.base.AlarmSeverity)):
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
        for alarm in self.alarm_iter():
            for severity in watcher.base.AlarmSeverity:
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
        for alarm in self.alarm_iter():
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
                if alarm0.severity == watcher.base.AlarmSeverity.NONE:
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
        for alarm0 in self.alarm_iter():
            if alarm0.nominal:
                continue
            for ack_severity in watcher.base.AlarmSeverity:
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
                    if alarm0.severity == watcher.base.AlarmSeverity.NONE:
                        # alarm is reset to nominal
                        self.assertEqual(alarm.max_severity, watcher.base.AlarmSeverity.NONE)
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
        for alarm0 in self.alarm_iter():
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # unack should have no effect initially because alarm is not acked
            alarm = copy.copy(alarm0)
            updated = alarm.unacknowledge()
            self.assertFalse(updated)
            self.assertEqual(alarm, alarm0)

            # acknowledge the alarm
            for ack_severity in watcher.base.AlarmSeverity:
                alarm = copy.copy(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = alarm.acknowledge(severity=ack_severity, user=user)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertTrue(alarm.acknowledged)
                if alarm0.severity == watcher.base.AlarmSeverity.NONE:
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
        for alarm in self.alarm_iter(name=name):
            if not alarm.nominal:
                self.assertNotEqual(alarm, blank_alarm)
            alarm.reset()
            self.assertEqual(alarm, blank_alarm)

    def test_set_severity_when_acknowledged(self):
        user = "skipper"
        desired_ncalls = 0
        for alarm0 in self.alarm_iter():
            if alarm0.nominal:
                continue
            self.assertFalse(alarm0.acknowledged)

            # acknowledge the alarm
            for ack_severity in watcher.base.AlarmSeverity:
                alarm = copy.copy(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = alarm.acknowledge(severity=ack_severity, user=user)
                desired_ncalls += 1
                self.assertTrue(updated)
                self.assertTrue(alarm.acknowledged)
                if alarm0.severity == watcher.base.AlarmSeverity.NONE:
                    self.assertTrue(alarm.nominal)
                else:
                    self.assertFalse(alarm.nominal)

                acked_alarm = alarm
                for severity in watcher.base.AlarmSeverity:
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
                    if severity == watcher.base.AlarmSeverity.NONE:
                        if acked_alarm.nominal:
                            self.assertFalse(updated)
                            self.assertEqual(alarm, acked_alarm)
                        else:
                            # alarm should be reset
                            self.assertTrue(updated)
                            self.assertEqual(alarm.max_severity, watcher.base.AlarmSeverity.NONE)
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
