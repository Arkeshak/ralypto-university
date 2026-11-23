"""Plug-in agent and tool registry (Proposal Sections 4 and 10).

Three ways to extend the system without touching the orchestrator:

1. Replace a core agent:   registry.register("forecaster", my_forecaster)
2. Add an extension agent:  registry.register_extension("carbon_check", fn, stage="validator")
   fn(env, draft, forecast, requester) -> Validation | None ; failures veto the PO, warnings are shown.
3. Add a tool:              tool_registry.register("fx_rate", fn) ; call with tool_registry.call("fx_rate", ...)

See docs/EXTENDING.md for a worked example.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

CORE_AGENTS = ["stock_monitor", "forecaster", "supplier_ranker", "po_drafter", "po_reviser", "validator"]


class AgentRegistry:
    """Registry for specialised procurement agents."""

    def __init__(self):
        self._agents: Dict[str, Callable[..., Any]] = {}
        self._ext: Dict[str, Tuple[str, Callable[..., Any]]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register (or replace) an agent function under a name."""
        self._agents[name] = fn
        return fn

    def register_agent(self, name: str):
        """Decorator form of register()."""
        def decorator(fn: Callable[..., Any]):
            self.register(name, fn)
            return fn
        return decorator

    def register_extension(self, name: str, fn: Callable[..., Any], stage: str = "validator") -> Callable[..., Any]:
        """Add a new agent that runs at a pipeline stage (currently: 'validator')."""
        if stage != "validator":
            raise ValueError("supported stages: validator")
        self._ext[name] = (stage, fn)
        return fn

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)
        self._ext.pop(name, None)

    def extensions(self, stage: str) -> List[Tuple[str, Callable[..., Any]]]:
        return [(n, fn) for n, (s, fn) in self._ext.items() if s == stage]

    def get(self, name: str) -> Optional[Callable[..., Any]]:
        return self._agents.get(name)

    def list_agents(self) -> Dict[str, str]:
        """Name -> first docstring line, core agents and extensions."""
        out = {name: (fn.__doc__ or "").strip().split("\n")[0] for name, fn in self._agents.items()}
        out.update({f"{n} (extension @ {s})": (fn.__doc__ or "").strip().split("\n")[0] for n, (s, fn) in self._ext.items()})
        return out

    def copy(self) -> "AgentRegistry":
        """Shallow copy for scoped modifications (e.g. one benchmark variant)."""
        clone = AgentRegistry()
        clone._agents = dict(self._agents)
        clone._ext = dict(self._ext)
        return clone


class ToolRegistry:
    """Registry for read-only tools that agents (and the single-agent baseline) may call."""

    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        self._tools[name] = fn
        return fn

    def register_tool(self, name: str):
        def decorator(fn: Callable[..., Any]):
            self.register(name, fn)
            return fn
        return decorator

    def get(self, name: str) -> Optional[Callable[..., Any]]:
        return self._tools.get(name)

    def call(self, name: str, *args, **kwargs):
        fn = self.get(name)
        if fn is None:
            raise KeyError(f"unknown tool {name}")
        return fn(*args, **kwargs)

    def list_tools(self) -> Dict[str, str]:
        return {name: (fn.__doc__ or "").strip().split("\n")[0] for name, fn in self._tools.items()}


default_registry = AgentRegistry()
default_tool_registry = ToolRegistry()


def init_default_registry():
    """Populate the default registries with the core agents and tools."""
    from . import agents as A
    from . import forecasting as F
    from .query import ask, check_sql

    def reorder_point_policy(env, sku):
        """Deterministic reorder-point policy (rule-based floor and fallback)."""
        from .orchestrator import reorder_point_policy as rop  # lazy: orchestrator imports this module
        return rop(env, sku)

    for n in CORE_AGENTS:
        default_registry.register(n, getattr(A, n))
    default_registry.register("query_agent", ask)

    default_tool_registry.register("ask", ask)
    default_tool_registry.register("check_sql", check_sql)
    default_tool_registry.register("seasonal_ses", F.seasonal_ses)
    default_tool_registry.register("ets", F.ets)
    default_tool_registry.register("reorder_point_policy", reorder_point_policy)
    default_tool_registry.register("usable_stock", A._usable_stock)


init_default_registry()
