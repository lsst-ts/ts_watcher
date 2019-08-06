# This file is part of ts_watcher.
#
# Developed for the LSST Data Management System.
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

__all__ = ["WatcherCsc"]

import asyncio
import pathlib

from lsst.ts import salobj
# from . import base
from .model import Model


class WatcherCsc(salobj.ConfigurableCsc):
    """The Watcher CSC.

    Parameters
    ----------
    config_dir : `str` (optional)
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `salobj.State` or `int` (optional)
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `lsst.ts.salobj.StateSTANDBY`,
        the default.

    Raises
    ------
    salobj.ExpectedError
        If initial_state or initial_simulation_mode is invalid.
    """
    def __init__(self, config_dir=None, initial_state=salobj.State.STANDBY):
        schema_path = pathlib.Path(__file__).resolve().parents[4].joinpath("schema", "Watcher.yaml")

        # the Watcher model is created when the CSC is configured
        self.model = None
        super().__init__("Watcher", index=0, schema_path=schema_path, config_dir=config_dir,
                         initial_state=initial_state, initial_simulation_mode=0)

    @staticmethod
    def get_config_pkg():
        return "ts_config_ocs"

    async def configure(self, config):
        if self.model is not None:
            # this should not happen, but in case it does shut down
            # the old model (disable alarms first because that is synchronous
            # and may avoid old alarms appearing due to a race condition)
            self.log.warning("self.model unexpectedly present in configure method")
            self.model.disable()
            asyncio.ensure_future(self.model.close())

        self.model = Model(domain=self.domain, config=config, alarm_callback=self.alarm_callback)
        await self.model.start_task
        self._enable_or_disable_model()

    def _enable_or_disable_model(self):
        """Enable or disable the model based on the summary state.
        """
        if self.summary_state == salobj.State.ENABLED:
            self.model.enable()
        elif self.model is not None:
            self.model.disable()

    def alarm_callback(self, alarm):
        """Callback function for alarms.
        """
        if self.summary_state != salobj.State.ENABLED:
            return
        self.evt_alarm.set_put(
            name=alarm.name,
            severity=alarm.severity,
            reason=alarm.reason,
            maxSeverity=alarm.max_severity,
            acknowledged=alarm.acknowledged,
            acknowledgedBy=alarm.acknowledged_by,
            escalated=alarm.escalated,
            escalateTo=alarm.escalate_to,
            mutedSeverity=alarm.muted_severity,
            mutedBy=alarm.muted_by,
            timestampSeverityOldest=alarm.timestamp_severity_oldest,
            timestampSeverityNewest=alarm.timestamp_severity_newest,
            timestampMaxSeverity=alarm.timestamp_max_severity,
            timestampAcknowledged=alarm.timestamp_acknowledged,
            timestampAutoAcknowledge=alarm.timestamp_auto_acknowledge,
            timestampAutoUnacknowledge=alarm.timestamp_auto_unacknowledge,
            timestampEscalate=alarm.timestamp_escalate,
            timestampUnmute=alarm.timestamp_unmute,
            force_output=True,
        )

    def report_summary_state(self):
        super().report_summary_state()
        self._enable_or_disable_model()

    def do_acknowledge(self, data):
        self.assert_enabled("acknowledge")
        self.model.acknowledge_alarm(name=data.name, severity=data.severity, user=data.acknowledgedBy)

    def do_mute(self, data):
        self.assert_enabled("acknowledge")
        raise salobj.ExpectedError("The mute command is not yet implemented")
