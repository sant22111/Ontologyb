"""Rename to workbench_adapter.py and set LLM_PROVIDER=workbench.
Wrap your existing KPMG Workbench chat function. It must return the reply TEXT (a JSON string)."""


def chat(system: str, messages: list, max_tokens: int) -> str:
    # from your_app import workbench_chat
    # return workbench_chat([{"role": "system", "content": system}] + messages, max_tokens=max_tokens)
    raise NotImplementedError("connect this to your Workbench wrapper")
