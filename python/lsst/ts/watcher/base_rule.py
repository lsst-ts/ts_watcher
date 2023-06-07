from __future__ import annotations

# This file is part of ts_watcher.
#
# Developed for Vera C. Rubin Observatory Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["NoneNoReason", "BaseRule", "RuleDisabledError"]

import abc
import types
import typing

from lsst.ts import salobj
from lsst.ts.idl.enums.Watcher import AlarmSeverity

from . import alarm

if typing.TYPE_CHECKING:
    from .model import Model
    from .remote_info import RemoteInfo
    from .topic_callback import TopicCallback


class RuleDisabledError(Exception):
    """Raised by BaseRule's constructor if the rule is disabled."""

    pass


# __call__ may return this if the alarm severity is NONE
NoneNoReason = (AlarmSeverity.NONE, "")


class BaseRule(abc.ABC):
    """Base class for watcher rules.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    name : `str`
        Name of alarm. This must be unique among all alarms
        and should be of the form system.[subsystem....]_name
        so that groups of related alarms can be acknowledged.
    remote_info_list : `list` [`RemoteInfo`]
        Information about the remotes used by this rule.
    alarms : `list` [`alarm.Alarm`] | None, optional
        List of 0 or more alarms managed by this rule.
        None (the default) results in a single alarm with ``name=name``;
        this is a very common case.
        An empty list is appropriate if the rule only writes the
        ``notification`` event and not the ``alarm`` event.

    Attributes
    ----------
    alarm : `Alarm`
        The alarm associated with this rule.
    remote_keys : `frozenset` [`tuple` [`str`, `int`]]
        Set of remote keys. Each element is a tuple of:

        * SAL component name (e.g. "ATPtg")
        * SAL index

    Notes
    -----
    `Model.add_rule` adds an attribute
    ``{lowerremotename}_{index} = `` `RemoteWrapper`
    to the rule for each remote in `remote_info_list`, where
    ``lowerremotename`` is the name of the SAL component cast to lowercase,
    and ``index`` is the SAL index (0 if not an indexed component).
    For example: ``atdome_0`` for ATDome (which is not indexed).
    This gives each rule ready access to its remote wrappers.
    """

    def __init__(
        self,
        config: types.SimpleNamespace,
        name: str,
        remote_info_list: list[RemoteInfo],
        alarms: list[alarm.Alarm] | None = None,
    ) -> None:
        self.config = config
        self.name = name
        self.remote_info_list = remote_info_list
        self.remote_keys = frozenset(info.key for info in remote_info_list)
        # The model sets the callback and auto delays

        if alarms is None:
            alarms = [alarm.Alarm(name=name)]
        self.alarms = alarms

    @classmethod
    @abc.abstractmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        """Return a jsonschema as a `dict`, to validate configuration.

        Notes
        -----
        Please provide default values for all fields for which defaults
        make sense. This makes watcher configuration files easier to write.

        If your rule has no configuration then return `None`.

        We recommend that you write the schema as yaml, for compactness,
        then use yaml.safe_load to convert it to a dict. For example::

            schema_yaml = \"\"\"
                $schema: http://json-schema.org/draft-07/schema#
                description: Configuration for MyRule
                type: object
                properties:
                ...
                required: [...]
                additionalProperties: false
            \"\"\"
            return yaml.safe_load(schema_yaml)

        """
        raise NotImplementedError("Subclasses must override")

    @classmethod
    def make_config(cls, **kwargs: str) -> types.SimpleNamespace:
        """Make a config from keyword arguments, after applying defaults.

        Parameters
        ----------
        kwargs
            The configuration, as a dict of property: name. The allowed
            properties and values are specified by the rule's config schema.

        Returns
        -------
        config : `types.SimpleNamespace`
            The rule configuration, with defaults applied as needed.

        Raises
        ------
        jsonschema.ValidationError
            If the provided kwargs are incorrect (missing keys,
            misspelled keys, incorrect data types...).
        """
        schema = cls.get_schema()
        if schema is None:
            if kwargs:
                raise ValueError("Rule has no schema, so the config dict must be empty")
            return types.SimpleNamespace()
        else:
            validator = salobj.DefaultingValidator(schema)
            full_config_dict = validator.validate(kwargs)
            return types.SimpleNamespace(**full_config_dict)

    def is_usable(self, disabled_sal_components: set[tuple[str, int]]) -> bool:
        """Return True if rule can be used, despite disabled SAL components.

        The default implementation returns true if all remotes used by this
        rule are enabled. Override if you need something more complicated.
        The attributes ``config``, ``name`` and ``remote_info_list``
        are all available when this method is called.

        Parameters
        ----------
        disabled_sal_components : `set` [`tuple` [`str`, `int`]]
            Set of disabled SAL components. Each element is a tuple of:

            * SAL component name (e.g. "ATPtg")
            * SAL index
        """
        return self.remote_keys.isdisjoint(disabled_sal_components)

    def setup(self, model: Model) -> None:
        """Perform post-constructor setup.

        Called after the remotes are constructed and populated with topics,
        but before the remotes have started.

        Parameters
        ----------
        model : `Model`
            The watcher model.

        Notes
        -----
        Possible uses:

        * Rules in which topics and/or fields are specified in configuration
          should check that the topics and/or fields exist. They may also
          set variables pointing to the appropriate topics.
        * Rules that start a background process may start the process here
          rather than in the constructor; this is especially helpful
          if the process needs access to topics or fields.

        Few rules require `setup`, so the default implemention is a no-op.
        """
        pass

    def start(self) -> None:
        """Start any background tasks, such as a polling loop.

        This is called when the watcher goes into the enabled state.

        Notes
        -----
        Do not assume that `start` is called before `stop`;
        the order depends on the initial state of the Watcher.

        Immediate subclasses need not call super().start()
        """
        pass

    def stop(self) -> None:
        """Stop all background tasks.

        This is called when the watcher goes out of the enabled state,
        and must stop any tasks that might trigger an alarm state change.

        Notes
        -----
        Do not assume that `start` is called before `stop`;
        the order depends on the initial state of the Watcher.

        This base implementation does nothing, so immediate subclasses
        need not call ``super().stop()``.
        """
        pass

    @abc.abstractmethod
    def __call__(
        self, data: salobj.BaseMsgType, topic_callback: TopicCallback | None
    ) -> None:
        """Run the rule.

        This should set the severity of one or more alarms and/or write a
        ``notification`` event, as appropriate.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            Message from the topic described by topic_callback.
        topic_callback : `TopicCallback` | None
            Topic callback wrapper.
            None simplifies unit tests for rules that ignore this argument.

        Returns
        -------
        A tuple of two values:

        severity: `lsst.ts.idl.enums.Watcher.AlarmSeverity`
            The new alarm severity.
        reason : `str`
            Detailed reason for the severity, e.g. a string describing
            what value is out of range, and what the range is.
            If ``severity`` is ``NONE`` then this value is ignored (but still
            required) and the old reason is retained until the alarm is reset
            to ``nominal`` state.

        Notes
        -----
        You may return `NoneNoReason` if the alarm states is ``NONE``.

        To defer setting an alarm state, start a task that calls
        ``set_severity`` later. For example the Heartbeat rule's
        ``__call__`` method is called when the heartbeat event is seen,
        and this restarts a timer. If the timer finishes
        (meaning the next heartbeat event was not seen in time),
        the timer set the alarm severity > ``NONE``.
        """
        raise NotImplementedError("Subclasses must override")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name})"
