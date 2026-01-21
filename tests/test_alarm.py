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

import asyncio
import copy
import itertools
import unittest

import pytest

from lsst.ts import utils, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

STD_TIMEOUT = 2  # seconds


class AlarmTestCase(unittest.IsolatedAsyncioTestCase):
    # NOTE: almost all test methods must be async, even with no visible
    # async code, so that Alarm has an event loop.
    def setUp(self):
        self.callback_queue = asyncio.Queue()
        self._alarms = []  # Alarms to close in tearDown.

    def tearDown(self):
        for alarm in self._alarms:
            alarm.close()

    async def callback(self, alarm):
        self.callback_queue.put_nowait(alarm)

    async def next_queued_alarm(self, expected_alarm=None, timeout=STD_TIMEOUT):
        """Get the next alarm queued by `callback`.

        Parameters
        ----------
        expected_alarm : `lsst.ts.watcher.Alarm` or `None`, optional
            The alarm that should be returned.
            If None (the default) then this is not checked.
        timeout : `float`
            Time limit for waiting (seconds).
        """
        alarm = await asyncio.wait_for(self.callback_queue.get(), timeout=STD_TIMEOUT)
        if expected_alarm is not None:
            assert alarm is expected_alarm
        return alarm

    @property
    def ncalls(self):
        return self.callback_queue.qsize()

    async def alarm_iter(
        self,
        callback,
        name="test.alarm",
        auto_acknowledge_delay=0,
        auto_unacknowledge_delay=0,
        escalation_responder="",
        escalation_delay=0,
    ):
        """An iterator over alarms with all allowed values of
        severity and max_severity.

        All of the returned alarms have a severity queue,
        so you can call alarm.assert_next_severity.

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
        escalation_delay : `float`, optional
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 (the default) the alarm is not escalated.
        escalation_responder : `str`
            Who or what to escalate the alarm to.
            If blank, the alarm will not be escalated.

        Notes
        -----
        The callback function is not called by this iterator,
        so this iterator does not change `self.ncalls`.
        """

        async def _alarm_iter_impl():
            """An iterator over alarms with all allowed values of
            severity and max_severity and no callback function.

            Assign the callback later, if desired.
            """
            alarm_kwargs = dict(
                name=name,
                auto_acknowledge_delay=auto_acknowledge_delay,
                auto_unacknowledge_delay=auto_unacknowledge_delay,
                escalation_responder=escalation_responder,
                escalation_delay=escalation_delay,
            )

            severities = list(AlarmSeverity)
            alarm = self.make_alarm(**alarm_kwargs)
            alarm.init_severity_queue()
            yield alarm
            for i, severity in enumerate(severities[1:]):
                alarm = self.make_alarm(**alarm_kwargs)
                alarm.init_severity_queue()
                reason = f"alarm_iter set severity={severity}"
                updated = await alarm.set_severity(severity=severity, reason=reason)
                await asyncio.wait_for(alarm.assert_next_severity(severity), timeout=STD_TIMEOUT)
                assert updated
                yield alarm

            for i, max_severity in enumerate(severities[1:]):
                for severity in severities[0 : i + 1]:
                    alarm = self.make_alarm(**alarm_kwargs)
                    alarm.init_severity_queue()
                    updated = await alarm.set_severity(severity=max_severity, reason=reason)
                    await asyncio.wait_for(alarm.assert_next_severity(max_severity), timeout=STD_TIMEOUT)
                    assert updated
                    reason = f"alarm_iter set severity to {severity} after setting it to {max_severity}"
                    updated = await alarm.set_severity(severity=severity, reason=reason)
                    await asyncio.wait_for(alarm.assert_next_severity(severity), timeout=STD_TIMEOUT)
                    assert updated
                    yield alarm

        async for alarm in _alarm_iter_impl():
            alarm.callback = callback
            yield alarm

    def copy_alarm(self, alarm):
        """Return a shallow copy of an alarm and schedule it to be closed.

        Parameters
        ----------
        alarm : `lsst.ts.watcher.Alarm`
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
        escalation_responder="",
        escalation_delay=0,
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
        escalation_delay : `float`, optional
            Delay before escalating a critical unacknowledged alarm (sec).
            If 0 (the default) the alarm is not escalated.
        escalation_responder : `str`
            Who or what to escalate the alarm to.
            If blank, the alarm will not be escalated.
        """
        alarm = watcher.Alarm(name=name)
        alarm.configure_basics(
            callback=callback,
            auto_acknowledge_delay=auto_acknowledge_delay,
            auto_unacknowledge_delay=auto_unacknowledge_delay,
        )
        alarm.configure_escalation(
            escalation_responder=escalation_responder,
            escalation_delay=escalation_delay,
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
        assert alarm.nominal
        assert alarm.auto_acknowledge_delay == auto_acknowledge_delay
        assert alarm.timestamp_auto_acknowledge == 0
        assert alarm.auto_acknowledge_task.done()

        await alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        assert alarm.nominal
        assert alarm.timestamp_auto_acknowledge == 0
        assert alarm.auto_acknowledge_task.done()

        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        assert not alarm.nominal
        assert alarm.timestamp_auto_acknowledge == 0
        assert alarm.auto_acknowledge_task.done()

        # Now set severity None, making the alarm stale
        t0 = utils.current_tai()
        await alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        # Give the auto acknowledgement task time to start
        curr_tai = utils.current_tai()
        dt = curr_tai - t0
        predicted_auto_ack_tai = curr_tai + auto_acknowledge_delay
        assert not alarm.nominal
        assert alarm.timestamp_auto_acknowledge == pytest.approx(predicted_auto_ack_tai, abs=dt)
        await asyncio.sleep(0)
        assert not alarm.auto_acknowledge_task.done()

        # Wait less than auto_acknowledge_delay and check that
        # the alarm has not yet been automatically acknowledged
        await asyncio.sleep(auto_acknowledge_delay / 2)
        assert alarm.max_severity == AlarmSeverity.WARNING
        assert not alarm.acknowledged
        assert not alarm.nominal

        # Set alarm severity > NONE and check that the automatic
        # acknowledgement task has been canceled.
        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        assert not alarm.nominal
        assert alarm.timestamp_auto_acknowledge == 0
        await asyncio.sleep(0)
        assert alarm.auto_acknowledge_task.done()

        # Make the alarm stale again and wait for automatic acknowledgement
        await alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        assert not alarm.nominal
        await asyncio.sleep(0)
        assert not alarm.auto_acknowledge_task.done()

        # Wait the rest of the needed time and check that the alarm
        # has been automatically acknowledged.
        await asyncio.sleep(auto_acknowledge_delay + 0.001)
        assert alarm.nominal
        assert alarm.acknowledged_by == "automatic"

    async def test_auto_unacknowledge(self):
        user = "chaos"
        auto_unacknowledge_delay = 0.5
        # The timer should not start until the alarm is stale.
        alarm = self.make_alarm(
            name="test",
            callback=self.callback,
            auto_unacknowledge_delay=auto_unacknowledge_delay,
        )
        assert alarm.nominal
        assert alarm.auto_unacknowledge_delay == auto_unacknowledge_delay
        assert alarm.timestamp_auto_unacknowledge == 0
        assert alarm.auto_unacknowledge_task.done()

        # Make an alarm condition and check that the auto-unack task
        # is not running yet.
        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        assert not alarm.acknowledged
        assert alarm.timestamp_auto_unacknowledge == 0
        await asyncio.sleep(0)
        assert alarm.auto_unacknowledge_task.done()

        # Acknowledge the alarm; the auto-unack task should now be running
        t0 = utils.current_tai()
        await alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        curr_tai = utils.current_tai()
        dt = curr_tai - t0
        predicted_auto_unack_tai = curr_tai + auto_unacknowledge_delay
        assert alarm.timestamp_auto_unacknowledge == pytest.approx(predicted_auto_unack_tai, abs=dt)
        assert alarm.acknowledged
        await asyncio.sleep(0)
        assert not alarm.auto_unacknowledge_task.done()

        # Wait less time than auto unack and manually unack the alarm;
        # this should cancel the auto unack task.
        await asyncio.sleep(auto_unacknowledge_delay / 2)
        assert alarm.acknowledged
        await alarm.unacknowledge()
        assert not alarm.acknowledged
        assert alarm.timestamp_auto_unacknowledge == 0
        await asyncio.sleep(0)
        assert alarm.auto_unacknowledge_task.done()

        # Acknowledge the alarm again
        await alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        assert alarm.acknowledged
        assert alarm.timestamp_auto_unacknowledge > 0
        await asyncio.sleep(0)
        assert not alarm.auto_unacknowledge_task.done()

        # Wait less time than auto unack and set severity NONE;
        # this should make the alarm nominal and cancel the auto unack
        await asyncio.sleep(auto_unacknowledge_delay / 2)
        await alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        assert alarm.nominal
        assert alarm.timestamp_auto_unacknowledge == 0
        await asyncio.sleep(0)
        assert alarm.auto_unacknowledge_task.done()

        # Set severity > NONE again, acknowledge,
        # and wait the full time for auto unack
        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="test")
        await alarm.acknowledge(severity=AlarmSeverity.WARNING, user=user)
        assert alarm.acknowledged
        assert alarm.timestamp_auto_unacknowledge > 0
        await asyncio.sleep(0)
        assert not alarm.auto_unacknowledge_task.done()

        await asyncio.sleep(auto_unacknowledge_delay + 0.001)
        assert not alarm.acknowledged
        assert alarm.auto_unacknowledge_task.done()

    async def test_noauto_acknowledge(self):
        # Set auto_acknowledge_delay = 0 to prevent automatic acknowledgement
        alarm = self.make_alarm(name="test", callback=self.callback, auto_acknowledge_delay=0)
        assert alarm.nominal
        assert alarm.auto_acknowledge_delay == 0
        assert alarm.timestamp_auto_acknowledge == 0
        assert alarm.auto_acknowledge_task.done()

        # Make alarm stale by setting severity > NONE then to NONE
        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="why not?")
        await alarm.set_severity(severity=AlarmSeverity.NONE, reason="")
        assert not alarm.nominal
        assert not alarm.acknowledged

        # Verify that auto acknowledgement is not running.
        assert alarm.timestamp_auto_acknowledge == 0
        assert alarm.auto_acknowledge_task.done()

    async def test_noauto_unacknowledge(self):
        # Set auto_unacknowledge_delay = 0 to prevent automatic unack
        alarm = self.make_alarm(name="test", callback=self.callback, auto_unacknowledge_delay=0)
        assert alarm.nominal
        assert alarm.auto_unacknowledge_delay == 0
        assert alarm.timestamp_auto_unacknowledge == 0
        assert alarm.auto_unacknowledge_task.done()

        # Make an acknowledged alarm.
        await alarm.set_severity(severity=AlarmSeverity.WARNING, reason="why not?")
        await alarm.acknowledge(severity=alarm.severity, user="chaos")
        assert not alarm.nominal
        assert alarm.acknowledged

        # Verify that auto unacknowledgement is not running.
        assert alarm.timestamp_auto_unacknowledge == 0
        assert alarm.auto_unacknowledge_task.done()

    async def test_alarm_iter(self):
        nseverities = len(AlarmSeverity)

        # Default arguments to self.alarm_iter
        default_kwargs = dict(
            name="test.alarm",
            auto_acknowledge_delay=0,
            auto_unacknowledge_delay=0,
            escalation_responder="",
            escalation_delay=0,
        )
        for callback, kwargs in itertools.product(
            (None, self.callback),
            (
                dict(),
                dict(name="foo"),
                dict(auto_acknowledge_delay=1),
                dict(auto_unacknowledge_delay=2),
                # Set both escalation_responder and escalation_delay
                # to enable escalation.
                dict(
                    escalation_responder="chaos",
                    escalation_delay=3,
                ),
            ),
        ):

            def assert_expected(alarm):
                """Assert that all alarm fields that can be specified
                when calling `alarm_iter` have the expected value.
                """
                for argname, default_value in default_kwargs.items():
                    expected_value = kwargs.get(argname, default_value)
                    assert getattr(alarm, argname) == expected_value

            severity_set = set()
            nitems = 0
            predicted_nitems = nseverities * (nseverities + 1) // 2
            async for alarm in self.alarm_iter(callback=callback, **kwargs):
                nitems += 1
                assert self.ncalls == 0
                assert alarm.callback == callback
                assert_expected(alarm)

                assert alarm.max_severity >= alarm.severity
                assert not alarm.acknowledged
                assert alarm.acknowledged_by == ""
                assert not alarm.do_escalate
                assert alarm.muted_severity == AlarmSeverity.NONE
                assert alarm.muted_by == ""
                if nitems == 1:
                    # first state is NONE, alarm is nominal
                    assert alarm.nominal
                    assert alarm.timestamp_severity_oldest == 0
                    assert alarm.timestamp_severity_newest == 0
                    assert alarm.timestamp_max_severity == 0
                else:
                    assert not alarm.nominal
                    assert alarm.timestamp_severity_oldest > 0
                    assert alarm.timestamp_severity_newest > 0
                    assert alarm.timestamp_max_severity > 0

                assert alarm.timestamp_acknowledged == 0
                assert alarm.timestamp_auto_unacknowledge == 0

                stale_alarm = alarm.severity == AlarmSeverity.NONE and alarm.max_severity > AlarmSeverity.NONE
                if stale_alarm and alarm.auto_acknowledge_delay > 0:
                    assert alarm.timestamp_auto_acknowledge > 0
                else:
                    assert alarm.timestamp_auto_acknowledge == 0
                assert alarm.timestamp_severity_newest >= alarm.timestamp_severity_oldest

                auto_escalate = (
                    alarm.max_severity == AlarmSeverity.CRITICAL
                    and alarm.escalation_delay > 0
                    and alarm.escalation_responder
                )
                if auto_escalate and alarm.severity == AlarmSeverity.CRITICAL:
                    assert alarm.timestamp_escalate > 0
                else:
                    assert alarm.timestamp_escalate == 0
                assert alarm.timestamp_unmute == 0
                severity_set.add((alarm.severity, alarm.max_severity))
            assert nitems == predicted_nitems
            assert nitems == len(severity_set)

    async def test_equality(self):
        """Test __eq__ and __ne__

        This is a rather crude test in that it sets fields to
        invalid values.
        """
        alarm0 = self.make_alarm(name="foo", callback=self.callback)
        alarm = self.copy_alarm(alarm0)
        assert alarm == alarm0
        assert not alarm != alarm0
        alarm.assert_equal(alarm0)
        for fieldname, value in vars(alarm).items():
            if fieldname.endswith("_task"):
                continue
            if fieldname == "severity_queue":
                continue
            with self.subTest(fieldname=fieldname):
                alarm = self.copy_alarm(alarm0)
                setattr(alarm, fieldname, 5)
                assert not alarm == alarm0
                assert alarm != alarm0
                alarm.assert_equal(alarm0, ignore_attrs=[fieldname])

    async def test_constructor(self):
        name = "test_fairly_long_alarm_name"
        alarm = self.make_alarm(name=name, callback=self.callback)
        assert alarm.name == name
        assert alarm.callback == self.callback
        assert alarm.nominal
        assert not alarm.acknowledged
        assert alarm.severity == AlarmSeverity.NONE
        assert alarm.max_severity == AlarmSeverity.NONE
        assert alarm.reason == ""
        assert alarm.acknowledged_by == ""
        assert alarm.muted_severity == AlarmSeverity.NONE
        assert alarm.nominal

        # Specifying a non-coroutine (synchronous function) as a callback
        # should raise TypeError
        def bad_callback():
            pass

        with pytest.raises(TypeError):
            alarm.callback = bad_callback

    async def test_config_errors(self):
        alarm = self.make_alarm(name="test")
        with pytest.raises(ValueError):
            alarm.configure_basics(auto_acknowledge_delay=-0.001)
        with pytest.raises(ValueError):
            alarm.configure_basics(auto_unacknowledge_delay=-0.001)

    async def test_none_severity_when_nominal(self):
        """Test that set_severity to NONE has no effect if nominal."""
        alarm = self.make_alarm(name="an_alarm", callback=self.callback)
        assert alarm.nominal
        prev_timestamp_severity_oldest = alarm.timestamp_severity_oldest
        prev_timestamp_severity_newest = alarm.timestamp_severity_newest
        prev_timestamp_max_severity = alarm.timestamp_max_severity
        prev_timestamp_acknowledged = alarm.timestamp_acknowledged

        reason = "this reason will be ignored"
        updated = await alarm.set_severity(severity=AlarmSeverity.NONE, reason=reason)
        assert not updated
        assert alarm.severity == AlarmSeverity.NONE
        assert alarm.max_severity == AlarmSeverity.NONE
        assert alarm.reason == ""
        assert not alarm.acknowledged
        assert alarm.acknowledged_by == ""
        assert alarm.muted_severity == AlarmSeverity.NONE
        assert alarm.nominal
        assert alarm.timestamp_severity_oldest == prev_timestamp_severity_oldest
        assert alarm.timestamp_severity_newest == prev_timestamp_severity_newest
        assert alarm.timestamp_max_severity == prev_timestamp_max_severity
        assert alarm.timestamp_acknowledged == prev_timestamp_acknowledged
        assert self.ncalls == 0

    async def test_decreasing_severity(self):
        """Test that decreasing severity does not decrease max_severity."""
        desired_ncalls = 0
        async for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = self.copy_alarm(alarm)
            for severity in reversed(list(AlarmSeverity)):
                if severity >= alarm.severity:
                    continue
                curr_tai = utils.current_tai()
                reason = f"set to {severity}"
                updated = await alarm.set_severity(severity=severity, reason=reason)
                await asyncio.wait_for(alarm.assert_next_severity(severity), timeout=STD_TIMEOUT)
                assert updated
                desired_ncalls += 1
                assert alarm.severity == severity
                assert alarm.max_severity == alarm0.max_severity
                assert not alarm.acknowledged
                assert alarm.acknowledged_by == ""
                assert alarm.timestamp_severity_oldest >= curr_tai
                assert alarm.timestamp_severity_newest >= curr_tai
                assert alarm.timestamp_max_severity == alarm0.timestamp_max_severity
                assert alarm.timestamp_acknowledged == alarm0.timestamp_acknowledged
                assert alarm.muted_severity == AlarmSeverity.NONE
                assert not alarm.nominal

        assert self.ncalls == desired_ncalls

    async def test_increasing_severity(self):
        """Test that max_severity tracks increasing severity."""
        desired_ncalls = 0
        async for alarm in self.alarm_iter(callback=self.callback):
            for severity in AlarmSeverity:
                if severity <= alarm.max_severity:
                    continue
                curr_tai = utils.current_tai()
                reason = f"set to {severity}"
                updated = await alarm.set_severity(severity=severity, reason=reason)
                await asyncio.wait_for(alarm.assert_next_severity(severity), timeout=STD_TIMEOUT)
                assert updated
                desired_ncalls += 1
                assert alarm.severity == severity
                assert alarm.max_severity == severity
                assert alarm.reason == reason
                assert not alarm.acknowledged
                assert alarm.acknowledged_by == ""
                assert alarm.muted_severity == AlarmSeverity.NONE
                assert not alarm.nominal
                assert alarm.timestamp_severity_oldest >= curr_tai
                assert alarm.timestamp_severity_newest >= curr_tai
                assert alarm.timestamp_max_severity >= curr_tai
                assert alarm.timestamp_acknowledged < curr_tai
        assert self.ncalls == desired_ncalls

    async def test_repeating_severity(self):
        """Test setting the same severity multiple times."""
        desired_ncalls = 0
        async for alarm in self.alarm_iter(callback=self.callback):
            alarm0 = self.copy_alarm(alarm)

            curr_tai = utils.current_tai()
            reason = f"set again to {alarm.severity}"
            assert alarm.reason != reason
            severity = alarm.severity
            updated = await alarm.set_severity(severity=severity, reason=reason)
            await asyncio.wait_for(alarm.assert_next_severity(severity), timeout=STD_TIMEOUT)
            if alarm0.nominal:
                assert not updated
                assert alarm == alarm0
            else:
                assert updated
                desired_ncalls += 1
                assert alarm.severity == alarm0.severity
                assert alarm.max_severity == alarm0.max_severity
                if alarm0.severity == AlarmSeverity.NONE:
                    assert alarm.reason == alarm0.reason
                else:
                    assert alarm.reason == reason
                assert not alarm.acknowledged
                assert alarm.acknowledged_by == ""
                assert alarm.muted_severity == AlarmSeverity.NONE
                assert alarm.timestamp_severity_oldest == alarm0.timestamp_severity_oldest
                assert alarm.timestamp_severity_newest >= curr_tai
                assert alarm.timestamp_max_severity == alarm0.timestamp_max_severity
                assert alarm.timestamp_acknowledged == alarm0.timestamp_acknowledged

        assert self.ncalls == desired_ncalls

    async def test_acknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        for auto_unacknowledge_delay in (0, 1):
            async for alarm0 in self.alarm_iter(
                callback=self.callback,
                auto_unacknowledge_delay=auto_unacknowledge_delay,
            ):
                if alarm0.nominal:
                    continue
                for ack_severity in AlarmSeverity:
                    alarm = self.copy_alarm(alarm0)
                    assert alarm.auto_unacknowledge_delay == auto_unacknowledge_delay
                    if alarm0.nominal:
                        # ack has no effect
                        updated = await alarm.acknowledge(severity=ack_severity, user=user)
                        assert not updated
                        assert alarm == alarm0
                    elif ack_severity < alarm.max_severity:
                        # ack severity too small
                        with pytest.raises(ValueError):
                            await alarm.acknowledge(severity=ack_severity, user=user)
                    else:
                        tai1 = utils.current_tai()
                        updated = await alarm.acknowledge(severity=ack_severity, user=user)
                        assert updated
                        desired_ncalls += 1
                        assert alarm.severity == alarm0.severity
                        assert alarm.acknowledged
                        assert alarm.acknowledged_by == user
                        assert alarm.timestamp_auto_acknowledge == 0
                        assert alarm.timestamp_escalate == 0
                        if alarm0.severity == AlarmSeverity.NONE:
                            # alarm is reset to nominal
                            assert alarm.max_severity == AlarmSeverity.NONE
                            assert alarm.nominal
                        else:
                            # alarm is still active
                            assert alarm.max_severity == ack_severity
                            assert not alarm.nominal
                        assert alarm.timestamp_severity_oldest == alarm0.timestamp_severity_oldest
                        assert alarm.timestamp_severity_newest == alarm0.timestamp_severity_newest
                        assert alarm.timestamp_max_severity >= tai1
                        assert alarm.timestamp_acknowledged >= tai1
                        await asyncio.sleep(0)

                        # Check task state; sleep first
                        # to let task cancellation happen.
                        assert alarm.auto_acknowledge_task.done()
                        assert alarm.escalation_timer_task.done()
                        if auto_unacknowledge_delay == 0 or alarm.severity == AlarmSeverity.NONE:
                            assert alarm.auto_unacknowledge_task.done()
                        else:
                            assert not alarm.auto_unacknowledge_task.done()
                        # Alarm was never muted.
                        assert alarm.unmute_task.done()

                        # Acknowledge again; this should have no affect
                        # except possibly restarting the unack timer.
                        restart_unack_timer = (
                            alarm.severity > AlarmSeverity.NONE and alarm.auto_unacknowledge_delay > 0
                        )
                        acked_alarm = self.copy_alarm(alarm)
                        user2 = "a different user"
                        updated = await alarm.acknowledge(severity=ack_severity, user=user2)
                        if restart_unack_timer:
                            assert updated
                            alarm.assert_equal(
                                acked_alarm,
                                ignore_attrs=["timestamp_auto_unacknowledge"],
                            )
                            assert (
                                alarm.timestamp_auto_unacknowledge > acked_alarm.timestamp_auto_unacknowledge
                            )
                        else:
                            assert not updated
                            alarm.assert_equal(acked_alarm)

            assert self.ncalls == desired_ncalls

    async def test_unacknowledge(self):
        user = "skipper"
        desired_ncalls = 0
        async for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            assert not alarm0.acknowledged

            # unacknowledge should have no effect initially
            # because alarm is not acknowledged
            alarm = self.copy_alarm(alarm0)
            updated = await alarm.unacknowledge()
            assert not updated
            alarm.assert_equal(alarm0)

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = self.copy_alarm(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = await alarm.acknowledge(severity=ack_severity, user=user)
                assert updated
                desired_ncalls += 1
                assert alarm.acknowledged
                if alarm0.severity == AlarmSeverity.NONE:
                    assert alarm.nominal
                else:
                    assert not alarm.nominal

                # unacknowledge the alarm
                acked_alarm = self.copy_alarm(alarm)
                tai0 = utils.current_tai()
                updated = await alarm.unacknowledge()
                if acked_alarm.nominal:
                    assert not updated
                    alarm.assert_equal(acked_alarm)
                else:
                    assert updated
                    desired_ncalls += 1
                    assert not alarm.nominal
                    assert not alarm.acknowledged
                    assert alarm.timestamp_acknowledged >= tai0
                    assert alarm.timestamp_severity_oldest == acked_alarm.timestamp_severity_oldest
                    assert alarm.timestamp_severity_newest == acked_alarm.timestamp_severity_newest
                    assert alarm.timestamp_max_severity == acked_alarm.timestamp_max_severity

        assert self.ncalls == desired_ncalls

    async def test_escalation(self):
        escalation_delay = 0.5
        escalation_responder = "chaos"

        async for alarm in self.alarm_iter(
            name="user",
            callback=self.callback,
            escalation_delay=escalation_delay,
            escalation_responder=escalation_responder,
        ):
            assert not alarm.do_escalate
            assert alarm.escalation_delay == escalation_delay
            assert alarm.escalation_responder == escalation_responder
            assert alarm.escalation_responder == escalation_responder
            if alarm.severity < AlarmSeverity.CRITICAL:
                assert alarm.timestamp_escalate == 0
                if not alarm.escalation_timer_task.done():
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(alarm.escalation_timer_task, timeout=0.5)
            else:
                assert alarm.timestamp_escalate > 0
                assert not alarm.escalation_timer_task.done()
                assert not alarm.do_escalate

                # Mute the alarm and make sure the escalation timer
                # is cancelled. Then unmute and make sure it starts again.
                await alarm.mute(duration=1, severity=AlarmSeverity.CRITICAL, user="muter")
                await self.next_queued_alarm(expected_alarm=alarm)
                if not alarm.escalation_timer_task.done():
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(alarm.escalation_timer_task, timeout=0.5)
                assert not alarm.do_escalate
                assert alarm.muted

                # Wait for the alarm to unmute itself
                await self.next_queued_alarm(expected_alarm=alarm)
                assert not alarm.muted
                assert not alarm.escalation_timer_task.done()
                assert not alarm.do_escalate

                # Wait for the alarm to call back when the escalation timer
                # fires. Then check the escalation fields set by Alarm.
                await self.next_queued_alarm(expected_alarm=alarm)
                assert alarm.escalation_timer_task.done()
                assert alarm.do_escalate

                # Acknowledging the alarm should clear do_escalate.
                await alarm.acknowledge(severity=AlarmSeverity.CRITICAL, user="arbitrary")
                assert not alarm.do_escalate
                assert alarm.escalation_timer_task.done()
                # Make sure this alarm called back, and flush
                # the callback queue.
                await self.next_queued_alarm(expected_alarm=alarm)

    async def test_reset(self):
        name = "alarm"
        blank_alarm = self.make_alarm(name=name, callback=None)
        blank_alarm.callback = self.callback
        assert blank_alarm.nominal
        async for alarm in self.alarm_iter(name=name, callback=self.callback):
            if not alarm.nominal:
                assert alarm != blank_alarm
            alarm.reset()
            alarm.assert_equal(blank_alarm)

    async def test_mute_valid(self):
        user = "otho"
        duration = 0.05
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            async for alarm in self.alarm_iter(name=user, callback=self.callback):
                t0 = utils.current_tai()
                await alarm.mute(duration=duration, severity=severity, user=user)
                curr_tai = utils.current_tai()
                dt = curr_tai - t0
                await self.next_queued_alarm(expected_alarm=alarm)
                assert alarm.muted
                assert alarm.muted_by == user
                assert alarm.muted_severity == severity
                # Check that timestamp_unmute is close to and no less than
                # the current time + duration.
                assert curr_tai + duration >= alarm.timestamp_unmute
                assert alarm.timestamp_unmute == pytest.approx(curr_tai + duration, abs=dt)
                # Wait for the alrm to unmute itself.
                await self.next_queued_alarm(expected_alarm=alarm, timeout=STD_TIMEOUT + duration)
                assert not alarm.muted
                assert alarm.muted_by == ""
                assert alarm.muted_severity == AlarmSeverity.NONE
                assert alarm.timestamp_unmute == 0

    async def test_mute_invalid(self):
        good_user = "otho"
        failed_user = "user associated with invalid mute command"
        good_delay = 5
        good_severity = AlarmSeverity.WARNING
        async for alarm in self.alarm_iter(name=good_user, callback=None):
            for bad_delay, bad_severity in itertools.product((0, -0.01), (AlarmSeverity.NONE, -53)):
                # check that mute raises ValueError for invalid values
                # and leaves the alarm state unchanged
                initial_alarm = self.copy_alarm(alarm)
                with pytest.raises(ValueError):
                    await alarm.mute(duration=bad_delay, severity=good_severity, user=failed_user)
                with pytest.raises(ValueError):
                    await alarm.mute(duration=good_delay, severity=bad_severity, user=failed_user)
                with pytest.raises(ValueError):
                    await alarm.mute(duration=bad_delay, severity=bad_severity, user=failed_user)
                alarm.assert_equal(initial_alarm)

                # make sure failures also leave muted alarm state unchanged
                await alarm.mute(duration=good_delay, severity=good_severity, user=good_user)
                assert alarm.muted
                assert alarm.muted_by == good_user
                assert alarm.muted_severity == good_severity
                muted_alarm = self.copy_alarm(alarm)

                with pytest.raises(ValueError):
                    await alarm.mute(duration=bad_delay, severity=good_severity, user=failed_user)
                alarm.assert_equal(muted_alarm)

                with pytest.raises(ValueError):
                    await alarm.mute(duration=good_delay, severity=bad_severity, user=failed_user)
                alarm.assert_equal(muted_alarm)

                with pytest.raises(ValueError):
                    await alarm.mute(duration=bad_delay, severity=bad_severity, user=failed_user)
                alarm.assert_equal(muted_alarm)

                await alarm.unmute()  # kill unmute timer

    async def test_unmute(self):
        user = "otho"
        duration = 5
        for severity in AlarmSeverity:
            if severity == AlarmSeverity.NONE:
                continue  # invalid value
            async for alarm in self.alarm_iter(name=user, callback=self.callback):
                ncalls0 = self.ncalls
                # check that unmute on unmuted alarm is a no-op
                original_alarm = self.copy_alarm(alarm)
                await alarm.unmute()
                alarm.assert_equal(original_alarm)
                assert self.ncalls == ncalls0 + 1

                # mute alarm and unmute it again before it unmutes itself
                t0 = utils.current_tai()
                await alarm.mute(duration=duration, severity=severity, user=user)
                curr_tai = utils.current_tai()
                dt = curr_tai - t0
                assert self.ncalls == ncalls0 + 2
                assert alarm.muted
                assert alarm.muted_by == user
                assert alarm.muted_severity == severity
                assert curr_tai + duration >= alarm.timestamp_unmute
                assert alarm.timestamp_unmute == pytest.approx(curr_tai + duration, abs=dt)

                await alarm.unmute()
                assert self.ncalls == ncalls0 + 3
                # Give asyncio a chance to cancel the mute task.
                await asyncio.sleep(0)
                assert alarm.unmute_task.done()
                # Compare equality.
                alarm.assert_equal(original_alarm)

    async def test_repr(self):
        name = "Something.else"
        alarm = self.make_alarm(name=name, callback=None)
        assert name in repr(alarm)
        assert "Alarm" in repr(alarm)

    async def test_set_severity_when_acknowledged(self):
        user = "skipper"
        desired_ncalls = 0
        async for alarm0 in self.alarm_iter(callback=self.callback):
            if alarm0.nominal:
                continue
            assert not alarm0.acknowledged

            # acknowledge the alarm
            for ack_severity in AlarmSeverity:
                alarm = self.copy_alarm(alarm0)
                if ack_severity < alarm.max_severity:
                    continue
                updated = await alarm.acknowledge(severity=ack_severity, user=user)
                desired_ncalls += 1
                assert updated
                assert alarm.acknowledged
                if alarm0.severity == AlarmSeverity.NONE:
                    assert alarm.nominal
                else:
                    assert not alarm.nominal

                acked_alarm = alarm
                for severity in AlarmSeverity:
                    alarm = self.copy_alarm(acked_alarm)
                    tai0 = utils.current_tai()
                    reason = f"set severity to {severity} after ack"
                    updated = await alarm.set_severity(severity, reason=reason)
                    if updated:
                        desired_ncalls += 1
                        assert alarm.severity == severity
                        if severity == acked_alarm.severity:
                            assert alarm.timestamp_severity_oldest == acked_alarm.timestamp_severity_oldest
                        else:
                            assert alarm.timestamp_severity_oldest >= tai0
                        assert alarm.timestamp_severity_newest >= tai0
                    if severity == AlarmSeverity.NONE:
                        if acked_alarm.nominal:
                            assert not updated
                            alarm.assert_equal(acked_alarm)
                        else:
                            # alarm should be reset
                            assert updated
                            assert alarm.max_severity == AlarmSeverity.NONE
                            assert alarm.reason == ""
                            assert not alarm.acknowledged
                            assert alarm.timestamp_max_severity >= tai0
                            assert alarm.timestamp_acknowledged >= tai0
                    else:
                        assert updated
                        assert alarm.reason == reason
                        if severity > acked_alarm.max_severity:
                            # alarm should be unacknowledged
                            assert alarm.max_severity == severity
                            assert not alarm.acknowledged
                            assert alarm.timestamp_max_severity >= tai0
                            assert alarm.timestamp_acknowledged >= tai0
                        else:
                            # alarm should remain acknowledged
                            assert alarm.max_severity == acked_alarm.max_severity
                            assert alarm.acknowledged
                            assert alarm.timestamp_max_severity == acked_alarm.timestamp_max_severity
                            assert alarm.timestamp_acknowledged == acked_alarm.timestamp_acknowledged

        assert self.ncalls == desired_ncalls
