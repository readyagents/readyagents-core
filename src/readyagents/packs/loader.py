"""Load installed packs via importlib.metadata entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from readyagents.errors import ConfigError
from readyagents.logging import get_logger
from readyagents.packs.protocol import Pack
from readyagents.tools import ToolRegistry

log = get_logger("packs")

ENTRY_POINT_GROUP = "readyagents.packs"


def discover_packs() -> list[Pack]:
    """Load every installed pack. Core runs fine with an empty list."""
    packs: list[Pack] = []
    selected = entry_points().select(group=ENTRY_POINT_GROUP)
    for ep in selected:
        try:
            loaded = ep.load()
            pack = loaded() if callable(loaded) and not _is_pack_instance(loaded) else loaded
            if not _is_pack_instance(pack):
                raise ConfigError(
                    f"Entry point '{ep.name}' did not return a Pack (name/version/register_*)"
                )
            packs.append(pack)
            log.debug("Loaded pack %s %s", pack.name, pack.version)
        except ConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConfigError(f"Failed to load pack '{ep.name}': {exc}") from exc
    return packs


def _is_pack_instance(obj: Any) -> bool:
    return (
        hasattr(obj, "name")
        and hasattr(obj, "version")
        and callable(getattr(obj, "register_nodes", None))
        and callable(getattr(obj, "register_tools", None))
        and callable(getattr(obj, "register_workflows", None))
    )


def collect_pack_tools(packs: list[Pack] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    for pack in packs if packs is not None else discover_packs():
        for tool in pack.register_tools() or []:
            registry.register(tool)
    return registry


def collect_pack_nodes(packs: list[Pack] | None = None) -> dict[str, Any]:
    handlers: dict[str, Any] = {}
    for pack in packs if packs is not None else discover_packs():
        for type_name, handler in (pack.register_nodes() or {}).items():
            handlers[type_name] = handler
    return handlers


def collect_pack_secrets(packs: list[Pack] | None = None) -> list[Any]:
    backends: list[Any] = []
    for pack in packs if packs is not None else discover_packs():
        fn = getattr(pack, "register_secrets", None)
        if not callable(fn):
            continue
        backends.extend(list(fn() or []))
    return backends


def collect_pack_authorizers(packs: list[Pack] | None = None) -> list[Any]:
    authorizers: list[Any] = []
    for pack in packs if packs is not None else discover_packs():
        fn = getattr(pack, "register_authorizers", None)
        if not callable(fn):
            continue
        authorizers.extend(list(fn() or []))
    return authorizers
