#!/usr/bin/env python
"""
Sphinx extension to generate a categorized list of Watcher alarms.

This extension creates a directive `alarm-categorizer` that
generates a categorized list of all Watcher alarms by extracting
information from the rule class docstrings.
"""

import inspect
import os
import sys

from docutils import nodes
from sphinx.util.docutils import SphinxDirective


def setup(app):
    """Set up the Sphinx extension."""
    app.add_directive("alarm-categorizer", AlarmCategorizer)
    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


class AlarmCategorizer(SphinxDirective):
    """A directive that generates a categorized list of Watcher alarms."""

    has_content = False
    required_arguments = 0
    optional_arguments = 0

    def run(self):
        """Generate the alarm list."""
        # Import watcher rules
        sys.path.insert(0, "")
        try:
            from lsst.ts.watcher import rules
        except ImportError:
            # If running outside of the standard environment, try to adapt
            try:
                # This path assumes we're running from the doc/ directory
                sys.path.insert(0, os.path.abspath(".."))
                from lsst.ts.watcher import rules
            except ImportError:
                error = nodes.error()
                error += nodes.paragraph(
                    text="Error: Could not import lsst.ts.watcher.rules"
                )
                return [error]

        # Categories and their order
        categories = {
            "Camera": [],
            "Environmental": [],
            "Power System": [],
            "MT Dome": [],
            "Main Telescope (MT)": [],
            "System": [],
            "Other": [],
        }

        # Rules that belong to specific categories
        category_patterns = {
            "Camera": ["Camera", "ATCamera"],
            "Environmental": [
                "Humidity",
                "DewPoint",
                "Hvac",
                "Pressure",
                "Temperature",
                "ESS",
            ],
            "Power System": ["Power"],
            "MT Dome": ["MTDome"],
            "Main Telescope (MT)": ["MT"],
            "System": ["Clock", "Enabled", "Heartbeat", "ScriptFailed", "Telemetry"],
        }

        # Get all classes from the rules module
        rule_classes = []
        for attr_name in dir(rules):
            if attr_name.startswith("_") or attr_name == "test":
                continue
            attr = getattr(rules, attr_name)
            if inspect.isclass(attr) and attr.__module__.startswith(
                "lsst.ts.watcher.rules"
            ):
                rule_classes.append(attr)

        # Categorize rule classes
        for rule_class in rule_classes:
            name = rule_class.__name__
            docstring = inspect.getdoc(rule_class) or ""

            # Determine category
            category = "Other"
            for cat, patterns in category_patterns.items():
                if any(pattern in name for pattern in patterns):
                    category = cat
                    break

            # Add to appropriate category
            categories[category].append((name, rule_class, docstring))

        # Create output - start with a container
        container = nodes.container()

        # Add each category and its rules
        for category, items in categories.items():
            if not items:
                continue

            # Category header
            cat_section = nodes.section()
            cat_section["ids"].append(
                f"alarm-category-{category.lower().replace(' ', '-')}"
            )
            cat_title = nodes.title(text=f"{category} Alarms")
            cat_section += cat_title

            # Add each rule in this category
            for name, rule_class, docstring in sorted(items, key=lambda x: x[0]):
                para = nodes.paragraph()

                # Create a reference to the class
                ref = nodes.reference("", "")
                ref["refuri"] = f"py-api/lsst.ts.watcher.rules.{name}.html"
                ref += nodes.strong(text=name)
                para += ref

                # Add description from docstring
                if docstring:
                    # Extract first paragraph from docstring
                    # (all consecutive non-empty lines)
                    lines = docstring.split("\n")
                    first_para_lines = []
                    for line in lines:
                        line = line.strip()
                        if (
                            not line and first_para_lines
                        ):  # Empty line after content marks paragraph end
                            break
                        if line:  # Skip empty lines at the beginning
                            first_para_lines.append(line)

                    first_para = " ".join(first_para_lines)
                    # Split long line into multiple lines
                    para += nodes.Text(
                        " - "
                        + first_para[:79]
                        + (first_para[79:] if len(first_para) > 79 else "")
                    )

                cat_section += para

            container += cat_section

        return [container]
