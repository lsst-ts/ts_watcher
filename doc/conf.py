"""Sphinx configuration file for an LSST stack package.

This configuration only affects single-package Sphinx documentation builds.
"""

import os
import sys

# Add the current directory to the path so Sphinx can find our extension
sys.path.insert(0, os.path.abspath("."))

import lsst.ts.watcher  # noqa
from documenteer.conf.pipelinespkg import *  # type: ignore # noqa

project = "ts_watcher"
html_theme_options["logotext"] = project  # type: ignore # noqa
html_title = project
html_short_title = project
doxylink = {}  # Avoid warning: Could not find tag file _doxygen/doxygen.tag

intersphinx_mapping["ts_idl"] = ("https://ts-idl.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_salobj"] = ("https://ts-salobj.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_utils"] = ("https://ts-utils.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_xml"] = ("https://ts-xml.lsst.io", None)  # type: ignore # noqa

# Add our custom extension
extensions.append("sphinx_alarm_categorizer")  # type: ignore # noqa
