"""Teach the upstream async plugin about inherited project metaclasses.

ASyncMeta wraps methods on every subclass, including subclasses which inherit
rather than explicitly declare their metaclass. Keep the upstream descriptor
model so argument and return checking remain enabled.
"""

from collections.abc import Callable
from functools import partial
from typing import cast

from a_sync_mypy_plugin import (
    ASYNC_BASE_FULLNAMES,
    ASYNC_FUNCTION_FULLNAMES,
    CACHED_PROPERTY_DECORATOR_FULLNAMES,
    PROPERTY_DECORATOR_FULLNAMES,
    ASyncPlugin,
    _a_sync_function_hook,
    _analyzed_callable_from_node,
    _get_fullname,
    _is_async_return_type,
    _parameters_from_callable,
    _unwrap_awaitable,
)
from a_sync_mypy_plugin import _wrap_async_class as _upstream_wrap_async_class
from mypy.nodes import (
    ARG_NAMED,
    ARG_NAMED_OPT,
    COVARIANT,
    CallExpr,
    Decorator,
    FuncDef,
    NameExpr,
    TypeInfo,
    Var,
)
from mypy.plugin import (
    ClassDefContext,
    FunctionContext,
    FunctionSigContext,
    MethodContext,
    MethodSigContext,
    Plugin,
)
from mypy.types import (
    AnyType,
    CallableType,
    Instance,
    LiteralType,
    NoneType,
    Overloaded,
    Parameters,
    Type,
    TypeOfAny,
    TypeVarType,
    UnionType,
    get_proper_type,
)


def _wrap_async_class(ctx: ClassDefContext) -> None:
    # Descriptor installation needs the late class hook: replacing methods
    # during semantic analysis collides with deferred analysis of their bodies.
    # This synthetic marker is removed by that hook before type checking.
    metadata = ctx.cls.info.metadata.setdefault("y.async", {})
    if metadata.get("scheduled"):
        return
    marker = NameExpr("object")
    marker.node = ctx.api.lookup_fully_qualified("builtins.object").node
    marker.fullname = "builtins.object"
    ctx.cls.decorators.append(marker)
    metadata["scheduled"] = True


def _wrap_async_class_late(ctx: ClassDefContext) -> bool:
    metadata = ctx.cls.info.metadata.get("y.async", {})
    if not metadata.get("scheduled"):
        return True
    body = ctx.cls.defs.body
    ctx.cls.defs.body = [
        statement
        for statement in body
        if not (
            isinstance(statement, Decorator)
            and (
                statement.func.is_property
                or statement.var.is_property
                or any(
                    _get_fullname(decorator) == "y._typing.a_sync_property"
                    for decorator in statement.decorators
                )
            )
        )
    ]
    try:
        _upstream_wrap_async_class(ctx)
        for statement in body:
            fn = statement.func if isinstance(statement, Decorator) else statement
            if not isinstance(fn, FuncDef) or not fn.is_async_generator:
                continue
            signature = _analyzed_callable_from_node(ctx, fn)
            method_symbol = ctx.cls.info.names.get(fn.name)
            if (
                signature is not None
                and method_symbol is not None
                and isinstance(method_symbol.node, Var)
            ):
                typ = get_proper_type(method_symbol.node.type)
                if (
                    isinstance(typ, Instance)
                    and typ.type.fullname == "a_sync.iter.ASyncGeneratorFunction"
                ):
                    # Class access retains self; __get__ removes it on binding.
                    method_symbol.node.type = typ.copy_modified(
                        args=[
                            _parameters_from_callable(signature, drop_first=False),
                            typ.args[1],
                        ]
                    )
        for symbol in ctx.cls.info.names.values():
            if symbol.plugin_generated and isinstance(symbol.node, Var):
                typ = get_proper_type(symbol.node.type)
                if isinstance(typ, Instance) and typ.type.fullname.startswith(
                    "a_sync.a_sync.method.ASyncMethodDescriptor"
                ):
                    # These descriptors reject instance assignment. Model the
                    # bound callable as read-only, allowing return covariance.
                    symbol.node.is_property = True
                    symbol.node.is_settable_property = False
                if (
                    isinstance(typ, Instance)
                    and typ.type.fullname.endswith(".HiddenMethodDescriptor")
                    and len(typ.args) == 3
                ):
                    symbol.node.type = typ.copy_modified(args=[typ.args[0], typ.args[2]])
    finally:
        ctx.cls.defs.body = body
    ctx.cls.decorators.remove(ctx.reason)
    return True


def _dual_signature(ctx: FunctionSigContext | MethodSigContext) -> CallableType:
    """Model the flags added at runtime to an overloaded coroutine function."""
    signature = ctx.default_signature
    mode: bool | None = True
    if isinstance(ctx.context, CallExpr):
        if "sync" in ctx.context.arg_names and "asynchronous" in ctx.context.arg_names:
            ctx.api.fail("Use only one execution mode flag", ctx.context)
        for name, value in zip(ctx.context.arg_names, ctx.context.args):
            if name not in ("sync", "asynchronous"):
                continue
            typ = get_proper_type(ctx.api.get_expression_type(value))
            literal = typ.last_known_value if isinstance(typ, Instance) else typ
            if isinstance(literal, LiteralType) and isinstance(literal.value, bool):
                mode = literal.value if name == "sync" else not literal.value
            else:
                mode = None
    value_type = _unwrap_awaitable(signature.ret_type)
    any_type = AnyType(TypeOfAny.special_form)
    asynchronous = ctx.api.named_generic_type("typing.Coroutine", [any_type, any_type, value_type])
    returned = (
        value_type
        if mode is True
        else (asynchronous if mode is False else UnionType.make_union([value_type, asynchronous]))
    )
    flag = ctx.api.named_generic_type("builtins.bool", [])
    return signature.copy_modified(
        arg_types=[*signature.arg_types, flag, flag],
        arg_kinds=[*signature.arg_kinds, ARG_NAMED_OPT, ARG_NAMED_OPT],
        arg_names=[*signature.arg_names, "sync", "asynchronous"],
        ret_type=returned,
    )


def _function_hook(ctx: FunctionContext) -> Type:
    if ctx.arg_types and ctx.arg_types[0]:
        function = get_proper_type(ctx.arg_types[0][0])
        if (
            isinstance(function, CallableType)
            and isinstance(function.definition, FuncDef)
            and function.definition.is_class
        ):
            # classmethod performs the binding; retain its cls parameter and
            # Self result instead of returning an unbound function instance.
            return function
    return _a_sync_function_hook(ctx)


def _stuck_signature(ctx: MethodSigContext) -> CallableType:
    if not ctx.args or not ctx.args[0]:
        return ctx.default_signature
    function = get_proper_type(ctx.api.get_expression_type(ctx.args[0][0]))
    if not isinstance(function, Instance) or not function.type.has_base(
        "a_sync.a_sync.function.ASyncFunction"
    ):
        return ctx.default_signature
    parameters = get_proper_type(function.args[0])
    if not isinstance(parameters, Parameters):
        return ctx.default_signature
    any_type = AnyType(TypeOfAny.special_form)
    returned = ctx.api.named_generic_type(
        "typing.Coroutine", [any_type, any_type, function.args[1]]
    )
    wrapper = CallableType(
        [
            *parameters.arg_types,
            LiteralType(False, ctx.api.named_generic_type("builtins.bool", [])),
        ],
        [
            *parameters.arg_kinds,
            ARG_NAMED_OPT if function.type.fullname.endswith("AsyncDefault") else ARG_NAMED,
        ],
        [*parameters.arg_names, "sync"],
        returned,
        ctx.api.named_generic_type("builtins.function", []),
        variables=list(parameters.variables),
    )
    async_wrapper = wrapper.copy_modified(
        arg_types=[
            *parameters.arg_types,
            LiteralType(True, ctx.api.named_generic_type("builtins.bool", [])),
        ],
        arg_kinds=[*parameters.arg_kinds, ARG_NAMED],
        arg_names=[*parameters.arg_names, "asynchronous"],
    )
    return ctx.default_signature.copy_modified(
        arg_types=[function], ret_type=Overloaded([wrapper, async_wrapper]), variables=[]
    )


def _decorator_signature(
    ctx: MethodSigContext,
    function_type: TypeInfo,
    async_type: TypeInfo,
    sync_type: TypeInfo,
) -> CallableType:
    """Resolve the coroutine/sync union before inferring its ParamSpec."""
    if not ctx.args or not ctx.args[0]:
        return ctx.default_signature
    function = get_proper_type(ctx.api.get_expression_type(ctx.args[0][0]))
    if not isinstance(function, CallableType):
        return ctx.default_signature
    if function_type.fullname == "a_sync.a_sync.function.ASyncFunction":
        function_type = async_type if _is_async_return_type(function) else sync_type
    result = Instance(
        function_type,
        [
            function.param_spec() or _parameters_from_callable(function, drop_first=False),
            _unwrap_awaitable(function.ret_type),
        ],
    )
    return ctx.default_signature.copy_modified(arg_types=[function], ret_type=result, variables=[])


def _property_signature(ctx: FunctionSigContext, descriptor: TypeInfo) -> CallableType:
    if not ctx.args or not ctx.args[0]:
        return ctx.default_signature
    function = get_proper_type(ctx.api.get_expression_type(ctx.args[0][0]))
    if not isinstance(function, CallableType) or not function.arg_types:
        return ctx.default_signature
    result = Instance(descriptor, [function.arg_types[0], _unwrap_awaitable(function.ret_type)])
    return ctx.default_signature.copy_modified(
        arg_types=[function, *ctx.default_signature.arg_types[1:]],
        ret_type=result,
        variables=[],
    )


def _queue_signature(ctx: FunctionSigContext) -> CallableType:
    if not ctx.args or not ctx.args[0]:
        return ctx.default_signature
    function = get_proper_type(ctx.api.get_expression_type(ctx.args[0][0]))
    result = get_proper_type(ctx.default_signature.ret_type)
    if (
        isinstance(function, Instance)
        and function.type.fullname == "a_sync.a_sync.function.ASyncFunctionAsyncDefault"
        and isinstance(result, Instance)
    ):
        return ctx.default_signature.copy_modified(
            arg_types=[function, *ctx.default_signature.arg_types[1:]],
            ret_type=result.copy_modified(args=function.args),
            variables=[],
        )
    return ctx.default_signature


def _method_descriptor_hook(ctx: FunctionContext) -> Type:
    if not ctx.arg_types or not ctx.arg_types[0]:
        return ctx.default_return_type
    function = get_proper_type(ctx.arg_types[0][0])
    result = get_proper_type(ctx.default_return_type)
    if isinstance(function, CallableType) and function.arg_types and isinstance(result, Instance):
        return result.copy_modified(
            args=[
                function.arg_types[0],
                _parameters_from_callable(function, drop_first=True),
                _unwrap_awaitable(function.ret_type),
            ]
        )
    return ctx.default_return_type


def _generator_binding_hook(ctx: MethodContext) -> Type:
    result = get_proper_type(ctx.default_return_type)
    if not isinstance(result, Instance) or not ctx.arg_types or not ctx.arg_types[0]:
        return ctx.default_return_type
    if isinstance(get_proper_type(ctx.arg_types[0][0]), NoneType):
        return result
    parameters = get_proper_type(result.args[0])
    if isinstance(parameters, Parameters) and parameters.arg_names[:1] == ["self"]:
        return result.copy_modified(
            args=[
                Parameters(
                    parameters.arg_types[1:],
                    parameters.arg_kinds[1:],
                    parameters.arg_names[1:],
                    variables=list(parameters.variables),
                ),
                result.args[1],
            ]
        )
    return result


def _method_binding_hook(ctx: MethodContext) -> Type:
    """A bound descriptor owns the actual instance, including subclasses."""
    result = get_proper_type(ctx.default_return_type)
    if isinstance(result, Instance) and ctx.arg_types and ctx.arg_types[0]:
        owner = get_proper_type(ctx.arg_types[0][0])
        if isinstance(owner, Instance) and len(result.args) in (2, 3):
            # The callable result is covariant; the upstream shared T is
            # invariant. Copy the class parameter so unrelated T uses stay intact.
            parameter = result.type.defn.type_vars[-1]
            if isinstance(parameter, TypeVarType) and parameter.variance != COVARIANT:
                parameter = parameter.copy_modified()
                parameter.variance = COVARIANT
                result.type.defn.type_vars[-1] = parameter
            return result.copy_modified(args=[owner, *result.args[1:]])
    return ctx.default_return_type


def _bound_call_signature(ctx: MethodSigContext) -> CallableType:
    """Retain ParamSpec arguments on the dependency's flag-bearing overloads."""
    instance = get_proper_type(ctx.type)
    if not isinstance(instance, Instance) or len(instance.args) != 3:
        return ctx.default_signature
    parameters = get_proper_type(instance.args[1])
    if not isinstance(parameters, Parameters):
        return ctx.default_signature
    signature = ctx.default_signature
    flags = [i for i, name in enumerate(signature.arg_names) if name in ("sync", "asynchronous")]
    return signature.copy_modified(
        arg_types=[*parameters.arg_types, *(signature.arg_types[i] for i in flags)],
        arg_kinds=[*parameters.arg_kinds, *(signature.arg_kinds[i] for i in flags)],
        arg_names=[*parameters.arg_names, *(signature.arg_names[i] for i in flags)],
        variables=list(parameters.variables),
    )


def _test_result_signature(ctx: FunctionSigContext, asynchronous: bool) -> CallableType:
    # Test instance-selected execution modes without changing those modes.
    # Infer before considering the generic union so Coroutine[T] cannot also
    # become T, producing a nested Coroutine result.
    if not ctx.args or not ctx.args[0]:
        return ctx.default_signature
    argument = ctx.api.get_expression_type(ctx.args[0][0])
    proper = get_proper_type(argument)
    members = proper.items if isinstance(proper, UnionType) else [argument]
    result = UnionType.make_union([_unwrap_awaitable(member) for member in members])
    if asynchronous:
        result = ctx.api.named_generic_type("typing.Awaitable", [result])
    return ctx.default_signature.copy_modified(arg_types=[argument], ret_type=result, variables=[])


class YPriceMagicPlugin(ASyncPlugin):
    def get_class_decorator_hook_2(self, fullname: str) -> Callable[[ClassDefContext], bool] | None:
        return _wrap_async_class_late if fullname == "builtins.object" else None

    def get_function_hook(self, fullname: str) -> Callable[[FunctionContext], Type] | None:
        if fullname in ASYNC_FUNCTION_FULLNAMES:
            return _function_hook
        if fullname in {
            "a_sync.a_sync.method.ASyncMethodDescriptor",
            "a_sync.a_sync.method.ASyncMethodDescriptorSyncDefault",
            "a_sync.a_sync.method.ASyncMethodDescriptorAsyncDefault",
        }:
            return _method_descriptor_hook
        return cast(Callable[[FunctionContext], Type] | None, super().get_function_hook(fullname))

    def get_function_signature_hook(
        self, fullname: str
    ) -> Callable[[FunctionSigContext], CallableType] | None:
        if fullname in {"tests.fixtures.async_result", "tests.fixtures.sync_result"}:
            return partial(_test_result_signature, asynchronous=fullname.endswith("async_result"))
        if fullname in {
            "a_sync.primitives.queue.ProcessingQueue",
            "a_sync.primitives.queue.SmartProcessingQueue",
        }:
            return _queue_signature
        if fullname in PROPERTY_DECORATOR_FULLNAMES | CACHED_PROPERTY_DECORATOR_FULLNAMES:
            kind = (
                "CachedProperty" if fullname in CACHED_PROPERTY_DECORATOR_FULLNAMES else "Property"
            )
            symbol = self.lookup_fully_qualified(f"a_sync.a_sync.property.ASync{kind}Descriptor")
            if symbol is not None and isinstance(symbol.node, TypeInfo):
                return partial(_property_signature, descriptor=symbol.node)
        if fullname in {
            "y.prices.magic.get_price",
            "y.prices.magic.get_prices",
            "y.contracts.has_method",
            "y.contracts.build_name",
            "y.utils._erc20.decimals",
            "y.utils._erc20.totalSupply",
            "y.utils.raw_calls.decimals",
            "y.utils.raw_calls.raw_call",
            "y.utils.raw_calls._decimals",
            "y.utils.raw_calls._totalSupply",
            "y.utils.raw_calls.balanceOf",
        }:
            return _dual_signature
        return None

    def get_metaclass_hook(self, fullname: str) -> Callable[[ClassDefContext], None] | None:
        if fullname == "y.classes.singleton.ChecksumASyncSingletonMeta":
            return _wrap_async_class
        if super().get_metaclass_hook(fullname) is not None:
            return _wrap_async_class
        return None

    def get_base_class_hook(self, fullname: str) -> Callable[[ClassDefContext], None] | None:
        symbol = self.lookup_fully_qualified(fullname)
        if symbol is not None and isinstance(symbol.node, TypeInfo):
            if any(base.fullname in ASYNC_BASE_FULLNAMES for base in symbol.node.mro):
                return _wrap_async_class
        return None

    def get_method_hook(self, fullname: str) -> Callable[[MethodContext], Type] | None:
        if fullname == "a_sync.task.TaskMapping.items":
            symbol = self.lookup_fully_qualified("a_sync.task.TaskMappingItems")
            if symbol is not None and isinstance(symbol.node, TypeInfo):
                item_type = symbol.node

                def items(ctx: MethodContext) -> Type:
                    instance = get_proper_type(ctx.type)
                    return (
                        Instance(item_type, list(instance.args))
                        if isinstance(instance, Instance)
                        else ctx.default_return_type
                    )

                return items
        if fullname == "a_sync.iter.ASyncGeneratorFunction.__get__":
            return _generator_binding_hook
        if fullname in {
            "a_sync.a_sync.method.ASyncMethodDescriptor.__get__",
            "a_sync.a_sync.method.ASyncMethodDescriptorSyncDefault.__get__",
            "a_sync.a_sync.method.ASyncMethodDescriptorAsyncDefault.__get__",
            "a_sync.a_sync.property.HiddenMethodDescriptor.__get__",
        }:
            return _method_binding_hook
        return cast(Callable[[MethodContext], Type] | None, super().get_method_hook(fullname))

    def get_method_signature_hook(
        self, fullname: str
    ) -> Callable[[MethodSigContext], CallableType] | None:
        if fullname in {
            "a_sync.a_sync.method.ASyncBoundMethod.__call__",
            "a_sync.a_sync.method.ASyncBoundMethodSyncDefault.__call__",
            "a_sync.a_sync.method.ASyncBoundMethodAsyncDefault.__call__",
        }:
            return _bound_call_signature
        if fullname == "y._decorators._StuckDebugger.__call__":
            return _stuck_signature
        if fullname == "y.contracts.Contract.from_abi":
            return _dual_signature
        for default in ("SyncDefault", "AsyncDefault", ""):
            if fullname == f"a_sync.a_sync.function.ASyncDecorator{default}.__call__":
                symbol = self.lookup_fully_qualified(
                    f"a_sync.a_sync.function.ASyncFunction{default}"
                )
                if symbol is not None and isinstance(symbol.node, TypeInfo):
                    async_symbol = self.lookup_fully_qualified(
                        "a_sync.a_sync.function.ASyncFunctionAsyncDefault"
                    )
                    sync_symbol = self.lookup_fully_qualified(
                        "a_sync.a_sync.function.ASyncFunctionSyncDefault"
                    )
                    if (
                        async_symbol is not None
                        and isinstance(async_symbol.node, TypeInfo)
                        and sync_symbol is not None
                        and isinstance(sync_symbol.node, TypeInfo)
                    ):
                        return partial(
                            _decorator_signature,
                            function_type=symbol.node,
                            async_type=async_symbol.node,
                            sync_type=sync_symbol.node,
                        )
        return None


def plugin(version: str) -> type[Plugin]:
    return YPriceMagicPlugin
