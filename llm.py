"""Model adapter. One place to change which AI model runs the studio.

Provider is picked from environment variables (see .env.example):
  LLM_PROVIDER = anthropic | azure | openai | workbench | mock
If LLM_PROVIDER is empty, the first key found is used, otherwise mock mode.

"workbench": create a file workbench_adapter.py next to this one with
    def chat(system: str, messages: list[dict], max_tokens: int) -> str
that calls your KPMG Workbench wrapper and returns the reply text.
"""
import json
import os
import re


class LLMError(Exception):
    pass


def extract_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object found in model reply")


class LLM:
    def __init__(self):
        p = (os.getenv("LLM_PROVIDER") or "").lower().strip()
        if not p:
            if os.getenv("ANTHROPIC_API_KEY"):
                p = "anthropic"
            elif os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
                p = "azure"
            elif os.getenv("OPENAI_API_KEY"):
                p = "openai"
            else:
                p = "mock"
        self.provider = p
        defaults = {
            "anthropic": "claude-sonnet-5-5",
            "azure": os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
            "openai": "gpt-4.1",
            "workbench": "workbench",
            "mock": "mock",
        }
        self.model = os.getenv("ONTOLOGY_MODEL") or defaults.get(p, "unknown")
        self._client = None

    # ------------------------------------------------------------------
    def _text(self, system, messages, max_tokens):
        try:
            if self.provider == "anthropic":
                import anthropic
                if self._client is None:
                    self._client = anthropic.Anthropic()
                r = self._client.messages.create(
                    model=self.model, max_tokens=max_tokens, system=system, messages=messages
                )
                return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            if self.provider in ("azure", "openai"):
                import openai
                if self._client is None:
                    if self.provider == "azure":
                        self._client = openai.AzureOpenAI(
                            api_key=os.environ["AZURE_OPENAI_API_KEY"],
                            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                        )
                    else:
                        self._client = openai.OpenAI()
                r = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}] + messages,
                    temperature=0.2,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                return r.choices[0].message.content
            if self.provider == "workbench":
                import workbench_adapter  # your own file
                return workbench_adapter.chat(system, messages, max_tokens)
        except Exception as e:  # surface a readable message to the UI
            raise LLMError(f"{self.provider} call failed: {e}") from e
        raise LLMError(f"unknown provider {self.provider}")

    # ------------------------------------------------------------------
    def json(self, task, system, messages, max_tokens=4000, context=None):
        """Ask for a JSON object. `task` and `context` are only used by mock mode."""
        if self.provider == "mock":
            from mock_llm import respond
            return respond(task, context or {})
        msgs = list(messages)
        last = None
        for _ in range(2):
            txt = self._text(system, msgs, max_tokens)
            try:
                return extract_json(txt)
            except Exception as e:
                last = e
                msgs = msgs + [
                    {"role": "assistant", "content": txt or "(empty)"},
                    {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON object, nothing else."},
                ]
        raise LLMError(f"model did not return valid JSON: {last}")


llm = LLM()
