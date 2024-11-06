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

__all__ = ["ATCameraDewar"]

import asyncio
import collections
import dataclasses
import types
import typing

import numpy as np
import yaml
from lsst.ts import salobj, utils, watcher
from lsst.ts.idl.enums.Watcher import AlarmSeverity


@dataclasses.dataclass
class MeasurementInfo:
    """Information about a measurement.

    Attributes
    ----------
    descr : `str`
        Description of measurement.
    field_name : `str`
        Field name in AuxTel vacuum telemetry topic.
    is_temperature : `bool`, optional
        True (default) if temperature, false if vacuum.
    big_is_bad_list : List[bool], optional
        List of things to measure: too big (True) or too small (False)
        Defaults to [True]
    units : `str`, computed
        Units for the field: C or Torr. Computed from is_temperature.
    """

    descr: str
    field_name: str
    is_temperature: bool = True
    big_is_bad_list: typing.List[bool] = dataclasses.field(
        default_factory=lambda: [True]
    )
    units: str = dataclasses.field(init=False)

    def __post_init__(self):
        self.units = "temperature" if self.is_temperature else "Torr"


class ATCameraDewar(watcher.BaseRule):
    """Monitor ATCamera dewar temperatures and vacuum.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Raises
    ------
    jsonschema.ValidationError
        If the configuration does not match the schema.
    ValueError
        If the three threshold levels for a given measurement,
        e.g. the three min_*_ccd_temp fields, are all null or absent.
        If you want to suppress all alarms for a measurement,
        specify an unrealistic value for at least one threshold level
        for that measurement.

    Notes
    -----
    The alarm name is "ATCameraDewar".

    The rule raises an alarm if any of the following are true:

    * ccd temperature is too low
    * ccd temperature is too high
    * cold plate temperature is too high
    * cryo head temperature is too high
    * vacuum is too soft (pressure is too high)

    You may configure up to three severity threshold levels for each of
    these alarm conditions, but typically you should only specify two:
    a warning level and either a serious or a critical level.

    The vacuum pressure gauge occasionally "burps", and temperature
    measurements fluctuate somewhat, so alarm thresholds are based on
    median values reported within a configurable time window.
    """

    def __init__(self, config, log=None):
        remote_info = watcher.RemoteInfo(
            name="ATCamera",
            index=0,
            callback_names=["tel_vacuum"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name="ATCameraDewar",
            remote_info_list=[remote_info],
            log=log,
        )
        self.data_queue: salobj.BaseDdsDataType = collections.deque()
        self.max_data_age: float = max(config.temperature_window, config.vacuum_window)
        self.min_values = config.min_values
        self.had_enough_data = False
        self.threshold_handlers: typing.Dict[
            str, typing.List[watcher.ThresholdHandler]
        ] = collections.defaultdict(list)
        # Measurement name: MeasurementInfo
        self.name_meas_info = {
            "ccd_temp": MeasurementInfo(
                descr="CCD temperature",
                field_name="tempCCD",
                big_is_bad_list=[False, True],
            ),
            "cold_plate_temp": MeasurementInfo(
                descr="Cold plate temperature",
                field_name="tempColdPlate",
            ),
            "cryo_head_temp": MeasurementInfo(
                descr="Cryo head temperature",
                field_name="tempCryoHead",
            ),
            "vacuum": MeasurementInfo(
                descr="Vacuum pressure",
                field_name="vacuum",
                is_temperature=False,
            ),
        }
        # Dict of measurement name: alarm severity for that measurement.
        # Used to provide the current_severity argument to
        # ThresholdHandler.get_severity_reason.
        self.name_severity = {name: AlarmSeverity.NONE for name in self.name_meas_info}

        for name, info in self.name_meas_info.items():
            for big_is_bad in info.big_is_bad_list:
                self.threshold_handlers[name].append(
                    self._make_threshold_handler(
                        config=config, name=name, big_is_bad=big_is_bad
                    )
                )

        # Task used to run and cancel no_data_timer.
        self.no_data_timer_task = asyncio.Future()

    def _make_threshold_handler(
        self, config: types.SimpleNamespace, name: str, big_is_bad: bool
    ) -> watcher.ThresholdHandler:
        """Make a ThresholdHandler

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Rule configuration.
        name : `str`
            Item is being measured. One of:
            "ccd_temp", "cold_plate_temp", "cryo_head_temp", "vacuum".
        big_is_bad : `bool`
            True if measured values larger than the specified levels are bad.
            False if measured values smaller than the specified levels are bad.
        """
        minmax_str = "max" if big_is_bad else "min"
        info = self.name_meas_info[name]
        level_kwargs = {
            f"{severity}_level": getattr(
                config, f"{minmax_str}_{severity}_{name}", None
            )
            for severity in ("warning", "serious", "critical")
        }
        if not level_kwargs:
            raise RuntimeError(
                f"The configuration must specify at least one threshold for {minmax_str} {name}"
            )
        category = "temperature" if info.is_temperature else "vacuum"
        return watcher.ThresholdHandler(
            warning_period=0,
            serious_period=0,
            critical_period=0,
            hysteresis=getattr(config, f"{category}_hysteresis"),
            big_is_bad=big_is_bad,
            value_name=info.descr,
            value_format="0.3g",
            units=info.units,
            **level_kwargs,
        )

    @classmethod
    def get_schema(cls) -> typing.Dict[str, typing.Any]:
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description:
                Configuration for ATCameraDewar
                You must specify at least one threshold level for each item
                (min ccd_temp, max ccd_temp, max cold_plate_temp, etc.).
                It is common to specify a warning level and either a serious
                or a critical level (not usually both).
            type: object
            properties:
                min_warning_ccd_temp:
                    description: Minimum CCD temperature (C) below which warning.
                    type: [number, "null"]
                    default: -95.16
                min_serious_ccd_temp:
                    description: Minimum CCD temperature (C) below which serious.
                    type: [number, "null"]
                min_critical_ccd_temp:
                    description: Minimum CCD temperature (C) below which critical.
                    type: [number, "null"]
                    default: -97
                max_warning_ccd_temp:
                    description: Maximum CCD temperature (C) above which warning.
                    type: [number, "null"]
                    default: -93.16
                max_serious_ccd_temp:
                    description: Maximum CCD temperature (C) above which serious.
                    type: [number, "null"]
                max_critical_ccd_temp:
                    description: Maximum CCD temperature (C) above which critical.
                    type: [number, "null"]
                    default: -91
                max_warning_cold_plate_temp:
                    description: Maximum cold plate temperature (C) above which warning.
                    type: [number, "null"]
                    default: -108
                max_serious_cold_plate_temp:
                    description: Maximum cold plate temperature (C) above which serious.
                    type: [number, "null"]
                max_critical_cold_plate_temp:
                    description: Maximum cold plate temperature (C) above which critical.
                    type: [number, "null"]
                    default: -104
                max_warning_cryo_head_temp:
                    description: Maximum cryo head temperature (C) above which warning.
                    type: [number, "null"]
                    default: -140
                max_serious_cryo_head_temp:
                    description: Maximum cryo head temperature (C) above which serious.
                    type: [number, "null"]
                max_critical_cryo_head_temp:
                    description: Maximum cryo head temperature (C) above which critical.
                    type: [number, "null"]
                    default: -128
                max_warning_vacuum:
                    description: Maximum dewar vacuum (Torr) above which warning.
                    type: [number, "null"]
                    default: 1.0e-6
                max_serious_vacuum:
                    description: Maximum dewar vacuum (Torr) above which serious.
                    type: [number, "null"]
                max_critical_vacuum:
                    description: Maximum dewar vacuum (Torr) above which critical.
                    type: [number, "null"]
                    default: 6.0e-6
                temperature_window:
                    description: Period of time (seconds) over which to median temperatures.
                    type: number
                    default: 180
                    exclusiveMinimum: 0
                temperature_hysteresis:
                    description:
                        Hysteresis for temperature-based alarms (C).
                        The amount by which a value must improve past an
                        alarm threshold before the alarm severity decreases.
                    type: number
                    default: 0.4
                    exclusiveMinimum: 0
                vacuum_window:
                    description: Period of time (seconds) over which to median vacuums.
                    type: number
                    default: 600
                    exclusiveMinimum: 0
                vacuum_hysteresis:
                    description:
                        Hysteresis for vacuum-based alarms (Torr)
                        The amount by which a value must improve past an
                        alarm threshold before the alarm severity decreases.
                    type: number
                    default: 0.2e-6
                    exclusiveMinimum: 0
                min_values:
                    description:
                        The minimum number of values in order to report data.
                        No data is reported unless there are at least this many data points
                        for both vacuum and temperatures. (Treating these categories separately
                        would make it difficult to warn if we never got enough data
                        for the category that requires more data).
                        Once the rule first sees this much data, it will issue a warning
                        whenever the number of data points drops below this value.
                    type: integer
                    default: 10
                    exclusiveMinimum: 0
                max_data_age:
                    description:
                        The maximum time this rule will wait for data (seconds)
                        before issuing a serious alarm.
                    type: number
                    default: 60
                    exclusiveMinimum: 0
            required:
              - temperature_window
              - temperature_hysteresis
              - vacuum_window
              - vacuum_hysteresis
              - min_values
              - max_data_age
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def no_data_timer(self):
        """Timer for no data received."""
        await asyncio.sleep(self.config.max_data_age)
        await self.alarm.set_severity(
            severity=AlarmSeverity.SERIOUS,
            reason=f"No data seen in {self.config.max_data_age} seconds",
        )

    def reset_all(self):
        """Reset the alarm, clear the data queue, and restart the no-data
        timer.
        """
        self.alarm.reset()
        self.data_queue.clear()
        self.had_enough_data = False
        self.restart_no_data_timer()

    def restart_no_data_timer(self):
        """Start or restart the no-data timer."""
        self.no_data_timer_task.cancel()
        self.no_data_timer_task = asyncio.create_task(self.no_data_timer())

    def start(self):
        self.reset_all()
        self.restart_no_data_timer()

    def stop(self):
        self.no_data_timer_task.cancel()

    def compute_alarm_severity(
        self, data: salobj.BaseMsgType, **kwargs
    ) -> watcher.AlarmSeverityReasonType:
        self.restart_no_data_timer()
        self.data_queue.append(data)
        curr_tai = utils.current_tai()

        oldest_temp_tai = curr_tai - self.config.temperature_window
        oldest_vacuum_tai = curr_tai - self.config.vacuum_window
        oldest_tai = min(oldest_temp_tai, oldest_vacuum_tai)

        while self.data_queue:
            if self.data_queue[0].private_sndStamp >= oldest_tai:
                break
            self.data_queue.popleft()
        nelts = len(self.data_queue)
        if nelts < self.min_values:
            # Complain about not enough data, if we have been running
            if self.had_enough_data:
                return (
                    AlarmSeverity.WARNING,
                    f"We don't have enough data; {nelts} < {self.min_values}",
                )
            else:
                return watcher.NoneNoReason

        self.had_enough_data = True

        data_lists = {name: [] for name in self.name_meas_info}
        temperature_name_fields = {
            name: meas_info.field_name
            for name, meas_info in self.name_meas_info.items()
            if meas_info.is_temperature
        }
        for data in self.data_queue:
            if data.private_sndStamp > oldest_vacuum_tai:
                data_lists["vacuum"].append(data.vacuum)
            if data.private_sndStamp > oldest_temp_tai:
                for name, fieldname in temperature_name_fields.items():
                    data_lists[name].append(getattr(data, fieldname))

        severity_reasons = []
        worst_severity = AlarmSeverity.NONE
        for name, data in data_lists.items():
            severity, reason = self._get_severity_reason_for_one_item(
                data=data, name=name
            )
            severity_reasons.append((severity, reason))
            worst_severity = max(severity, worst_severity)

        if worst_severity == AlarmSeverity.NONE:
            return watcher.NoneNoReason

        reasons = []
        for severity, reason in severity_reasons:
            if severity == worst_severity:
                reasons.append(reason)

        return worst_severity, "; ".join(reasons)

    def _get_severity_reason_for_one_item(self, data, name):
        """Get the severity and reason for a single item.

        Parameters
        ----------
        data : List [float]
            Measurements of item
        name : `str`
            Name of item.
        """
        current_severity = self.name_severity[name]
        median_value = np.median(data)

        # Only one name has multiple threshold handlers,
        # but it's a bit simpler to assume they all do.
        severity_reasons = []
        worst_severity = AlarmSeverity.NONE
        for threshold_handler in self.threshold_handlers[name]:
            severity, reason = threshold_handler.get_severity_reason(
                value=median_value, current_severity=current_severity, source_descr=""
            )
            severity_reasons.append((severity, reason))
            worst_severity = max(severity, worst_severity)
        for severity, reason in severity_reasons:
            if severity == worst_severity:
                # Only one threshold handler can complain (a value can't be
                # both too small and too large) so return the first match.
                self.name_severity[name] = severity
                return severity, reason
