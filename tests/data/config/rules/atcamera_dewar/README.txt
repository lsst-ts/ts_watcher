Configuration files for the ATCameraDewar rule unit tests.

good_*.yaml: valid configuration files.
bad_*.yaml: configuration files that should be rejected by the schema validator.
invalid_*.yaml: configuration files that match the schema, but are still not usable.
    These will raise an exception in the rule's constructor.
