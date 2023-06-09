.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher:

###############
lsst.ts.Watcher
###############

.. image:: https://img.shields.io/badge/Project Metadata-gray.svg
    :target: https://ts-xml.lsst.io/index.html#index-csc-table-watcher
.. image:: https://img.shields.io/badge/SAL\ Interface-gray.svg
    :target: https://ts-xml.lsst.io/sal_interfaces/Watcher.html
.. image:: https://img.shields.io/badge/GitHub-gray.svg
    :target: https://github.com/lsst-ts/ts_watcher
.. image:: https://img.shields.io/badge/Jira-gray.svg
    :target: https://jira.lsstcorp.org/issues/?jql=project%3DDM%20AND%20labels%3Dts_watcher

Overview
========

The Watcher monitors other SAL components and uses the data to generate alarms for display by LOVE.
The point is to provide a simple, uniform interface to handle alarms.

Each rule has one associated `Alarm`, and is reponsible for determining the severity of that alarm.
Alarm state changes trigger ``alarm`` events.

Rules may also emit ``notification`` events.
Notifications differ from alarms in that they have no state, so they cannot be acknowledged or muted; they are a rule-specific form of log message.
It is recommended that each rule either determine the severity of its alarm or emit ``notification`` events, not both.

All rules for the Watcher are defined in this package.
The CSC configuration specifies which of the available rules are used, and the configuration for each rule.

.. _lsst.ts.watcher.severity_levels:

Severity Levels
---------------

Alarms have the following available severity levels (though most alarms only use a subset):

* CRITICAL: Equipment is in danger. Critical alarms can be configured to be escalated to SquadCast if not acknowledged in time.
* SERIOUS: Something is broken.
* WARNING: Something is wrong but we can probably keep operating.
* NONE: No alarm condition present.

Each alarm has two severity fields:

* severity: the current severity, as reported by the rule.
* max_severity: the maximum severity seen since the alarm was last acknowledged.

Keeping track of max_severity makes sure that transient problems are seen and acknowledged, or, if so configured, escalated to SquadCast.

User Guide
==========

Start the Watcher CSC as follows:

.. prompt:: bash
    
    run_watcher

Stop the watcher by commanding it to the OFFLINE state, using the standard CSC state transition commands.

See Watcher `SAL communication interface <https://ts-xml.lsst.io/sal_interfaces/Watcher.html>`_ for commands, events and telemetry.

The configuration of the Watcher specifies:

* Which of the available rules it will run.
* The configuration for each rule.
* Escalation: which rules (if any) will be escalated as SquadCast alerts if critical alarms are not acknowledged in time.
* Automatic acknowledgement and unacknowledgement of alarms.

In order to escalate alarms to SquadCast you must define secret environment variable ESCALATION_KEY.
You can obtain this key from the SquadCast web site as follows:

* Click on Service in the left column.
* Click on the "Expand All" icon above and to the right of the table (3 thick horizontal bars).
* Click Add in the Alert Sources panel.
* Type Incident Webhook in the search box.
* Click on the Incident Webhook icon (it should have a green "Added" label on it).
* In the panel that is exposed copy the Webhook URL.
* The value for ESCALATION_KEY is the hexadecimal value after ".../v2/incidents/api/".

Configuration
-------------

The set of rules used by the Watcher and the configuration of each rule is specified by the CSC configuration.
The configuration options for each rule are specified by a schema provided by the rule.
A typical Watcher configuration file will specify most available rules, and will likely be large.

The Watcher configuration also has a list of disabled SAL components, for the situation that a subsystem is down for maintenance or repair.
Rules that use a disabled SAL component are not loaded.

Escalation
----------

It is possible to configure alarms to escalate to SquadCast, which can text or phone people who are on call.
See the escalation section of the configuration schema for the format.

A Watcher alarm is escalated by creating an SquadCast alert, if all of the following are true:

* The alarm is configured for escalation, meaning escalation delay > 0 and an escalation responder is specified, and the top-level configuration field ``escalation_url`` is not blank.
* The alarm reaches CRITICAL severity (even if only briefly).
* The alarm is not acknowledged before the escalation delay elapses.

If SquadCast accepts the request to create an alert then the Watcher sets the alarm's ``escalated_id`` field to the ID of the SquadCast alert.
This ID allows you to track the status of the alert in SquadCast.
If the attempt to create an SquadCast alert fails, ``escalated_id`` is set to an explanatory message that starts with "Failed: ".

If an escalated Watcher alarm is acknowledged, the Watcher will try to close the SquadCast alert, and will always set the alarm's ``escalation_id`` field back to an empty string.
This occurs regardless of the current severity of the alarm.

Subtleties:

* Each escalation configuration may apply to more than one rule.
  However, each rule will have, at most, one escalation configuration: the first match wins.
* If a given rule has no escalation configuration (a very common case) then it will never be escalated.
* Escalation and de-escalation are done on a "best effort" basis.
  The watcher will log a warning if anything goes obviously wrong.
* SquadCast's API operates in two phases.
  First it responds to a request with 202=ACCEPTED, or an error code if the request is rejected.
  The ACCEPTED message includes an ID you can use to poll SquadCast to find out if the request eventually succeeds or fails.
  However, the CSC only ever listens for the initial response, because there is nothing much it can do if the request eventually fails.

Auto Acknowledge and Unacknowledge
----------------------------------

You may configure the Watcher to auto-acknowledge and auto-unacknowledge alarms after a configurable period of time,
using configuration parameters ``auto_acknowledge_delay`` and ``auto_unacknowledge_delay``.

An alarm will be automatically acknowledged only if its current severity stays NONE for the full ``auto_acknowledge_delay`` period
(i.e. if the problem truly appears to have gone away).

An alarm will be automatically unacknowledged only if the condition does not get worse than the level at which it was ackowledged,
and does not get resolved (go to NONE), during the full ``auto_unacknowledge_delay`` period after being acknowledged.

SquadCast Notes
===============

.. toctree::
   :maxdepth: 2

   squadcast_notes.rst

Displaying Alarms
=================

.. toctree::
   :maxdepth: 2

   displaying_alarms.rst

Developer Guide
===============

.. toctree::
    developer_guide
    :maxdepth: 2

Version History
===============

.. toctree::
    version_history
    :maxdepth: 1
