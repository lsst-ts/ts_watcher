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

import yaml

from lsst.ts.idl.enums.Watcher import AlarmSeverity
from lsst.ts import salobj
from lsst.ts.watcher import base


class Enabled(base.BaseRule):
    """Monitor the summary state of a CSC.

    Set alarm severity NONE if the CSC is in the ENABLED state,
    SERIOUS if the CSC is in a FAULT state, else WARNING.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.

    Notes
    -----
    The alarm name is f"Enabled.{name}:{index}",
    where name and index are derived from ``config.name``.
    """

    def __init__(self, config):
        remote_name, remote_index = salobj.name_to_name_index(config.name)
        remote_info = base.RemoteInfo(
            name=remote_name,
            index=remote_index,
            callback_names=["evt_summaryState"],
            poll_names=[],
        )
        super().__init__(
            config=config,
            name=f"Enabled.{remote_info.name}:{remote_info.index}",
            remote_info_list=[remote_info],
        )

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_watcher/Enabled.yaml
            description: Configuration for Enabled
            type: object
            properties:
                name:
                    description: >-
                        CSC name and index in the form `name` or `name:index`.
                        The default index is 0.
                    type: string

            required: [name]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def __call__(self, topic_callback):
        state = topic_callback.get().summaryState
        if state == salobj.State.ENABLED:
            return base.NoneNoReason
        elif state == salobj.State.FAULT:
            return AlarmSeverity.SERIOUS, "FAULT state"
        else:
            try:
                state_name = salobj.State(state).name
            except Exception:
                state_name = str(state)
            return AlarmSeverity.WARNING, f"{state_name} state"
