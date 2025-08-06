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

__all__ = ["MTAirCompressorsState"]

import typing

import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity

# SAL indices for MTAirCompressors to monitor.
SAL_INDICES = (1, 2)
SAL_INDICES_STR = ", ".join(str(index) for index in sorted(SAL_INDICES))

GOOD_STATES = frozenset((salobj.State.DISABLED, salobj.State.ENABLED))


class MTAirCompressorsState(watcher.BaseRule):
    """Monitor the summary state of the two MTAirCompressor instances.

    Set alarm severity None if both instances are disabled or enabled
    (both states are equally good from the perspective of providing
    compressed air).
    Set one configurable alarm level if either instance is not.
    Set a different configurable alarm level if both instances are not.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is "MTAirCompressorsState".
    """

    def __init__(self, config, log=None):
        remote_infos = [
            watcher.RemoteInfo(
                name="MTAirCompressor",
                index=0,
                callback_names=["evt_summaryState"],
                poll_names=[],
                index_required=False,
            )
        ]
        # Dict of sal_index: summary state.
        self.states = {index: "UNKNOWN" for index in SAL_INDICES}
        super().__init__(
            config=config,
            name="MTAirCompressorsState",
            remote_info_list=remote_infos,
            log=log,
        )

    @classmethod
    def get_schema(cls):
        enum_str = ", ".join(
            f"{severity.name}"
            for severity in AlarmSeverity
            if severity is not AlarmSeverity.NONE
        )
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for MTAirCompressorsState
            type: object
            properties:
              one_severity:
                description: >-
                  Alarm severity if one MTAirCompressor is in enabled or disabled state,
                  and the other is not (or its state has not been seen).
                type: string
                default: {AlarmSeverity.WARNING.name}
                enum: [{enum_str}]
              both_severity:
                description: >-
                  Alarm severity if neither MTAirCompressor is in enabled or disabled state.
                type: string
                default: {AlarmSeverity.CRITICAL.name}
                enum: [{enum_str}]
            required:
            - one_severity
            - both_severity
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def setup(self, model) -> None:
        self.one_severity = AlarmSeverity[self.config.one_severity]
        self.both_severity = AlarmSeverity[self.config.both_severity]

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs: typing.Any
    ) -> watcher.AlarmSeverityReasonType:
        if data.salIndex not in SAL_INDICES:
            self.log.warning(
                f"Ignoring data for sal_index={data.salIndex}; not in {SAL_INDICES_STR=}"
            )
            return None
        try:
            self.states[data.salIndex] = salobj.State(data.summaryState)
        except ValueError:
            self.log.warning(
                f"Ignoring unknown summaryState={data.summaryState} for MTAirCompressors:{data.salIndex}"
            )
            return None

        num_good = len([True for state in self.states.values() if state in GOOD_STATES])
        if num_good >= 2:
            return watcher.NoneNoReason

        states = ", ".join(f"{key}={value!r}" for key, value in self.states.items())
        if num_good == 1:
            return self.one_severity, "MTAirCompressor summaryStates:" + states
        return self.both_severity, "MTAirCompressor summaryStates:" + states
