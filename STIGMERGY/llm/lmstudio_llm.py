import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"


def _lmstudio_openai_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "LMSTUDIO_ENDPOINT must be an absolute URL, for example "
            "'http://localhost:1234/v1'."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))


def create_client():
    endpoint = os.getenv("LMSTUDIO_ENDPOINT")
    if not endpoint:
        raise ValueError("LMSTUDIO_ENDPOINT must be set when using LM Studio.")
    return OpenAI(
        api_key=os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
        base_url=_lmstudio_openai_endpoint(endpoint),
    )


client = create_client()


def _format_relation_judgment(content):
    data = json.loads(content)
    subject = data["subject"].strip()
    predicate = data["predicate"].strip()
    object_ = data["object"].strip()
    reason = data["reason"].strip()

    if not all((subject, predicate, object_, reason)):
        raise ValueError(f"Incomplete relation judgment: {content!r}")

    return f"({subject} {predicate} {object_}) - {reason}"


RELATION_JUDGMENT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "relation_judgment",
        "schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                },
                "predicate": {
                    "type": "string",
                    "enum": [
                        "supports",
                        "contradicts",
                        "requires",
                        "causes",
                        "is unrelated to",
                    ],
                },
                "object": {
                    "type": "string",
                },
                "reason": {
                    "type": "string",
                },
            },
            "required": ["subject", "predicate", "object", "reason"],
            "additionalProperties": False,
        },
    },
}


def _resolve_system_prompt(system_prompt):
    if system_prompt is None:
        return DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    prompt = str(system_prompt)
    if "\n" not in prompt:
        path = Path(prompt)
        if path.exists():
            return path.read_text(encoding="utf-8")
    return prompt


class LMStudioLLM:
    def __init__(
        self,
        system_prompt=None,
        response_format=None,
        formatter=_format_relation_judgment,
    ):
        self.client = client
        self.model = os.getenv("LMSTUDIO_MODEL")
        self.system_msg = _resolve_system_prompt(system_prompt)
        self.response_format = (
            RELATION_JUDGMENT_RESPONSE_FORMAT
            if response_format is None
            else response_format
        )
        self.formatter = formatter
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = [
            {
                "role": "system",
                "content": self.system_msg,
            }
        ]

    def send_messages(self, message, max_tokens=500, temperature=1.0):
        self.messages.append({"role": "user", "content": str(message)})
        request = {
            "model": self.model,
            "messages": self.messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.response_format is not False:
            request["response_format"] = self.response_format

        response = self.client.chat.completions.create(**request)

        content = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": content})
        if response.usage:
            self.prompt_tokens += response.usage.prompt_tokens or 0
            self.completion_tokens += response.usage.completion_tokens or 0
            self.total_tokens += response.usage.total_tokens or 0
        if self.formatter is None:
            return content
        return self.formatter(content)


if __name__ == "__main__":
    agent = LMStudioLLM(system_prompt="llm/system_prompt.md")
    response = agent.send_messages("Write a 10 word joke")
    print(response)
