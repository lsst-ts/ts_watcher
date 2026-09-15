# This file is part of ts_watcher.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["ClosedLoopDisabled"]

import yaml

from lsst.ts.xml.enums import MTAOS, Scheduler
from lsst.ts.xml.enums.Watcher import AlarmSeverity

from ..base_rule import BaseRule, NoneNoReason
from ..remote_info import RemoteInfo


class ClosedLoopDisabled(BaseRule):
    """Monitor MTAOS closed loop state when scheduler is running.

    This alarms will trigger if the (MT)Scheduler is running and
    the MTAOS closed loop is disabled. It serves to notify observers
    of this non-nominal, but acceptable condition.


    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration.
    log : `logging.Logger`, optional
        Parent logger.
    """

    def __init__(self, config, log=None):

        scheduler_info = RemoteInfo(
            name="Scheduler",
            index=1,
            callback_names=["evt_detailedState"],
            poll_names=[],
        )

        mtaos_info = RemoteInfo(
            name="MTAOS",
            index=0,
            callback_names=["evt_closedLoopState"],
            poll_names=[],
        )

        self.scheduler_detailed_state = None
        self.mtaos_closed_loop_state = None

        self.alarm_severity = getattr(AlarmSeverity, config.alarm_severity)

        super().__init__(
            config=config,
            name="ClosedLoopDisabled",
            remote_info_list=[scheduler_info, mtaos_info],
            log=log,
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = f"""
        $schema: http://json-schema.org/draft-07/schema#
        description: Configuration for ClosedLoopDisabled
        type: object
        properties:
            alarm_severity:
                description: Severity of this alarm.
                type: string
                enum:
                - {AlarmSeverity.WARNING.name}
                - {AlarmSeverity.SERIOUS.name}
                - {AlarmSeverity.CRITICAL.name}
                default: {AlarmSeverity.WARNING.name}
        additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(self, **kwargs):
        data = kwargs.get("data", None)

        substate = getattr(data, "substate", None)

        if substate is not None:
            self.scheduler_detailed_state = Scheduler.DetailedState(substate)

        closed_loop_state = getattr(data, "state", None)

        if closed_loop_state is not None:
            self.mtaos_closed_loop_state = MTAOS.ClosedLoopState(closed_loop_state)

        if (
            self.scheduler_detailed_state != Scheduler.DetailedState.IDLE
            and self.mtaos_closed_loop_state == MTAOS.ClosedLoopState.IDLE
        ):
            return self.alarm_severity, "MTAOS closed loop is disabled and Scheduler is running."

        return NoneNoReason
