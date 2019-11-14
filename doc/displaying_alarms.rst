.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.displaying_alarms:

#################################################
Guidelines for Displaying Alarms from the Watcher
#################################################

Alarm Events
------------

Alarm data is contained in the ``alarm`` Watcher event.
The primary fields needed for display are:

* ``name``: the name of the alarm.
  Each alarm has a unique name.
* ``severity``: the current severity of the alarm.
  One of ``NONE``, ``WARNING``, ``SERIOUS`` and ``CRITICAL``.
* ``maxSeverity``: the maximum severity seen for this alarm since it was last reset.
  Reset to ``NONE`` if alarm is aknowledged while the severity is ``NONE``.
  Thus ``maxSeverity`` should always be >= ``severity``.
* ``acknowledged``: has this alarm been acknowledged?
  Ignore if ``severity`` and ``maxSeverity`` are both ``NONE``.
  If ``acknowledged`` then the name of the user who acknowledged it is given in ``acknowledgedBy``.
* ``mutedSeverity``: if greater than ``NONE`` then the alarm is :ref:`muted <lsst.ts.watcher.muted_alarms>`.
* ``reason``: the detailed reason for the current severity.
  This will almost certainly be blank if severity is ``NONE`` and is set blank when the alarm is reset.
* ``timestampEscalate``: time at which the alarm will be escalated if not knowledged (once escalation is supported).
  Ignore if ``maxSeverity < CRITICAL``.

Display Suggestions
-------------------

For purposes of displaying alarms I suggest that you consider an alarm to have the following states (in addition to severity), each of which should be displayed differently:

* ``Nominal``: no problem; remove the alarm from the Watcher display.
  This is indicated by``severity=NONE`` and ``maxSeverity=NONE``; the value of ``acknowledged`` is *irrelevant*.
* ``Active`` or ``Semi-Active``: the alarm condition is present and has not been acknowledged.
  This is indicated by ``severity>NONE`` and ``acknowledged=False``.
  Semi-Active simply means that the alarm condition is present but has ameliorated somewhat; in other words ``severity < maxSeverity``.
* ``Stale``: the alarm condition is no longer present but the alarm was never acknowledged.
  This is indicated by ``severity=NONE``, ``maxSeverity>NONE`` and ``acknowledged=False``.
  Note that a stale alarm will still be escalated, if appropriate, so you *must* display stale alarms.
  One option to consider is to display them grayed out.

.. _lsst.ts.watcher.muted_alarms:

Muted Alarms
------------

Independently of the above states an alarm may also be *muted* by an operator, e.g. to hide a condition that keeps going away and returning again, so that acknowledging it becomes tedious.
A muted alarm is indicated by ``mutedSeverity > NONE``.
If the alarm severity goes above this level the alarm will unmute itself (set ``mutedSeverity`` back to ``NONE``); thus you do not need to pay attention to any severities to decide if an alarm is muted.
Muted alarms should not normally be displayed and will never be escalated.
However, please offer a way to view muted alarms, so an operator can umute a muted alarm, perhaps because the problem has been fixed or the alarm was accidentally muted.
Furthermore, it would be very helpful to always provide a count or other summary of muted alarms, so the operators know that some alarms are muted.

Other fields associated with muted alarms (only relevant if ``mutedSeverity > NONE``):

* The person who muted the alarm is given by ``mutedBy`` if ``mutedSeverity``
* The time at which the alarm will automatically unmute itself is given by ``timestampUnmute``.
