"""Validated tool definitions and independently selectable profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.tooling.contracts import (
    ToolAccess,
    ToolDefinition,
)

CapabilitiesT = TypeVar("CapabilitiesT")


def _undocumented_input_properties(schema: dict[str, object]) -> list[str]:
    """Find undocumented parameters at every nested JSON-schema object boundary."""
    missing: set[str] = set()

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, path)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            for name, property_schema in properties.items():
                if (
                    isinstance(name, str)
                    and isinstance(property_schema, dict)
                    and not property_schema.get("description")
                ):
                    missing.add(".".join((*path, name)))
                visit(property_schema, (*path, str(name)))
        definitions = value.get("$defs")
        if isinstance(definitions, dict):
            for name, definition_schema in definitions.items():
                visit(definition_schema, (*path, f"$defs.{name}"))
        for key in ("allOf", "anyOf", "oneOf", "items"):
            visit(value.get(key), path)

    visit(schema, ())
    return sorted(missing)


@dataclass(frozen=True, slots=True)
class ToolProfile:
    name: str
    tool_names: frozenset[str]


class ToolCatalog(Generic[CapabilitiesT]):
    def __init__(
        self,
        definitions: list[ToolDefinition[CapabilitiesT]],
        profiles: list[ToolProfile],
        *,
        require_agent_metadata: bool = False,
    ) -> None:
        self._definitions: dict[str, ToolDefinition[CapabilitiesT]] = {}
        intents: set[str] = set()
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"duplicate tool definition: {definition.name}")
            if not definition.description.strip():
                raise ValueError(f"tool {definition.name} requires a description")
            if require_agent_metadata:
                if not definition.title or not definition.title.strip():
                    raise ValueError(f"tool {definition.name} requires a title")
                if definition.output_model is None:
                    raise ValueError(
                        f"tool {definition.name} requires an output schema"
                    )
                if definition.behavior is None:
                    raise ValueError(f"tool {definition.name} requires behavior hints")
                if definition.intent in intents:
                    raise ValueError(
                        f"tool {definition.name} duplicates intent {definition.intent}"
                    )
            schema = definition.input_model.model_json_schema()
            if schema.get("type") != "object":
                raise ValueError(
                    f"tool {definition.name} input schema must be an object"
                )
            if require_agent_metadata:
                missing_descriptions = _undocumented_input_properties(schema)
                if missing_descriptions:
                    raise ValueError(
                        f"tool {definition.name} input properties require descriptions: "
                        f"{', '.join(missing_descriptions)}"
                    )
            self._definitions[definition.name] = definition
            intents.add(definition.intent or definition.name)
        self._profiles: dict[str, ToolProfile] = {}
        for profile in profiles:
            if profile.name in self._profiles:
                raise ValueError(f"duplicate tool profile: {profile.name}")
            missing = profile.tool_names.difference(self._definitions)
            if missing:
                raise ValueError(
                    f"profile {profile.name} references missing tools: "
                    f"{', '.join(sorted(missing))}"
                )
            self._profiles[profile.name] = profile

    def _profile(self, profile_name: str) -> ToolProfile:
        try:
            return self._profiles[profile_name]
        except KeyError as exc:
            raise KeyError(f"unknown tool profile: {profile_name}") from exc

    @staticmethod
    def _is_authorized(
        definition: ToolDefinition[CapabilitiesT],
        access: ToolAccess,
    ) -> bool:
        return definition.required_permission in access.permissions

    def definitions_for(
        self,
        access: ToolAccess,
    ) -> list[ToolDefinition[CapabilitiesT]]:
        profile = self._profile(access.profile_name)
        return [
            definition
            for name in sorted(profile.tool_names)
            if self._is_authorized(
                definition := self._definitions[name],
                access,
            )
        ]

    def definition_for(
        self,
        access: ToolAccess,
        name: str,
    ) -> ToolDefinition[CapabilitiesT]:
        profile = self._profile(access.profile_name)
        if name not in profile.tool_names:
            raise KeyError(f"tool unavailable: {name}")
        definition = self._definitions[name]
        if not self._is_authorized(definition, access):
            raise KeyError(f"tool unavailable: {name}")
        return definition

    def is_available(self, access: ToolAccess, name: str) -> bool:
        try:
            self.definition_for(access, name)
        except KeyError:
            return False
        return True

    def profile_tool_names(self, profile_name: str) -> frozenset[str]:
        """Names reserved by a profile, independent of current authorization."""
        return self._profile(profile_name).tool_names

    def provider_declarations(self, access: ToolAccess) -> list[dict[str, object]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.input_model.model_json_schema(),
            }
            for definition in self.definitions_for(access)
        ]
