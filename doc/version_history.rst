.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.version_history:

###############
Version History
###############

v1.3.2
======

Changes:

* Fix the requirements for 1.3.0 and 1.3.1 in the version history.

v1.3.1
======

Changes:

* Add the ``kapacitor`` directory to save Kapacitor alert scripts.

Requires:

* ts_salobj 6
* ts_xml 4.6 - 6
* ts_idl 2
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.3.0
======

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
======

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
======

Changes:

* Update for compatibility with ts_salobj 6.

Requires:

* ts_salobj 5.11 - 6
* ts_xml 4.6 - 6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.0.3
======

Changes:

* Add conda package configuration file and Jenkinsfile script to manage build process.

Requires:

* ts_salobj 5.11
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v1.0.2
======

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
======

Major changes:

* Code formatted by ``black``, with a pre-commit hook to enforce this. See the README file for configuration instructions.

v1.0.0
======

Added the unacknowledge command.
Added automatic unacknowledgement of active alarms and automatic acknowledgement of stale alarms, after configurable durations.

Requires:

* ts_salobj 5.2
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.4.0
======

Update for ts_salobj 5.2: rename initial_simulation_mode to simulation_mode.

Requires:

* ts_salobj 5.2
* ts_xml 4.5
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.3.0
======

Add the ``showAlarms`` command.
Make the ``rules.test.ConfiguredSeverities`` rule cycle forever.

Requires:

* ts_salobj 5.
* ts_xml 4.5.
* ts_idl 1.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.2
======

Add ts_salobj to the ups table file.

Requires:

* ts_salobj 4.5.
* ts_xml 4.3 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.1
======

Fixed an incompatibility with ts_salobj 4.5 (use of a function only available in ts_salobj v5).

Requires:

* ts_salobj 4.5.
* ts_xml 4.3 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.

v0.2.0
======

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
======

First preliminary release.

There are a few rules and the unit tests pass, but we will need at least one configuration file in ts_config_ocs to declare it fully functional, and preferably more rules as well.

Requires:

* ts_salobj 4.5.
* ts_xml v4.1.0 for the Watcher SAL component.
* ts_idl 0.3 for the Watcher enums.
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``.
