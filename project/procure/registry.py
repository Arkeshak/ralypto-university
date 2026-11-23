"""Plug-in agent and tool registry (Proposal Section 4 & 10).

Enables adding, inspecting, or overriding agent functions and tools dynamically
without modifying the core orchestrator or pipeline.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class AgentRegistry:
    """Registry for specialized procurement agents."""

    def __init__(self):
        self._agents: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register an agent function under a specific name."""
        self._agents[name] = fn
        return fn

    def register_agent(self, name: str):
        """Decorator to register an agent."""
        def decorator(fn: Callable[..., Any]):
            self.register(name, fn)
            return fn
        return decorator

    def get(self, name: str) -> Optional[Callable[..., Any]]:
        """Retrieve an agent function by name."""
        return self._agents.get(name)

    def list_agents(self) -> Dict[str, str]:
        """List all registered agents and their docstrings."""
        return {
            name: (fn.__doc__ or "").strip().split("\n")[0]
            for name, fn in self._agents.items()
        }

    def copy(self) -> AgentRegistry:
        """Create a shallow copy of the registry for scoped modifications."""
        clone = AgentRegistry()
        clone._agents = dict(self._agents)
        return clone


class ToolRegistry:
    """Registry for query tools and helper utilities."""

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

    def list_tools(self) -> Dict[str, str]:
        return {
            name: (fn.__doc__ or "").strip().split("\n")[0]
            for name, fn in self._tools.items()
        }


# Global default registries
default_registry = AgentRegistry()
default_tool_registry = ToolRegistry()


def init_default_registry():
    """Populate default registry with core agents."""
    from . import agents as A
    from .query import ask

    default_registry.register("stock_monitor", A.stock_monitor)
    default_registry.register("forecaster", A.forecaster)
    default_registry.register("supplier_ranker", A.supplier_ranker)
    default_registry.register("po_drafter", A.po_drafter)
    default_registry.register("po_reviser", A.po_reviser)
    default_registry.register("validator", A.validator)

    default_tool_registry.register("ask", ask)


init_default_registry()
