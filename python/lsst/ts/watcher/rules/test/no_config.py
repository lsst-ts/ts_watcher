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

__all__ = ["NoConfig"]

from lsst.ts import watcher


class NoConfig(watcher.BaseRule):
    """A minimal test rule that has no configuration and no remotes.

    Set alarm severity to NONE. This alarm basically does nothing
    and is designed for unit tests.

    Parameters
    ----------
    config : `types.SimpleNamespace`
        Rule configuration, as validated by the schema.
    log : `logging.Logger`, optional
        Parent logger.

    Raises
    ------
    RuntimeError
        If `compute_alarm_severity` is called. When used as a normal alarm
        this method should never be called because the rule
        specifies topics to call it.

    Notes
    -----
    The alarm name is "test.NoConfig".
    """

    def __init__(self, config, log=None):
        super().__init__(
            config=config, name="test.NoConfig", remote_info_list=[], log=log
        )

    @classmethod
    def get_schema(cls):
        return None

    def compute_alarm_severity(self) -> None:
        raise RuntimeError("This should never be called")
