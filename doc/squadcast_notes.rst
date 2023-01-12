.. py:currentmodule:: lsst.ts.watcher

.. _lsst.ts.watcher.squadcast_notes:

###############
SquadCast Notes
###############

Overview
--------

To escalate an alarm to `squadcast <https://squadcast.com>`_, trigger (create) an incident using the `Incident Webhook`_.

To de-escalate an alarm to `squadcast <https://squadcast.com>`_, resolve the incident using the `Incident Webhook`_.

The `Incident Webhook`_. identifies incidents by a user-provided "event_id".
Squadcast also uses a squadcast-assigned incident ID in its web site and when communicating via `API V3`_.
However, that incident ID is not useful when using the `Incident Webhook`_, and `API V3`_ does not appear to be useful to the Watcher.

If you do end up using `API V3`_ note that it requires a user-specific secret key specified in a header.
By comparison `Incident Webhook`_ requires a service-specific secret key that is part of the URL (no custom header is required).

Get the URL (including secret key) from the Incident Webhook service on the web site.
If the service has already been added, try adding it again to see the URL.

To control where incidents go, use the `squadcast website <https://squadcast.com>`_ to edit the Routing Rules for the Incident Webhook Service.

.. _Incident Webhook: https://support.squadcast.com/integrations/incident-webhook-incident-webhook-api
.. _API V3: https://apidocs.squadcast.com/?version=latest

Note: squadcasts's web site is squadcast.com, not squadcast.fm.
A web search is likely to take you to the wrong site.

Trigger an Incident
-------------------

To trigger (create) an incident send the following data.
The tags are fairly arbitrary, and Squadcast supports specifying the color using a format not shown here).
The tags shown in this example are those used by the Watcher::

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
  Watcher sends it and MockSquadCast requires it.
* It is not clear if I can obtain the incident ID very easily (the manual says nothing).
  Fortunately, I think Watcher need only use this simple Incident Webhook interface, in which case it will not need the incident ID.
* event_id need not be unique; all incidents that share an event_id will be resolved together (from tech support, since the manual says nothing.)
  Watcher sends a unique event_id for each incident, and MockSquadCast requires that they be unique.
* The payload size is limited to 30,000 bytes. Any payload that crosses this limit will not be processed.
  You will receive HTTP Status Code 413 (REQUEST_ENTITY_TOO_LARGE) to notify you of this.
  Other documentation suggests that the description may be limited to 15,000 bytes.

Resolve an Incident
-------------------

To resolve (close) an incident send::

    {
    "status": "resolve",
    "event_id": "5d81d9bc60e42f6b99ca4307"
    }

Details:
* If the event_id does not exist, the request will silently succeed.
* event_id is optional, but omitting it has no effect (rather than, say, resolving all triggered incidents that have no event_id). (Based on tests. The manual says nothing.)
* If more than one event exists with this event_id, all will be resolved. (Tech support. The manual says nothing.)
