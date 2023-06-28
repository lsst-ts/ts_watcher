.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.squadcast_notes:

###############
SquadCast Notes
###############

Overview
--------

To escalate an alarm to `squadcast <https://squadcast.com>`_: :ref:`trigger an incident <lsst.ts.watcher.squadcast_notes.trigger_an_incident>`.

To de-escalate an alarm to `squadcast <https://squadcast.com>`_: :ref:`resolve the incident <lsst.ts.watcher.squadcast_notes.resolve_an_incident>`.

The Watcher uses the `Incident Webhook`_ service to perform these tasks.
Get the URL (including secret key) from the Incident Webhook service on the `squadcast website <https://squadcast.com>`_.
As of 2023-04 you can only see that URL when you add the service.
If that is still true when you want to find it, try adding the service again to see the URL.

To control how Squadcast distributes these incidents to people, use the `squadcast website <https://squadcast.com>`_ to edit the Routing Rules for the Incident Webhook Service.

.. _Incident Webhook: https://support.squadcast.com/integrations/incident-webhook-incident-webhook-api
.. _API V3: https://apidocs.squadcast.com/?version=latest

Note: squadcasts's web site is squadcast.com, not squadcast.fm.
A web search is likely to take you to the wrong site.

.. _lsst.ts.watcher.squadcast_notes.trigger_an_incident:

Trigger an Incident
-------------------

To trigger (create) an incident in `squadcast <https://squadcast.com>`_, send the following data to the `Incident Webhook`_.
The tags are fairly arbitrary, and Squadcast supports specifying the color using a format not shown here).
The tags shown in this example are those used by the Watcher.
Note that the Watcher sends a unique event_id for each trigger::

    {
    "message": "Summary of problem",
    "description": "Detailed description of the problem",
    "tags" : {
        "responder": "name of responder",
        "alarm_name": "Enabled.ESS:201",
    },
    "status": "trigger",
    "event_id": "5d81d9bc60e42f6b99ca4307"
    }

Details:

* The only required field is "message".
  The manual says "description" is also required, but based on tests it is not.
  Still, Watcher sends "description" and MockSquadCast requires it.
* "status" defaults to "trigger" (based on tests, because the manual says nothing).
  Watcher sends "trigger" and MockSquadCast requires it.
* "event_id" is NOT required and is NOT the same as the incident ID used by API v3
  (from tech support, since the manual says nothing).
  Watcher sends event_id (a unique value for each call) and MockSquadCast requires it.
* event_id need not be unique; all incidents that share an event_id will be resolved together (from tech support, since the manual says nothing.)
  Watcher sends a unique event_id for each incident, and MockSquadCast requires that they be unique.
* The payload size is limited to 30,000 bytes. Any payload that crosses this limit will not be processed.
  You will receive HTTP Status Code 413 (REQUEST_ENTITY_TOO_LARGE) to notify you of this.
  Other documentation suggests that the description may be limited to 15,000 bytes.

.. _lsst.ts.watcher.squadcast_notes.resolve_an_incident:

Resolve an Incident
-------------------

To resolve (close) an incident in `squadcast <https://squadcast.com>`_ send the following data to the `Incident Webhook`_.::

    {
    "status": "resolve",
    "event_id": "5d81d9bc60e42f6b99ca4307"
    }

Details:

* If the event_id does not exist, the request will silently succeed.
* event_id is optional (based on tests; the manual says nothing).
  I am not sure what happens if you omit it, but my guess is that it resolves all triggered incidents that have no event_id.
* If more than one event exists with this event_id, all will be resolved. (Tech support. The manual says nothing.)

Incident Webhook vs API v3
--------------------------

The Watcher does everything via the `Incident Webhook`_.
However, Squadcast also has different API called `API V3`_, which seems to be primarliy used to manage squads and such, rather than incidents.
The Watcher does not use `API V3`_.

The `Incident Webhook`_. identifies incidents by a user-provided "event_id".

Squadcast also uses a squadcast-assigned ``incident ID`` in its web site, and when communicating via `API V3`_.
However, that incident ID is not useful when using the `Incident Webhook`_, and `API V3`_ does not appear to be useful to the Watcher.
Which may be just as well, because I have no idea how to obtain the incident ID using the `Incident Webhook`_ (the manual says nothing).

If you do end up using `API V3`_ note that it requires a user-specific secret key specified in a header.
By comparison `Incident Webhook`_ requires a service-specific secret key that is part of the URL (no custom header is required).
