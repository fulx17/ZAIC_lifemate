"""Lazy local Qwen client and deterministic mock client."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from core.errors import BudgetExceededError, ModelUnavailableError
from core.json_utils import parse_json_response

T = TypeVar("T", bound=BaseModel)


class LocalQwenClient:
    """Loads one local Transformers model lazily; remote downloads are disabled."""

    def __init__(
        self,
        model_path: str,
        *,
        max_new_tokens: int = 768,
        seed: int = 42,
        quantization: str | None = None,
    ):
        self.model_path = Path(model_path)
        self.max_new_tokens = max_new_tokens
        self.seed = seed
        if quantization not in {None, "4bit"}:
            raise ValueError(f"Unsupported Qwen quantization: {quantization!r}")
        self.quantization = quantization
        self._model: Any = None
        self._tokenizer: Any = None
        self.call_count = 0

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.model_path.exists():
            raise ModelUnavailableError("MODEL_NOT_FOUND", f"Local Qwen model path does not exist: {self.model_path}")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise ModelUnavailableError(
                "MODEL_DEPENDENCY_MISSING", "Install the local-model extra to use Qwen."
            ) from exc
        load_options: dict[str, Any] = {"device_map": "auto"}
        if self.quantization == "4bit":
            if not torch.cuda.is_available():
                raise ModelUnavailableError(
                    "QUANTIZATION_REQUIRES_CUDA", "4-bit Qwen loading requires a CUDA-enabled GPU."
                )
            try:
                from transformers import BitsAndBytesConfig
            except ImportError as exc:
                raise ModelUnavailableError(
                    "QUANTIZATION_DEPENDENCY_MISSING",
                    "Install the local-model extra with bitsandbytes to use 4-bit Qwen.",
                ) from exc
            load_options["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            load_options["torch_dtype"] = torch.float16
        else:
            load_options["torch_dtype"] = "auto"
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_path), local_files_only=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self.model_path), local_files_only=True, **load_options
        )
        self._torch = torch

    def generate_text(self, prompt: str, *, max_new_tokens: int | None = None, thinking: bool = False) -> str:
        self._load()
        self.call_count += 1
        messages = [{"role": "user", "content": prompt}]
        prompt_text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=thinking
        )
        inputs = self._tokenizer(prompt_text, return_tensors="pt").to(self._model.device)
        self._torch.manual_seed(self.seed)
        output = self._model.generate(
            **inputs,
            max_new_tokens=max_new_tokens or self.max_new_tokens,
            do_sample=False,
        )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        return self._tokenizer.decode(generated, skip_special_tokens=True)

    def generate_json(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        response_model: type[T],
        settings: dict[str, Any] | None = None,
    ) -> T:
        import json

        config = settings or {}
        prompt = (
            f"Task: {prompt_name}\nReturn only JSON matching this schema:\n"
            f"{json.dumps(response_model.model_json_schema(), ensure_ascii=False)}\n"
            f"Input data:\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        answer = self.generate_text(
            prompt,
            max_new_tokens=config.get("max_new_tokens"),
            thinking=bool(config.get("thinking", False)),
        )
        try:
            return parse_json_response(answer, response_model)
        except ValueError as first_error:
            if int(config.get("max_json_repair", 1)) < 1:
                raise
            repaired = self.generate_text(
                f"Repair this response into valid JSON matching the schema. Return JSON only.\n"
                f"Validation error: {first_error}\nResponse:\n{answer}",
                max_new_tokens=config.get("repair_tokens", 512),
            )
            return parse_json_response(repaired, response_model)


class MockLLMClient:
    """Fixture-driven LLM replacement; no model packages or weights are loaded."""

    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.call_settings: list[dict[str, Any]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate_json(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        response_model: type[T],
        settings: dict[str, Any] | None = None,
    ) -> T:
        self.calls.append((prompt_name, payload))
        self.call_settings.append(dict(settings or {}))
        value = self.responses.get(prompt_name)
        if callable(value):
            value = value(payload)
        if value is None:
            raise KeyError(f"No mock LLM response configured for {prompt_name!r}")
        return response_model.model_validate(value)


class BudgetedLLMClient:
    """Per-request cap around one process-shared model client."""

    def __init__(self, client: Any, max_calls: int):
        self.client = client
        self.max_calls = max_calls
        self.calls_used = 0

    def reset(self) -> None:
        self.calls_used = 0

    def generate_json(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        response_model: type[T],
        settings: dict[str, Any] | None = None,
    ) -> T:
        remaining = self.max_calls - self.calls_used
        if remaining <= 0:
            raise BudgetExceededError("MAX_LLM_CALLS", "Per-request LLM call budget exhausted")
        bounded_settings = dict(settings or {})
        bounded_settings["max_json_repair"] = min(bounded_settings.get("max_json_repair", 1), max(0, remaining - 1))
        before = getattr(self.client, "call_count", None)
        try:
            return self.client.generate_json(prompt_name, payload, response_model, bounded_settings)
        finally:
            after = getattr(self.client, "call_count", None)
            self.calls_used += after - before if isinstance(before, int) and isinstance(after, int) else 1
