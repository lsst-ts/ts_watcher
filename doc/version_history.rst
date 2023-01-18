.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.version_history:

###############
Version History
###############

v1.12.0
-------

Changes:

* Escalate critical alarms to SquadCast instead of OpsGenie.
  This changed the config schema version from v4 to v5.
* Add `rules.BaseEssRule` and modify `rules.Humidity` and `rules.OverTemperature` to inherit from it.
* `rules.Humdity`: add optional ``warning_msg``, ``serious_msg``, and ``critical_msg`` to config.
* Add `rules.UnderPressure`.
* Add `rules.test.TriggeredSeverities` rule.
  This is only intended for unit tests, since it will not transition between severities on its own.
  It gives unit tests complete control over when to report the next severity.
* Add `MockPagerDuty` and `MockSquadCast` classes.
* Make test_clock.py and test_heartbeat more robust by increasing the timing margin.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 13 and ts_sal 7.

v1.11.2
-------

Changes:

* Remove some obsolete backwards compatibility code for ts_xml 11 and 12 (DM-35892).
  Version v1.11.0 already required ts_xml 13, due to other changes.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 13 and ts_sal 7.

v1.11.1
-------

Changes:

* Modernize pre-commit hooks and conda recipe.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 13 and ts_sal 7.

v1.11.0
-------

Changes:

* Update for ts_xml 13:

  * Update rules to use the new ESS topics.
  * Update unit tests and documentation to eliminate use of obsolete ESS topics.

* Update rules that use ESS topics to use hard-coded topics (this was made possible by ts_xml 13), simplifying configuration:

  * `rules.DewPoint`
  * `rules.Humidity`
  * `rules.OverTemperature`

* Update CONFIG_SCHEMA to v4, because of the changes to the schemas of the rules noted above.
* Update `rules.ATCameraDewer` to improve float formatting in alarm details; vacuum was always shown as 0.00.
* Fix a race condition caused by making rule and topic wrapper callbacks read data from the topic callback instance:

  * `Model`: call call rules with an additional data argument.
  * `TopicCallback`:

    * Call rules and topic wrappers with an additional data argument.
    * Eliminate the `get` method; use the data passed to the callback, instead.
    * Add attribute ``call_event`` for unit tests.

  * Updated all rules accordingly.
  * Updated the "Writing Watcher Rules" document accordingly.

* Add `PollingRule` class, for rules that poll for data.
  Modified polling rules to use it.
* Add `write_and_wait` function for unit tests.
* Make test_clock.py compatible with Kafka salobj, while preserving compatibility with DDS salobj.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 13 and ts_sal 7.

v1.10.1
-------

Changes:

* Add new ScriptFailed rule, which monitors the ScriptQueue execution and set severity to WARNING if the current script failed.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 11 (preferably 13) and ts_sal 7.

v1.10.0
-------

Changes:

* Escalate alarms to OpsGenie by using the REST API to create alerts.

  * Update the CSC configuration schema to version 3:

    * Update ``escalation`` items by replacing the ``to`` field (a string) ``responders`` (a list of objects).
    * Add escalation_url.

  * Overhaul escalation-related `Alarm` fields.
    It is important to keep track of the ID of escalation alerts.
  * Update `Model` to handle the new `Alarm` fields.
  * Update `WatcherCsc` to handle the new `Alarm` fields and `Model` changes.
  * Add `MockOpsGenie`, a mock OpsGenie service for unit tests.
  * Add support for ts_xml 13, which has more detailed escalation information in the ``alarm`` event, while retaining backwards compatibility with ts_xml 11.

* Modernize the documentation.
  Split the main page into a User Guide (still part of the main page) and a Developer Guide (a separate page).
  Add a section on alarm escalation to the User Guide.


Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 11 (preferably 13) and ts_sal 7.

v1.9.0
------

Changes:

* Delete the command_watcher.py command-line script.
* Rename command-line scripts to remove ".py" suffix.
* Update HeartbeatWriter, a subclass of WriteTopic, in a unit test, to be compatible with ts_sal 7.
  ts_sal 7 is required for unit test test_clock.py to pass.
* Simplify some tests by using a write-only controller.
  This requires ts_salobj 7.1.
* Wait for SalInfo instances to start in unit tests.
* Modernize ``Jenkinsfile``.
* Use ``vars(message)`` instead of ``message.get_vars()`` in a unit test.
* Build with pyproject.toml.

Requires:

* ts_utils 1.1
* ts_salobj 7.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 11 and ts_sal 7

v1.8.0
------

Changes:

* Update for ts_salobj 7, which is required.
  This also requires ts_xml 11.

Requires:

* ts_utils 1.1
* ts_salobj 7
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py`` built with ts_xml 11

v1.7.0
------

Changes:

* Use index_generator from ts_utils.
  This requires ts_utils 1.1 or later.
* Add `ATCameraDewar` rule.
* `Alarm`:

    * Add ``init_severity_queue`` and ``assert_next_severity`` methods, for unit testing.
    * Fix ``unacknowledge`` to only restart the escalation timer if the alarm is configured with escalation information.

* Overhaul the unit tests to wait for events instead of sleeping for an arbitrary time, where practical.

Requires:

* ts_utils 1.1
* ts_salobj 6.3
* ts_xml 10.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.6.0
------

Changes:

* Add rules (most of which require ts_xml 10.1):

    * `rules.DewPointDepression`.
    * `rules.Humidity`.
    * `rules.OverTemperature`.
    * `rules.MTCCWFollowingRotator`: warn when the MT camera cable wrap is not following the camera rotator.

* Add classes  `FieldWrapperList`, `BaseFilteredFieldWrapper`, `FilteredEssFieldWrapper`, and `IndexedEssFilteredFieldWrapper`.
  These allow rules to handle data from CSCs such as the ESS, that publish the the same topic with different data for different subystems.
* Add class `ThresholdHandler`, which computes alarm severity by comparing a value to one or more threshold levels.
* `BaseRule` changes:

  * Add method `BaseRule.setup` for finishing construction and performing additional validation, after the model and topics are made.
    This is where a rule can add filtered field wrappers.
  * Add a default implementation of `BaseRule.is_usable`.
    Use this default implementation for all existing rules.
  * Add an attribute ``remote_keys``, which is used by `BaseRule.is_usable`.

* `Model` changes:

    * Change the type of ``disabled_sal_components`` from ``list`` to ``frozenset``.
    * Call `BaseRule.setup` after creating all topics.

* `TopicCallback`: add support for wrapper callbacks.
* Add function `get_topic_key`.
* Use package ``ts_utils``.
* Remove the ``base`` subpackage and move the contents up one level.
* Modernize unit tests to use bare assert.
* Make ``test_auto_acknowledge_unacknowledge`` in ``test_csc.py`` more robust by allowing a bit of clock jitter.
* Add ``Jenkinsfile``.

Requires:

* ts_utils 1
* ts_salobj 6.3
* ts_xml 10.1
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ESS``, ``MTMount``, ``ScriptQueue``, and ``Test``, plus any additional SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.5.3
------

Changes:

* Use `unittest.IsolatedAsyncioTestCase` instead of the abandoned asynctest package.
* Format the code with black 20.8b1.

Requires:

* ts_salobj 6.3
* ts_xml 7
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.5.2
------

Changes:

* Add a Kapacitor rule for the summit and rename the rule for the NCSA test stand.

Requires:

* ts_salobj 6.3
* ts_xml 7
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.5.1
------

Changes:

* Fix handling of missing version.py file.

Requires:

* ts_salobj 6.3
* ts_xml 7
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.5.0
------

Changes:

* Store the CSC configuration schema in code.
  This requires ts_salobj 6.3.

Requires:

* ts_salobj 6.3
* ts_xml 7
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.4.3
------

Changes:

* `WatcherCsc`: set ``version`` class variable.
  Test that this sets the cscVersion field of the softwareVersions event.
* Modernize doc/conf.py for documenteer 0.6.

Requires:

* ts_salobj 6.1
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.4.2
------

Changes:

* Update Jenkinsfile.conda to use the shared library.
* Pin the versions of ts_idl and ts_salobj in conda/meta.yaml.

Requires:

* ts_salobj 6.1
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.4.1
------

Changes:

* Fix ts-idl package name run dependency in conda recipe.
* Minor updates to conda recipe.

Requires:

* ts_salobj 6.1
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.4.0
------

Changes:

* Update for ts_salobj 6.1, which is required.
* Add `WatcherCsc` constructor argument ``settings_to_apply`` and set class variable ``require_settings = True``.
* Fix deprecation warnings about calling get(flush=False) on read topics.
* Remove obsolete .travis.yml file.
* Update to use ``pre-commit`` to maintain ``flake8`` and ``black`` compliance.

Requires:

* ts_salobj 6.1
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.3.3
------

Changes:

* Bug fix: Model mis-handled rules with no configuration.
* Improved a unit test to catch ts_salobj bug `DM-27380 <https://jira.lsstcorp.org/browse/DM-27380>`_.

Requires:

* ts_salobj 6
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.3.2
------

Changes:

* Fix the requirements for 1.3.0 and 1.3.1 in the version history.

Requires:

* ts_salobj 6
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.3.1
------

Changes:

* Add the ``kapacitor`` directory to save Kapacitor alert scripts.

Requires:

* ts_salobj 6
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.3.0
------

Changes:

* Add configuration for escalation.
* Set the escalated fields of Alarm events.
* Add optional ``delay`` and ``repeats`` configuration fields to `rules.test.ConfiguredSeverities`.
* Improve the git pre-commit hook.
* Update the docs to link ts_sal and ts_xml.
* Add ``valid_simulation_modes`` class variable to `WatcherCsc`.

Requires:

* ts_salobj 6
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.2.0
------

Changes:

* Add `bin/command_watcher.py`: a Watcher commander.
* Stop publishing ``alarm.timestampSeverityNewest``; it was causing too many unnecessary alarm messages.
* Make the ``showAlarms`` command only work if the CSC is enabled.
  It would fail in interesting ways if the CSC was not enabled.

Requires:

* ts_salobj 5.11 - 6
* ts_xml 4.6 - 6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.1.0
------

Changes:

* Update for compatibility with ts_salobj 6.

Requires:

* ts_salobj 5.11 - 6
* ts_xml 4.6 - 6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.0.3
------

Changes:

* Add conda package configuration file and Jenkinsfile script to manage build process.

Requires:

* ts_salobj 5.11
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.0.2
------

Changes:

* Add ``tests/test_black.py`` to verify that files are formatted with black.
  This requires ts_salobj 5.11 or later.
* Update test_csc.py to use ``lsst.ts.salobj.BaseCscTestCase``, which also makes it compatible with salobj 5.12.
* Update test_remote_wrapper.py to make it compatible with salobj 5.12.
* Update ``.travis.yml`` to remove ``sudo: false`` to github travis checks pass once again.

Requires:

* ts_salobj 5.11
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.0.1
------

Major changes:

* Code formatted by ``black``, with a pre-commit hook to enforce this. See the README file for configuration instructions.

v1.0.0
------

Added the unacknowledge command.
Added automatic unacknowledgement of active alarms and automatic acknowledgement of stale alarms, after configurable durations.

Requires:

* ts_salobj 5.2
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.4.0
------

Update for ts_salobj 5.2: rename initial_simulation_mode to simulation_mode.

Requires:

* ts_salobj 5.2
* ts_xml 4.5
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.3.0
------

Add the ``showAlarms`` command.
Make the ``rules.test.ConfiguredSeverities`` rule cycle forever.

Requires:

* ts_salobj 5.
* ts_xml 4.5.
* ts_idl 1.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.2
------

Add ts_salobj to the ups table file.

Requires:

* ts_salobj 4.5.
* ts_xml 4.3 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.1
------

Fixed an incompatibility with ts_salobj 4.5 (use of a function only available in ts_salobj v5).

Requires:

* ts_salobj 4.5.
* ts_xml 4.3 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.0
------

Add ``mute`` and ``unmute`` commands.
Add a `rules.Clock` rule to watch clock error.

Bug fixes:

* The ``acknowledge`` command was documented in ts_xml to support regular expressions, but did not.
* `Model.__aenter__` called `Model.start` instead of awaiting ``start_task``.
  Only the constructor should call `Model.start`.
* `Model.enable` ran topic callbacks once for every remote, rather than once period.

Requires:

* ts_salobj 4.5.
* ts_xml 4.3 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.1.0
------

First preliminary release.

There are a few rules and the unit tests pass, but we will need at least one configuration file in ts_config_ocs to declare it fully functional, and preferably more rules as well.

Requires:

* ts_salobj 4.5.
* ts_xml v4.1.0 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.
