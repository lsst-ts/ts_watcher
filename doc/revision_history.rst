.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.revision_history:

################
Revision History
################

v0.5.0
======

Rename duration to timespan in the mute command.

* ts_salobj 5.2
* ts_xml 4.6
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.4.0
======

Update for ts_salobj 5.2: rename initial_simulation_mode to simulation_mode.

* ts_salobj 5.2
* ts_xml 4.5
* ts_idl 1
* IDL files for ``Watcher``, ``ATDome``, ``ScriptQueue``, and ``Test``, plus any SAL components you wish to watch.
  These may be generated using ``make_idl_files.py``

v0.3.0
======

Add the ``showAlarms`` command.
Make the ``test.ConfiguredSeverities`` rule cycle forever.

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
