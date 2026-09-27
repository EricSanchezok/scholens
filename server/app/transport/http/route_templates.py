"""Canonical labels from registered route contexts, never request identifiers."""

from collections.abc import Sequence
from re import Pattern

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from starlette.routing import BaseRoute, compile_path
from starlette.types import Scope


class _RouteTemplates:
    def __init__(self, routes: Sequence[BaseRoute]) -> None:
        self.labels: dict[int, list[tuple[Pattern[str], str]]] = {}
        for context in iter_route_contexts(routes):
            if context.path is None:
                continue
            pattern, label, _converters = compile_path(context.path)
            self.labels.setdefault(id(context.original_route), []).append(
                (pattern, label)
            )


def matched_route_template(scope: Scope) -> str | None:
    application, route = scope.get("app"), scope.get("route")
    if not isinstance(application, FastAPI) or route is None:
        return None
    # Application composition finishes before serving. Cache only immutable
    # registered patterns, scoped to that application's lifetime, never actors
    # or request paths. An included router can have more than one public prefix.
    catalog = getattr(application.state, "_http_route_templates", None)
    if not isinstance(catalog, _RouteTemplates):
        catalog = _RouteTemplates(application.routes)
        application.state._http_route_templates = catalog
    path = str(scope.get("path", ""))
    root = str(scope.get("root_path", "")).rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        path = path[len(root) :] or "/"
    for pattern, label in catalog.labels.get(id(route), ()):
        if pattern.fullmatch(path):
            return label
    return None
