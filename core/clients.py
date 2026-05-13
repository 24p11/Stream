from abc import ABC, abstractmethod
from typing import override

import json
import time
from io import BytesIO

import httpx
from anthropic import Anthropic
from mistralai.client import Mistral
from ollama import Client


class BaseClient(ABC):
    """Base class for clients"""

    def __init__(self) -> None:
        super().__init__()

    @abstractmethod
    def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        raise NotImplementedError


class AnthropicClient(BaseClient):
    """Anthropic (Claude) client normalised to the ``chat()`` interface.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    verify:
        ``True`` (default), ``False``, or path to a CA bundle (``.pem``).
    """

    def __init__(self, api_key: str, verify: bool | str = True) -> None:
        super().__init__()

        self._client = Anthropic(
            api_key=api_key, http_client=httpx.Client(verify=verify)
        )

    @override
    def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        system: str | None = None
        chat_messages: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                chat_messages.append(msg)

        params: dict = dict(
            model=model,
            max_tokens=kwargs.get("max_tokens", 4096),
            messages=chat_messages,
        )
        if system:
            params["system"] = system

        response = self._client.messages.create(**params)  # type: ignore[arg-type]

        return {
            "message": {
                "role": "assistant",
                "content": response.content[0].text,
            }
        }


class MistralClient(BaseClient):
    """Mistral client normalised to the ``chat()`` interface.

    Parameters
    ----------
    api_key:
        Mistral API key.
    verify:
        ``True`` (default), ``False``, or path to a CA bundle (``.pem``).
    """

    def __init__(self, api_key: str, verify: bool | str = True) -> None:
        super().__init__()

        self._client = Mistral(api_key=api_key, timeout_ms=120_000)
        if verify is not True:
            self._client.client._client = httpx.Client(verify=verify)

    @override
    def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        response = self._client.chat.complete(
            model=model,
            max_tokens=kwargs.get("max_tokens", 4096),
            messages=messages,
        )

        return {
            "message": {
                "role": "assistant",
                "content": response.choices[0].message.content,
            }
        }
    
    def batch_chat(
        self,
        model: str,
        requests: list[dict],
        *,
        max_tokens: int = 128_000,
        poll_interval_seconds: int = 1,
    ) -> list[dict]:
        """Run a Mistral batch job with this batch format:
        system prompt + user prompt + assistant prefix.
        """
        buffer = BytesIO()

        for idx, item in enumerate(requests):
            custom_id = str(item.get("custom_id", idx))

            request = {
                "custom_id": custom_id,
                "body": {
                    "max_tokens": max_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": item["system_prompt"],
                        },
                        {
                            "role": "user",
                            "content": item["user_prompt"],
                        },
                        {
                            "role": "assistant",
                            "content": item["prefix"],
                            "prefix": True,
                        },
                    ],
                },
            }

            buffer.write(json.dumps(request, ensure_ascii=False).encode("utf-8"))
            buffer.write(b"\n")

        input_file = self._client.files.upload(
            file={
                "file_name": "stream_aphp_batch.jsonl",
                "content": buffer.getvalue(),
            },
            purpose="batch",
        )

        batch_job = self._client.batch.jobs.create(
            input_files=[input_file.id],
            model=model,
            endpoint="/v1/chat/completions",
            metadata={"job_type": "stream_aphp"},
        )

        while batch_job.status in ["QUEUED", "RUNNING"]:
            time.sleep(poll_interval_seconds)
            batch_job = self._client.batch.jobs.get(job_id=batch_job.id)

        if batch_job.status not in {"SUCCESS", "SUCCEEDED"}:
            raise RuntimeError(
                f"Mistral batch job {batch_job.id} ended with status {batch_job.status}"
            )

        output_file_id = getattr(batch_job, "output_file", None) or getattr(
            batch_job, "output_file_id", None
        )

        if output_file_id is None:
            raise RuntimeError(
                f"Mistral batch job {batch_job.id} has no output file."
            )

        output_file = self._client.files.download(file_id=output_file_id)

        raw_bytes = b""
        for chunk in output_file.stream:
            raw_bytes += chunk

        responses: list[dict] = []

        for line in raw_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue

            response_item = json.loads(line)
            custom_id = str(response_item.get("custom_id"))

            error = response_item.get("error")
            if error:
                responses.append(
                    {
                        "custom_id": custom_id,
                        "content": "",
                        "error": error,
                        "raw": response_item,
                    }
                )
                continue

            content = response_item["response"]["body"]["choices"][0]["message"][
                "content"
            ]

            responses.append(
                {
                    "custom_id": custom_id,
                    "content": content,
                    "error": None,
                    "raw": response_item,
                }
            )

        return sorted(responses, key=lambda x: int(x["custom_id"]))


class OllamaClient(BaseClient):
    """Ollama client normalised to the ``chat()`` interface.
    Parameters
    ----------
    base_url:
        Ollama server URL (default: ``http://localhost:11434``).
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        super().__init__()
        self._client = Client(host=base_url)

    @override
    def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        response = self._client.chat(
            model=model,
            messages=messages,
            options={"num_predict": kwargs.get("max_tokens", 4096)},
        )
        return {
            "message": {
                "role": "assistant",
                "content": response.message.content,
            }
        }


def get_client(
    servers: dict, client_type: str = "ollama"
) -> tuple[AnthropicClient | MistralClient | OllamaClient, str]:
    """Instantiate an LLM client and return ``(client, model_name)``."""
    if client_type == "ollama":
        cfg = servers["ollama"]
        return OllamaClient(cfg["host"]), cfg["model"]

    if client_type == "claude":
        cfg = servers["claude"]
        return AnthropicClient(
            api_key=cfg["api_key"],
            verify=cfg.get("verify", True),
        ), cfg["model"]

    if client_type == "mistral":
        cfg = servers["mistral"]
        return MistralClient(
            api_key=cfg["api_key"],
            verify=cfg.get("verify", True),
        ), cfg["model"]

    raise ValueError(
        f"Type de client inconnu : '{client_type}'. "
        "Valeurs acceptées : ollama, claude, mistral."
    )
