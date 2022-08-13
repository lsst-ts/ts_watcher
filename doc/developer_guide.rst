.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.developer_guide:

###############
Developer Guide
###############

The Watcher CSC is implemented using `ts_salobj <https://github.com/lsst-ts/ts_salobj>`_.

The fundamental objects that make up the Watcher are rules and alarms.
There is a one to one relationship between these: every rule contains one associated alarm.
It is the logic in a rule that determines the state of its alarm.

Each rule monitors messages from remote SAL components (or, potentially, other sources).
Based on that logic the Watcher sets the severity of the associated alarm.
Rules are instances of *subclasses* of `BaseRule`.
There are many such subclasses.

Each alarm contains state, including the current severity, whether the alarm has been acknowledged, and the maximum severity seen since last acknowledgement.
Alarms are instances of `Alarm`.

Other Classes
=============

`Model` manages all the rules that are in use.
It is the model that uses the watcher configuration to construct rules, construct salobj remotes and topics and wire everything together.
The model also disables rules when the Watcher CSC is not in the ENABLED state.

In order to reduce resource usage, remotes (instances of `lsst.ts.salobj.Remote`) and topics (instances of `lsst.ts.salobj.topics.ReadTopic`) are only constructed if a rule that is in use needs them.
Also remotes and topics are shared, so if more than one rule needs a given Remote, only one is constructed.

Since rules share remotes and topics, the rule's constructor does not construct remotes or topics (which also means that a rule's constructor does not make the rule fully functional).
Instead a rule specifies the remotes and topics it needs by constructing `RemoteInfo` objects, which the `Model` uses to construct the remotes and topics and connect them to the rule.

`TopicCallback` supports calling more than one rule from a topic.
This is needed because a salobj topic can only call back to a single function and we may have more than one rule that wants to be called.

Rules are isolated from each other in two ways, both of which are implemented by wrapping each remote with multiple instances of `RemoteWrapper`, one instance per rule that uses the remote:

* A rule can only see the topics that it specifies it wants.
  This eliminates a source of surprising errors where if rule A if uses a topic specified only by rule B then the topic will only be available to rule A if rule B is being used.
* A rule can only see the current value of a topic; it cannot wait on the next value of a topic.
  That prevents one rule from stealing data from another rule.

Writing Rules
=============

.. toctree::
   :maxdepth: 2

   writing_rules.rst

Contributing
============

``lsst.ts.watcher`` is developed at https://github.com/lsst-ts/ts_watcher.
You can find Jira issues for this module using `labels=ts_watcher <https://jira.lsstcorp.org/issues/?jql=project%3DDM%20AND%20labels%3Dts_watcher>`_.

.. _lsst.ts.watcher-pyapi:

Python API reference
====================

.. automodapi:: lsst.ts.watcher
    :no-main-docstr:
.. automodapi:: lsst.ts.watcher.rules
    :no-main-docstr:
.. automodapi:: lsst.ts.watcher.rules.test
    :no-main-docstr:
    :no-inheritance-diagram:
