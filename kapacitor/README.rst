Kapacitor alert scripts.

Overview
========

Chronograf supports publishing alerts based on data from the Engineering Facilities Database (EFD);
these alerts are called Kapacitor tasks.
This directory contains the scripts for Kapactor alert tasks used by Telescope and Site.

You may have to edit each script to configure it for different locations (e.g. summit, NCSA test stand).
Each script should start with a comment describing what it does and how to configure it.

Files ending in ".tick" are TICKscript scripts, used by Chronograf 1.
Files ending in ".flux" are Flux scripts, supported by Chronograf 1.8 and later.

This directory exists because Chronograf does not have any history for its Kapacitor alert tasks,
and because it is far too easy for the simple alert GUI to corrupt a TICKscript, as explained in `Protecting Alerts`_.

Creating Alerts
===============

These instructions are for Chronograf 1.5.

Log into Chronograf and click on the ⚠️ icon from the left toolbar and select Alerting > Manage Tasks.

Manage Tasks shows two lists of alerts labeled "1. Alert Rule" and "2. TICKscripts".
The first list offers a GUI for creating and editing simple alert rules;
the second list allows you to create more complex rules by editing the source code for the alert rule.
The simple GUI is a great way to create a new alert, but risky, as explained in `Protecting Alerts`_.

.. note:: Always save the TICKscript for your alert rule to github (e.g. by adding it to this directory).
          Choronograf 5 offers no history for rule scripts.

Creating a rule using the simple GUI:

* Create a new alert rule by pressing the blue "+ Build Alert Rule" button.
* Set the parameters as you like them.
* Save the result.
* The new rule will show up in both lists,
  so to support features beyond the simple GUI you can refine the rule by editing the TICKscript.
* If you edit the TICKscript, see `Protecting an Alert`_ to prevent it from being corrupted by the simple GUI.

Creating a rule using TICKscript:

* Press the green "+ Write TICKscript" button.
* Create and save your code.
* The alert should only show up in the second list, and so not need to be protected from corruption by the simple GUI.

Parameters:

* Most rules use source efd.autogen (var db = 'efd').
* The Watcher to Slack rules use Stream mode (var data = stream).

Protecting Alerts
=================

If a complex alert shows up in both lists then it is at risk of being corrupted:
editing a rule using the simple GUI will **lose all code** that is not supported by the GUI.
To protect against this, create a new version of the rule using "+ Write TICKscript":

* Copy the TICKscript.
* Create a new TICKscript by pressing the green "+ Write TICKscript" button.
* Choose a new name (rename the original script, first, if necessary, to avoid conflicts).
* Paste your TICKscript.
* The new alert rule should only show up in the second list.

Testing an Alert
================

The only way I know to test an alert is to trigger the condition.
Chronograf 1.5 offers no way to manually trigger an alert.
