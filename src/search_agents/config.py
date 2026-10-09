"""Run configuration read from a YAML file."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from search_agents.models import Model

DEFAULT_CONFIG_PATH = Path("search_agents.yaml")


class ConfigError(Exception):
    """The config file is missing or malformed."""


class RunConfig(Model):
    provider: str | None = None


def load_config(path: Path | None) -> RunConfig:
    """Load `path`, or `search_agents.yaml` in the working directory if it exists."""
    if path is None:
        if not DEFAULT_CONFIG_PATH.is_file():
            return RunConfig()
        path = DEFAULT_CONFIG_PATH
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read config: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return RunConfig.model_validate(data if data is not None else {})
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid config: {exc}") from exc
