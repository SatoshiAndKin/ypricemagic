Liquidity-based price estimation
===============================

Python 3.11, 3.12, and 3.13 are supported. Local validation uses Python 3.12.

``get_price(token, block, amount=1000)`` estimates the value of selling 1,000
readable tokens. ``ERC20(token).price(block, amount=Decimal("1.25"))`` accepts
the same keyword. ``get_prices(tokens, block, amounts=[1, 2])`` preserves input
order, including duplicate tokens with different amounts. Use integers or
``Decimal``. Floats, nonpositive or nonfinite amounts, and values that do not
fit exactly in the token's base units are errors. Batch lengths are checked
before RPC work.

``PriceResult.price`` remains USD per input token. Amount requests also return
``PriceResult.quote``. It contains the exact input, final output assets and
integer amounts, total USD value, block number and hash, and ordered swap and
redemption steps. Each quantity includes decimals and an exact ``readable``
property. Holder eligibility is always ``unverified``. This is an estimate,
not a transaction or a guarantee that an unknown holder can execute an exit.

Route selection
---------------

The router ranks each available pool by its balance of the current input token.
Balances use that token's base units. Protocol name and pool address resolve
ties. The router tries the deepest pool first. It tries a lower-ranked pool if
a native quote fails or the route reaches a dead end. Each directed edge can
be tried only once in a route request. The router does not build path lists or
try every combination. It permits eleven swaps and retains validated explicit
protocol routes. It prevents token cycles and pool reuse.

Subsequent swaps can use another supported DEX. The router sends the full amount
through each step. It does not split an amount among competing routes. This
liquidity rule does not guarantee the highest price among all possible routes.

Native V2 and Solidly router quotes, V3 quoters, Curve ``get_dy``, Balancer V1
``calcOutGivenIn``, and Balancer V2 ``queryBatchSwap`` retain DEX fees and price
impact. Balancer V1 discovery retains the existing proxy's candidate universe;
the estimate selects one pool and does not use the proxy's split allocation.
The router values terminal stablecoins and native assets with historical USD
feeds. A stablecoin classification, including one read from the database, does
not assign a fixed $1 price. Calls without an amount retain API, oracle, and
wrapper valuation priority. DEX fallback estimates one readable token.

Immediate redemption support
----------------------------

* ERC4626: ``previewRedeem`` receives the full share amount and includes
  withdrawal fees. A failed preview is unavailable. ``convertToAssets`` is
  never a sale-quote fallback. Previews exclude global and holder limits;
  ``maxRedeem`` and holder eligibility remain unverified.
* Yearn V2 API 0.4.3 through 0.4.6: the exact share-value calculation includes
  remaining locked profit. An exit is available only when idle assets cover
  the full output. These exits have no withdrawal fee. Strategy withdrawals
  can realize losses and are unavailable without a reliable model.
* Configured Aave V2/V3 markets: underlying output is one-for-one. The adapter
  checks cash, active-reserve status, and pause status. There is no withdrawal
  fee. Collateral, account balance, and holder eligibility remain unverified.
* Canonical mainnet Compound V2 cTokens: ``exchangeRateCurrent`` includes accrued interest. The
  adapter uses integer redemption arithmetic and checks ``getCash``. There is
  no Compound V2 redemption fee. Comptroller and holder eligibility remain
  unverified.
* Wrapped native assets and mainnet Lido wstETH: immediate one-for-one native
  conversion or ``getStETHByWstETH`` determines the output. These conversions
  have no withdrawal fee. wstETH returns stETH, not an immediate ETH exit.
* Verified Curve LiquidityGauge contracts: a fungible receipt returns its LP
  token one-for-one, with no fee. The adapter checks LP backing. Mainnet Convex
  Booster V1 deposit receipts return their underlying LP after a historical
  pool match and backing check. Staked reward contracts and delayed exits are
  unavailable.
* Mainnet Uniswap/Sushi V2 LP tokens: integer burn arithmetic uses current
  balances and includes protocol-fee supply dilution. Both outputs must receive
  a valuation. Other V2 LP contract variants are unavailable.
* Curve LP tokens with ``calc_withdraw_one_coin``: the native quote includes
  withdrawal imbalance fees. The adapter checks LP supply and tries output
  coins in address order.
* Balancer V2 Weighted, Stable, and ComposableStable pool LP tokens: a native
  proportional ``queryExit`` includes fees and checks the returned BPT input.
  Other pool versions without this contract remain unavailable.

If both direct sale and redemption succeed, the estimate uses the better total
USD value. It aggregates identical redemption outputs and processes them in
address order. It carries used-pool exclusions across all output valuations and
excludes pools changed by an LP withdrawal. Every nonzero output needs a value.
Accounting NAV is never a replacement for an unavailable amount-aware exit.

Caching and diagnostics
-----------------------

The bounded in-memory result cache includes the exact amount, valuation mode,
chain, block hash, exclusions, and dependency context. Identical requests share
in-flight work. Cancelling one caller does not cancel another caller's work.
The last cancelled caller drains the owned task. Returned price paths are
copies. Amount results never enter the numeric spot-price database.

Immutable pool snapshots and amount-independent reads use separate bounded
caches keyed by chain and block hash. ``skip_cache=True`` bypasses final price
caches, while fixed-block pool discovery and state remain shared. Discovery
and liquidity reads use at most 64 workers per request. No selection deadline
is added. Quote state and native calls use EIP-1898 block-hash identifiers with
``requireCanonical=True``. Batches retain that hash, and the result checks that
the block remains canonical before it returns. A rejected call cannot cache
another block's state under the requested hash.

Enable ``logging.getLogger("y.stuck?").setLevel(logging.DEBUG)`` for
``still executing`` messages every five minutes. These messages are DEBUG-only.

Historical audit
----------------

Run the public pricing functions against the mainnet manifest::

    BROWNIE_NETWORK_ID=mainnet ypricemagic audit-prices audits/mainnet.json \
        --json audit-results/mainnet.json --csv audit-results/mainnet.csv

Use a separate database with ``YPRICEMAGIC_SQLITE_PATH`` when testing. The
manifest selects the Brownie network, complete token addresses, explicit block
numbers or UTC timestamps, and optional readable ``amounts``. ``quarterly``
adds quarter ends from 2021 through the archive node's latest completed quarter.
``boundaries`` adds token deployment and Chainlink registry feed boundaries.
``usd_amounts`` uses reference prices only to size audit inputs.

Timestamps resolve to the last block at or before the requested time. Reports
retain its number and hash. DeFiLlama references must be positive and finite,
have confidence of at least 0.9, and be within one hour of the block timestamp.
Stress samples use fifteen minutes. Spot deviation is
``abs(yprice / reference - 1)`` and must be at most 5%. Sale impact is separate.
No production price depends on DeFiLlama, and no result is clamped to a reference.

JSON and CSV reports preserve addresses, amounts, quote paths, reference age,
failures, elapsed time, logical RPC calls, and generated RPC batch counts. The
RPC counters are process-wide; audit samples run sequentially. They do not
claim to measure transport retries. Exit code 0 means required comparisons
passed, 1 means a price/quote comparison failed, and 2 means coverage is
incomplete. Reports retain unavailable and stale samples.

Native contracts:
`ERC4626 <https://eips.ethereum.org/EIPS/eip-4626>`_,
`Balancer batch swaps <https://github.com/balancer/docs-developers/blob/main/resources/swaps/batch-swaps.md>`_,
`Yearn V2 <https://github.com/yearn/yearn-vaults/blob/v0.4.6/contracts/Vault.vy>`_,
`DeFiLlama historical API <https://api-docs.defillama.com/llms-free.txt>`_.
