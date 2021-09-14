.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.writing_rules:

#####################
Writing Watcher Rules
#####################

Overview
========

Each rule is responsible for setting the severity of a single alarm, based on data from one or more SAL topics.
Thus there is a one to one relationship between alarms and rules.
In fact each rule contains its alarm as attribute ``alarm`` and both have the same unique name.

When you read "rule" below you should usually think "rule and associated alarm".

We strongly recommend focusing a given rule on a single condition.
Keep it simple!
If a given alarm is used to report more than one condition then it can be difficult for an operator to understand what is wrong.
For example:

* It is better to have one rule for wind speed and another for humidity than one rule that covers many weather conditions.
* The `rules.Enabled` rule only monitors one CSC, not a list of CSCs.
  Instead we construct one instance of `rules.Enabled` for each CSC to monitor.

Note that a rule class can define more than one instance.
For example the `Enabled` rule monitors whether a CSC is in the ENABLED state, and there one instance of the Enabled rule for each CSC being monitored.

Rules can be configured.
For instance the `Enabled` rule is configured with the name and index of the CSC that it monitors.

Alarm Severity
--------------
The primary purpose of a rule is to set the severity of its alarm.
A rule can do this in two ways:

* Most rules specify one or more topics for which they are called when the topic receives a sample.
  The topic calls `BaseRule.__call__` which must return a tuple of (rule severity, reason).
  The calling code uses that returned tuple to set the alarm severity.
* A rule may directly set the severity of its alarm by calling `self.alarm.set_severity`.
  One example is the `Heartbeat` rule which restarts a timer when a heartbeat event is received.
  If the timer expires the rule sets its alarm severity to `SERIOUS`.

Note that the `BaseRule.__call__` should never directly set the alarm severity;
return the new (rule severity, reason) instead.

Alarm Name
----------
Each alarm must have a unique name.
This name is displayed in LOVE and is used to aknowledge and mute alarms.
The convention for rule names is ``rule_class_name.remote_name_index``, where ``rule_class_name`` is the class name of a rule relative to `lsst.ts.watcher.rule` and `remote_name_index` is the SAL component name and SAL index of the sole or primary SAL component that the rule listens to, in the form ``sal_component_name:index``.
Good examples are `Heartbeat.ATDome:0` and `test.ConfiguredSeverities.ScriptQueue:1`.

Subtleties:

* ``rule_class_name`` is the same name used to specify a rule in the Watcher's configuration file.
  This consistency between rule name and rule class name is very helpful in figuring out which rule defines a given alarm.
* ``remote_name_index`` must always include the index, even if the index is optional in the rule configuration.
  This prevents a given rule's name from changing depending on whether a configuration includes or omits an optional SAL index.

Where Alarms Live
-----------------
All rules must be defined in modules in the python/lsst/ts/watcher/rules directory or subdirectories.

Writing a Rule
==============

The steps to writing a rule are as follows:

Configuration
-------------
Determine the configuration options you want to offer.
Examples are:
This can be as simple as voltage levels for various severities of alarm or as fancy as a remote name and index.
Construct a jsonschema describing the configuration and return it from the get_schema classmethod.

Note that a validated configuration is passed to the rule's constructor as a `types.SimpleNamespace`.

Constructor
-----------
Determine which SAL components and topic(s) you need data from
(this may depend on the configuration, as for `rules.Enabled`).
A typical rule should only need one or a very small number of topics.

For each topic decide whether you want to be called back when the value changes and which topics you want to poll.
When in doubt use a callback, so you will not miss any data.

Use this information to construct a `RemoteInfo` for each remote your rule listens to
and pass a list of these to the `BaseRule.__init__`

\_\_call\_\_
------------
The `BaseRule.__call__` method is called whenever a topic you have subscribed receives a sample.
It receives a single argument: a `TopicWrapper` for the topic.

Compute the new alarm severity and a reason for it and return these as a tuple: ``(severity, reason)``.
you may return `NoneNoReason` if the severity is ``NONE``.

start
-----
If your rule polls data or has other needs for background timers or events, start them in `BaseRule.start`.

stop
----
If your rule starts any background tasks then stop them in `BaseRule.stop`.

Testing a Rule
==============
Add a unit test to your rule in ``tests/rules`` or an appropriate subdirectory.

I suggest constructing a `Model` with a configuration that just specifies the one rule you are testing.
This saves the headache of figuring out how to fully construct a rule yourself (including the necessary remote(s) and topic(s)).
