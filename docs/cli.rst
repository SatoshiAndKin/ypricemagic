CLI Tools
=========

The y/cli.py module provides command-line tools for debugging and database management.

Debugging
---------

The CLI includes commands to inspect price retrieval and Curve pool operations.

debug price
~~~~~~~~~~~
Description:
    Debug token price retrieval with the specified token address and an optional
    block number. This operation enables DEBUG logging for ``y``. It reuses an
    available handler, or adds a stream handler if none is available. Importing
    the CLI and running ``audit-prices`` or database commands preserve the
    configured logging level and handlers.

    Long-running calls emit DEBUG-only ``y.stuck?`` messages every five minutes
    when that logger is enabled. See :doc:`caching` for diagnostic guidance.

Usage:
    ypricemagic debug price --token <token_address> [--block <block_number>]

Example:
    ypricemagic debug price --token 0x6B3595068778DD592e39A122f4f5a5cF09C90fE2 --block 18000000

debug curve
~~~~~~~~~~~
Description:
    Debug Curve pool operations by running the Brownie script "debug-curve". This command requires a pool token address provided through the --token flag. An optional --block flag sets the block number for evaluation.

Usage:
    ypricemagic debug curve --token <pool_address> [--block <block_number>]

Example:
    ypricemagic debug curve --token 0x123456...

Database Management
-------------------

db info
~~~~~~~
Description:
    Displays database information including table row counts and, for PostgreSQL, the storage size using pg_total_relation_size. For SQLite, it shows the file size along with row counts.

Usage:
    ypricemagic db info

db vacuum
~~~~~~~~~
Description:
    Reclaims unused space by running a VACUUM operation. In SQLite, the database file is rebuilt; in PostgreSQL, space is reclaimed to improve performance.

Usage:
    ypricemagic db vacuum

db clear
~~~~~~~~
Description:
    Clears cached price data from the database. You must supply exactly one of the following options:
      - --token: Token address or symbol.
      - --block: Block number.

Usage:
    To clear by token address:
        ypricemagic db clear --token 0xABCdef
    To clear by token symbol:
        ypricemagic db clear --token MOON
    To clear by block:
        ypricemagic db clear --block 1000000

db nuke
~~~~~~~
Description:
    Drops all tables in the database, effectively clearing all stored data. A confirmation prompt is shown unless the --force flag is used to bypass it.

Usage:
    With confirmation:
        ypricemagic db nuke
    Without confirmation:
        ypricemagic db nuke --force

db select
~~~~~~~~~
Description:
    Selects a token from the database matching the specified token address or token symbol, and displays detailed information about the token.

Usage:
    ypricemagic db select <target>
    (Replace <target> with the token address or symbol, for example:
        ypricemagic db select 0x123abc... or
        ypricemagic db select MOON)

db reset-prices
~~~~~~~~~~~~~~~
Description:
    Back up the configured SQLite database and remove one chain's cached prices.
    Stop all writers before this command. The backup path must not exist.
    The command checks the backup, reports deleted rows, and preserves metadata,
    events, discovery data, and prices for other chains. Restart writers after
    the command to clear memory caches. Prices rebuild on demand.

Usage::

    BROWNIE_NETWORK_ID=mainnet ypricemagic db reset-prices --chain 1 --backup /path/to/backup.sqlite

The command uses ``YPRICEMAGIC_SQLITE_PATH`` when set, or the default database at
``~/.ypricemagic/ypricemagic.sqlite``. It does not stop or restart other processes.

Historical price audit
----------------------

``ypricemagic audit-prices MANIFEST --json REPORT.json --csv REPORT.csv``
compares historical public prices against DeFiLlama with a 5% spot tolerance.
See :doc:`amount-quotes` for the manifest, coverage rules, and exit codes.
