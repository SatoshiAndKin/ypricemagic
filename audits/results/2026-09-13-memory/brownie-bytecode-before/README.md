# Native bytecode buffer retention

Sixteen scans of the same 17,408-byte input retain 4,464,096 bytes in 8,176
intermediate byte buffers. Python's cyclic collector does not release them.
Each scan returns the expected opcodes. This diagnostic imports the installed
native Brownie caching extension and uses no RPC calls.

The compiler primitive incorrectly declares that `CPyBytes_Concat` steals its
first argument. The native runtime does not release it, and generated callers
omit that release. The upstream repair is
[python/mypy PR 21469](https://github.com/python/mypy/pull/21469).
Compiler 2.2.0 and 2.3.1 contain this fix, but their Brownie builds fail to import
with `Plain typing.NotRequired is not valid as type argument`. The next controlled
check uses the exact upstream ownership fix on compiler 1.19.1.
