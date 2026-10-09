"""Registry of the search providers a user can pick for a run."""

from collections.abc import Callable

from search_agents.providers.base import SearchProvider
from search_agents.providers.fake import FakeSearchProvider

_PROVIDERS: dict[str, Callable[[], SearchProvider]] = {
    "fake": FakeSearchProvider,
}


class UnknownProviderError(Exception):
    def __init__(self, name: str | None) -> None:
        registered = ", ".join(registered_providers())
        problem = "no search provider chosen" if name is None else f"unknown search provider '{name}'"
        super().__init__(f"{problem}; registered providers: {registered}")


def registered_providers() -> list[str]:
    return sorted(_PROVIDERS)


def create_provider(name: str | None) -> SearchProvider:
    factory = _PROVIDERS.get(name) if name is not None else None
    if factory is None:
        raise UnknownProviderError(name)
    return factory()
