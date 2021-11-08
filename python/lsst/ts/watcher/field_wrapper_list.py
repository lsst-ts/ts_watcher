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

__all__ = ["FieldWrapperList"]

import math

from lsst.ts import utils


class FieldWrapperList:
    """A sequence of field wrappers.

    Provides convenient methods for extracting data.

    Attributes
    ----------
    field_wrappers : `list` [`BaseFilteredFieldWrapper`]
        List of field wrappers.
    """

    def __init__(self):
        self.field_wrappers = []

    def add_wrapper(self, field_wrapper):
        """Add a field wrapper to the collection.

        Parameters
        ----------
        field_wrapper : `BaseFilteredFieldWrapper`
            Field wrapper to add to the collection.
        """
        self.field_wrappers.append(field_wrapper)

    def get_data(self, omit_nan=True, max_age=None):
        """Return the current data, optionally with an age limit.

        Field wrappers that have not yet seen any data are omitted.

        Parameters
        ----------
        omit_nan : `bool`
            If True then omit NaN values.
        max_age : `float` or `None`
            The maximum age (in seconds) of the data; older data is omitted.
            If None then all data is returned.

        Returns
        -------
        data : `list` [`tuple`]
            A list of tuples, each of which is:

            * value: scalar value
            * wrapper: the field wrapper the value came from
            * value_index: index of the value in ``wrapper.value``,
              or `None` if ``wrapper.value`` is a scalar.
        """
        data = []
        for wrapper in self.field_wrappers:
            if wrapper.value is not None:
                if wrapper.nelts is None:
                    data.append((wrapper.value, wrapper, None))
                elif getattr(wrapper, "indices", None) is None:
                    data += [(item, wrapper, i) for i, item in enumerate(wrapper.value)]
                else:
                    data += [(wrapper.value[i], wrapper, i) for i in wrapper.indices]

        if omit_nan:
            data = [item for item in data if not math.isnan(item[0])]

        if max_age is not None:
            tai = utils.current_tai()
            data = [item for item in data if tai - item[1].timestamp < max_age]

        return data
