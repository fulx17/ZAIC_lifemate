"""Composition root for the five V2 ownership modules."""

from __future__ import annotations

from typing import Any

from core.config import configured_path
from core.llm import BudgetedLLMClient, LocalQwenClient, MockLLMClient
from modules.asr.mock import MockASR
from modules.asr.pho_whisper import PhoWhisperASR
from modules.discovery.service import DiscoveryService
from modules.planner.service import MockPlanner, SingleShotPlanner
from modules.resolver.service import ResolverService
from modules.runtime.engine import RuntimeService

_LLM_SINGLETONS: dict[str, Any] = {}


def build_llm(config: dict[str, Any]) -> Any:
    model_config = config.get("models", {}).get("llm", {})
    if model_config.get("impl", "mock") == "mock":
        return MockLLMClient()
    local_path = model_config.get("local_path")
    if not local_path:
        raise ValueError("models.llm.local_path must point to a local Qwen snapshot in local mode")
    resolved = configured_path(config, local_path)
    key = str(resolved)
    if key not in _LLM_SINGLETONS:
        _LLM_SINGLETONS[key] = LocalQwenClient(
            str(resolved),
            max_new_tokens=max(model_config.get("max_new_tokens", {}).values(), default=768),
            seed=config.get("run", {}).get("seed", 42),
            quantization=model_config.get("quantization"),
        )
    return _LLM_SINGLETONS[key]


class PipelineServices:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.raw_llm = build_llm(config)
        planning = config.get("planning", {})
        max_llm_calls = planning.get(
            "max_initial_calls",
            config.get("run", {}).get("max_llm_calls", 1),
        ) + planning.get("max_repair_calls", 0)
        self.llm = BudgetedLLMClient(self.raw_llm, max_calls=max_llm_calls)
        modules = config.get("modules", {})
        model_config = config.get("models", {})
        asr_impl = modules.get("asr_impl", "mock")
        if asr_impl == "mock":
            self.asr = MockASR()
        elif asr_impl == "pho_whisper":
            asr_settings = model_config.get("asr", {})
            local_path = asr_settings.get("local_path")
            if not local_path:
                raise ValueError("models.asr.local_path must point to local PhoWhisper weights")
            self.asr = PhoWhisperASR(
                str(configured_path(config, local_path)),
                device=asr_settings.get("device"),
                torch_dtype=asr_settings.get("torch_dtype"),
            )
        else:
            raise ValueError(f"Unknown ASR implementation: {asr_impl}")

        discovery_settings = config.get("discovery", {})
        self.discovery = DiscoveryService(
            top_k=discovery_settings.get("initial_top_k", modules.get("discovery_top_k", 8)),
            recovery_top_k=discovery_settings.get("recovery_top_k", 5),
        )
        planner_impl = modules.get("planner_impl", "mock")
        if planner_impl == "mock":
            self.planner = MockPlanner()
        elif planner_impl == "qwen_single_shot":
            self.planner = SingleShotPlanner(
                self.llm,
                max_new_tokens=model_config.get("llm", {}).get("max_new_tokens", {}).get("plan", 900),
                repair_max_new_tokens=model_config.get("llm", {}).get("max_new_tokens", {}).get("repair", 700),
            )
        else:
            raise ValueError(f"Unknown planner implementation: {planner_impl}")
        resolver_settings = config.get("resolver", {})
        self.resolver = ResolverService(
            require_provenance_for=resolver_settings.get("require_provenance_for"),
            strict_semantic_ready=resolver_settings.get("strict_semantic_ready", True),
        )
        run_settings = config.get("run", {})
        self.runtime = RuntimeService(
            max_steps=run_settings.get("max_execution_steps", 12),
            timeout_seconds=run_settings.get("max_runtime_seconds", 120),
            max_explore_tasks=config.get("runtime", {}).get("max_explore_tasks", 3),
            per_issue_attempts=config.get("runtime", {}).get("per_issue_attempts", 1),
        )

    def reset_budget(self) -> None:
        self.llm.reset()
