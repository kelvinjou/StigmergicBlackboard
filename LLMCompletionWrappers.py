import os
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from openai import OpenAI

from config import LLM_PROVIDER

load_dotenv()

NVIDIA_NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1"


def _lmstudio_openai_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "LMSTUDIO_ENDPOINT must be an absolute URL, for example "
            "'http://localhost:1234/v1'."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))


def create_client(provider=LLM_PROVIDER):
    provider = provider.strip().lower()

    if provider == "lmstudio":
        endpoint = os.getenv("LMSTUDIO_ENDPOINT")
        if not endpoint:
            raise ValueError("LMSTUDIO_ENDPOINT must be set when using LM Studio.")
        return OpenAI(
            api_key=os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
            base_url=_lmstudio_openai_endpoint(endpoint),
        )

    if provider == "nvidia_nim":
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY must be set when using NVIDIA NIM.")
        return OpenAI(
            api_key=api_key,
            base_url=os.getenv("NVIDIA_NIM_ENDPOINT", NVIDIA_NIM_ENDPOINT),
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER {provider!r}. "
        "Use 'lmstudio' or 'nvidia_nim'."
    )


client = create_client()
