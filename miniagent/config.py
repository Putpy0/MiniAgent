"""MiniAgent configuration module using Pydantic."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    """Configuration for LLM provider settings."""

    primary: str = Field(
        default="openrouter/qwen/qwen-2.5-coder-32b-instruct",
        description="Primary LLM provider model identifier"
    )
    fallback: list[str] = Field(
        default_factory=lambda: [
            "groq/llama-3.3-70b-versatile",
            "ollama/qwen2.5-coder"
        ],
        description="List of fallback providers in order of preference"
    )
    api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="API keys for providers (can use ${ENV_VAR} syntax)"
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM generation"
    )
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum tokens for LLM response"
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum retry attempts on failure"
    )
    timeout: int = Field(
        default=60,
        gt=0,
        description="Timeout in seconds for LLM requests"
    )

    @field_validator("api_keys")
    @classmethod
    def resolve_env_vars(cls, v: dict[str, str]) -> dict[str, str]:
        """Resolve ${ENV_VAR} syntax in API keys."""
        resolved = {}
        for key, value in v.items():
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                resolved[key] = os.getenv(env_var, "")
            else:
                resolved[key] = value
        return resolved


class ExecutorConfig(BaseModel):
    """Configuration for command executor settings."""

    type: str = Field(
        default="subprocess",
        description="Executor type: 'subprocess' or 'docker'"
    )
    workspace: str = Field(
        default="./workspace",
        description="Restricted workspace directory for file operations"
    )
    timeout: int = Field(
        default=30,
        gt=0,
        description="Default timeout in seconds for command execution"
    )
    log_file: str = Field(
        default=".miniagent/logs/execution.log",
        description="Path to execution log file"
    )


class MemoryConfig(BaseModel):
    """Configuration for memory settings."""

    short_term_window: int = Field(
        default=10,
        gt=0,
        description="Number of messages to keep in short-term memory"
    )
    long_term_enabled: bool = Field(
        default=True,
        description="Enable long-term memory persistence"
    )
    storage_path: str = Field(
        default=".miniagent/memory",
        description="Path for long-term memory storage"
    )


class MiniAgentConfig(BaseModel):
    """Main configuration model for MiniAgent."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills_dir: str = Field(
        default="./skills",
        description="Directory containing skill folders"
    )
    prompts_dir: str = Field(
        default="./prompts",
        description="Directory containing prompt templates"
    )
    sessions_dir: str = Field(
        default=".miniagent/sessions",
        description="Directory for session state files"
    )
    logs_dir: str = Field(
        default=".miniagent/logs",
        description="Directory for log files"
    )

    @classmethod
    def load_from_yaml(cls, config_path: Optional[str] = None) -> "MiniAgentConfig":
        """Load configuration from YAML file with environment variable resolution."""
        load_dotenv()  # Load .env file if exists

        if config_path is None:
            config_path = os.getenv("MINIAGENT_CONFIG", "config.yaml")

        config_file = Path(config_path)
        if not config_file.exists():
            # Return default config if no config file found
            return cls()

        with open(config_file, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        # An empty (or comment-only) YAML file parses to None - fall back to {}
        raw_config = raw_config or {}

        # Resolve environment variables in the raw config
        raw_config = cls._resolve_env_in_dict(raw_config)

        return cls(**raw_config)

    @classmethod
    def _resolve_env_in_dict(cls, d: dict[str, Any]) -> dict[str, Any]:
        """Recursively resolve ${ENV_VAR} syntax in dictionary values."""
        result = {}
        for key, value in d.items():
            if isinstance(value, dict):
                result[key] = cls._resolve_env_in_dict(value)
            elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                result[key] = os.getenv(env_var, "")
            else:
                result[key] = value
        return result

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        dirs_to_create = [
            self.executor.workspace,
            self.skills_dir,
            self.prompts_dir,
            self.sessions_dir,
            self.logs_dir,
            self.memory.storage_path,
        ]
        for dir_path in dirs_to_create:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
