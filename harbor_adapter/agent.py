"""Harbor agent adapter for the Cartwheel support agent."""

from __future__ import annotations

import json
import os
import shlex
from typing import override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from harbor_adapter.export import _provider_key


class CartwheelAgent(BaseAgent):
    """Run Cartwheel once against the case packaged with a Harbor task."""

    @staticmethod
    @override
    def name() -> str:
        return "cartwheel"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        return

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        model = self.model_name or self.extra_env.get("CARTWHEEL_MODEL")
        if not model:
            raise ValueError("CartwheelAgent requires a model")

        provider_key = _provider_key(model)
        credential_names = {provider_key} if provider_key else set()
        if provider_key:
            credential_names.add(provider_key.removesuffix("_API_KEY") + "_BASE_URL")
        runtime_env = {
            key: value
            for key in credential_names
            if (value := os.environ.get(key))
        }
        runtime_env.update(self.extra_env)

        result = await environment.exec(
            command=(
                "/app/.venv/bin/python -m harbor_adapter.runtime "
                "--case /app/case.json "
                "--output /app/cartwheel-result.json "
                f"--model {shlex.quote(model)}"
            ),
            cwd="/app",
            env=runtime_env,
        )
        if result.return_code != 0:
            detail = result.stderr or result.stdout or "no output"
            raise RuntimeError(f"Cartwheel exited with code {result.return_code}: {detail}")

        host_result = self.logs_dir / "cartwheel-result.json"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        await environment.download_file(
            source_path="/app/cartwheel-result.json",
            target_path=host_result,
        )
        evidence = json.loads(host_result.read_text())
        usage = evidence.get("transcript", {}).get("usage", {})
        context.n_input_tokens = usage.get("input_tokens")
        context.n_output_tokens = usage.get("output_tokens")
        context.metadata = {
            "case_id": evidence.get("case_id"),
            "kind": evidence.get("kind"),
        }
