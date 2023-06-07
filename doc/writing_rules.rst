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
The primary purpose of a rule is to compute the :ref:`severity <lsst.ts.watcher.severity_levels>` of its alarm.
The main logic for this goes into an override of `BaseRule.compute_alarm_severity`, which must return a tuple of ``(severity, reason)``.

That method can be called in several ways:

* Many rules specify one or more topics for which they are called when the topic receives a message.
  When data for that topic is received, the associated `TopicCallback` calls `BaseRule.update_alarm_severity`, which calls `BaseRule.compute_alarm_severity`.
  Both calls receive two arguments, detailed below.
* Polling rules (subclasses of `PollingRule` and `BaseEssRule`) call `BaseRule.update_alarm_severity` at regular intervals, with no arguments.
  This calls`BaseRule.compute_alarm_severity`, again with no arguments.
* Directly call `self.alarm.set_severity`.
  This is useful for rules that need to defer setting the severity.  
  One example is the `Heartbeat` rule.
  This starts a timer whenever a heartbeat event is received, and if the timer expires then the alarm severity set to a configured level.

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
Examples include:

* `rules.Enabled` accepts a remote name and SAL index, formatted as ``{name}[:{index}]`` (a standard that can be parsed with `lsst.ts.salobj.name_to_name_index`).
* `rules.Humidity` is a good example of a :ref:`rule that uses ESS data <lsst.ts.watcher.writing_rules.ess_data>`.
  It specifies name, alarm levels, hysteresis, and a list of humidity sensors.

Construct a jsonschema describing the configuration and return it from the `BaseRule.get_schema` classmethod.

Note that a validated configuration is passed to the rule's constructor as a `types.SimpleNamespace`.
Note that only the top level is a `types.SimpleNamespace`.
Any "objects" below that will be `dict`\ s, though you can easily convert them using ``types.SimpleNamespace(**dict)``.

Constructor
-----------
Determine which SAL components and topic(s) you need data from.
This may depend on the configuration, as it does for `rules.Enabled`.
Most rules only need one or a few topics.

For each topic: decide whether you want to be called back when data is received, or whether you would rather poll for the current value:

* Events: always use a callback, to avoid missing data.
* High bandwidth telemetry: always poll, to avoid overwhelming the Watcher.
* Low-bandwidth telemetry: either is fine.

Use this information to construct a `RemoteInfo` for each remote your rule listens to and pass a list of these to the `BaseRule.__init__`

setup
-----
This optional method is an extra constructor stage that is called after the `Model` and all `lsst.ts.salobj.Remote`\ s are constructed,
but before the remotes have fully started.

This method is required by :ref:`rules that use ESS data <lsst.ts.watcher.writing_rules.ess_data>` and any other rules that use `FilteredTopicWrapper` and similar.

The default implementation is a no-op, and that suffices for most rules.

compute_alarm_severity
----------------------

All rules must override abstract method `BaseRule.compute_alarm_severity`.
This computes the alarm severity and return the information as a tuple:  ``(severity, reason)``.

If your rule is triggered by receiving SAL messages, specify the topics in `RemoteInfo`.
Then `BaseRule.compute_alarm_severity` will be called when new data arrives, with two arguments:

  * The new topic data.
  * The `TopicCallback` for this topic.
    This can be used to determine which topic the data is for.
    However, only a few rules are complicated enough need this; most rules can ignore it.

If your rule uses ESS data then see `ESS data <lsst.ts.watcher.writing_rules.ess_data>`.

If your rule relies only on polling, consider inheriting from `PollingRule`.
(Note that `BaseEssRule`, mentioned in `ESS data <lsst.ts.watcher.writing_rules.ess_data>`, is a subclass of `PollingRule`).
This calls `BaseRule.compute_alarm_severity` at regular intervals (set by ``config.poll_interval``), with no arguments.

If your rule compares a value to one or more severity threshold levels to determine the alarm severity, consider using `ThresholdHandler` to compute the severity and reason.
Most rules that use `ESS data <lsst.ts.watcher.writing_rules.ess_data>` fall into this category.
See `rules.Humidity` for a fairly simple example.

start
-----
If your rule polls data or has other needs for background timers or events, start them in `BaseRule.start`.

stop
----
If your rule starts any background tasks, then stop them in `BaseRule.stop`.

.. _lsst.ts.watcher.writing_rules.ess_data:

Rules that use ESS Data
=======================
Data from the ESS presents a special challenge for watcher rules, because an ESS CSC may write a given topic for more than one sensor (or, in the case of a multi-channel thermometer, one collection of sensors).
For example: an ESS CSC that is connected to two multi-channel thermometers will use the same ``temperature`` telemetry topic to report data for both of them, differing only in the value of the ``sensorName`` field.

The simplest solution is to subclass `BaseEssRule`, which takes care of most of the details.
See `rules.Humidity` for a simple example and `rules.DewPointDepression` for a more complex example.

If your rule is too complicated to allow inheriting from `BaseEssRule`, then you will probably have replicate what it does yourself.
`BaseEssRule` creates an instance of `FilteredEssFieldWrapper`\ s (or related class) for each field of each ESS topic of interest.
Then it creates a `FieldWrapperList` for each topic, to manage the field wrappers.
These objects take care of reading and caching data from the desired sensors.
For example, under the hood, the `rules.Humidity` rule has one `FieldWrapperList` and the `rules.DewPointDepression` rule has two: one for dew point and one for temperature.

Note: `FilteredEssFieldWrapper`\ s may only be constructed after the `Model` and `lsst.ts.salobj.Remote`\ s have been constructed,
so that must be done in the `BaseRule.setup` method, rather than the constructor.

If your ESS-based rule can distill the measurement down to a single value then you should consider using a `ThresholdHandler` to convert the value to a severity and reason.

Testing a Rule
==============
Add a unit test to your rule in ``tests/rules`` or an appropriate subdirectory.

We suggest constructing a `Model` with a configuration that just specifies the one rule you are testing.
This saves the headache of figuring out how to fully construct a rule yourself (including the necessary remote(s) and topic(s)).
