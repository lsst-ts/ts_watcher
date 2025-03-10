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

__all__ = ["Clock"]

import numpy as np
import yaml
from lsst.ts import salobj, watcher
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class Clock(watcher.BaseRule):
    """Monitor the system clock of a SAL component using the ``heartbeat``
    event.

    Set alarm severity WARNING if the absolute value of the clock error
    is above the configured threshold for `min_errors` sequential heartbeat
    events. The clock error is computed as the difference between the time
    the heartbeat event was sent and received; thus some delay is inevitable.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Notes
    -----
    The alarm name is f"Clock.{name}:{index}",
    where name and index are derived from ``config.name``.
    """

    min_errors = 3
    """Number of sequential errors required for a failure"""

    def __init__(self, config, log=None):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = watcher.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_heartbeat"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"Clock.{remote_info.name}:{remote_info.index}",
            remote_info_list=[remote_info],
            log=log,
        )
        self.threshold = config.threshold
        # An array of up to `min_errors` recent measurements of clock error
        # (seconds), oldest first.
        self.clock_errors = np.zeros(self.min_errors, dtype=float)
        # The number of values in `clock_errors`; maxes out at `min_errors`
        self.n_clock_errors = 0

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            description: Configuration for Clock
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string
                threshold:
                    description: Maximum allowed time error (sec).
                    type: number
                    default: 1

            required: [name]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def compute_alarm_severity(
        self,
        data: salobj.BaseMsgType,
        topic_callback: watcher.TopicCallback | None = None,
    ) -> watcher.AlarmSeverityReasonType:
        clock_error = data.private_rcvStamp - data.private_sndStamp
        if self.n_clock_errors < self.clock_errors.shape[0]:
            self.clock_errors[self.n_clock_errors] = clock_error
            self.n_clock_errors += 1
        else:
            # Shift clock_errors left one place and append the new value.
            self.clock_errors[0 : self.min_errors - 1] = self.clock_errors[1:]
            self.clock_errors[-1] = clock_error
        min_abs_error = np.min(np.abs(self.clock_errors))
        if min_abs_error > self.threshold:
            mean_error = np.mean(self.clock_errors)
            return (
                AlarmSeverity.WARNING,
                f"Mininum |error|={min_abs_error:0.2f}; mean error={mean_error:0.2f} sec",
            )
        return watcher.NoneNoReason
