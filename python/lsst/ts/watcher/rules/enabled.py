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

__all__ = ["Enabled"]

import typing

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity


class Enabled(watcher.BaseRule):
    """Monitor the summary state of a CSC.

    Set alarm severity NONE if the CSC is in the ENABLED state,
    and configurable severities in other states.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is f"Enabled.{name}:{index}",
    where name and index are derived from ``config.name``.
    """

    def __init__(self, config, log=None):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_summaryState"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"Enabled.{remote_info.name}:{remote_info.index}",
            remote_info_list=[remote_info],
            log=log,
        )

    @classmethod
    def get_schema(cls):
        def make_severity_property(state, default_severity):
            """Make all the data for one {state}_severity property.

            Parameters
            ----------
            state : `salobj.State`
                The state.
            default_severity : `AlarmSeverity`
                The default alarm severity for this state.
            """
            indent = "                "
            return f"""{indent}{state.name.lower()}_severity:
{indent}    description: alarm severity for state {state.name}
{indent}    type: integer
{indent}    default: {default_severity.value}
{indent}    enum:
""" + "\n".join(
                f"{indent}    - {severity.value}" for severity in AlarmSeverity
            )

        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for Enabled
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
{make_severity_property(salobj.State.DISABLED, AlarmSeverity.NONE)}
{make_severity_property(salobj.State.STANDBY, AlarmSeverity.NONE)}
{make_severity_property(salobj.State.OFFLINE, AlarmSeverity.SERIOUS)}
{make_severity_property(salobj.State.FAULT, AlarmSeverity.CRITICAL)}
            required:
            - name
            - disabled_severity
            - standby_severity
            - offline_severity
            - fault_severity
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> watcher.AlarmSeverityReasonType:
        state = data.summaryState
        try:
            state_name = salobj.State(state).name
            severity = getattr(self.config, f"{state_name.lower()}_severity")
        except Exception:
            state_name = f"{state} unknown"
            severity = self.config.fault_severity

        if state == salobj.State.ENABLED or severity == AlarmSeverity.NONE:
            return watcher.NoneNoReason
        return severity, f"{state_name} state"
