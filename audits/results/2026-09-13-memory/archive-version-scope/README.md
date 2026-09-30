# Archive source version scope

The runner now sets `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YPRICEMAGIC=0.0.0`.
It no longer sets the global `SETUPTOOLS_SCM_PRETEND_VERSION` variable, which
incorrectly changed versions of dependencies built inside the container.

The isolated editable ypricemagic build completes with version 0.0.0.
The [version check](version-scope.json) confirms that the global override is
absent and that installed dependency versions remain their own versions.
The command exits zero. This build check does not import all application
extensions or replace the required archive and native test checks.

The original dependency metadata failure and the later unrelated faster-eth-abi
build failure remain recorded in [HTTP ownership evidence](../http-request-ownership/README.md).
