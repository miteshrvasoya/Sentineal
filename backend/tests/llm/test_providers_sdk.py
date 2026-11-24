"""Provider adapters exercised with real SDK response/exception types (no network)."""
import httpx
import pytest

from app.llm.base import LLMError, LLMRateLimited
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.openai_compat import OpenAICompatProvider

REQ = httpx.Request("POST", "https://x.test/v1")


def resp(code, body="{}"):
    return httpx.Response(code, request=REQ, text=body)


class Box:  # tiny namespace
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def test_anthropic_parses_text_and_usage():
    from anthropic.types import Message, TextBlock, Usage
    msg = Message(id="m1", model="claude-haiku-5-5", role="assistant", type="message", stop_reason="end_turn", stop_sequence=None,
                  content=[TextBlock(type="text", text='{"a": 1}', citations=None)], usage=Usage(input_tokens=11, output_tokens=7))
    seen = {}

    async def create(**kw):
        seen.update(kw)
        return msg
    p = AnthropicProvider(client=Box(messages=Box(create=create)), key="")
    r = await p.complete(system="S", user="U", model="claude-haiku-5-5", temperature=0.0, max_tokens=50)
    assert (r.text, r.tokens_in, r.tokens_out, r.provider) == ('{"a": 1}', 11, 7, "anthropic")
    assert seen["system"] == "S" and seen["messages"] == [{"role": "user", "content": "U"}] and seen["max_tokens"] == 50


async def test_anthropic_retries_without_rejected_temperature_and_maps_errors():
    import anthropic
    from anthropic.types import Message, TextBlock, Usage
    ok = Message(id="m", model="x", role="assistant", type="message", stop_reason="end_turn", stop_sequence=None,
                 content=[TextBlock(type="text", text="ok", citations=None)], usage=Usage(input_tokens=1, output_tokens=1))
    calls = []

    async def create(**kw):
        calls.append(dict(kw))
        if "temperature" in kw:
            raise anthropic.BadRequestError("`temperature` is not supported for this model", response=resp(400), body=None)
        return ok
    p = AnthropicProvider(client=Box(messages=Box(create=create)))
    assert (await p.complete(system="s", user="u", model="m")).text == "ok" and len(calls) == 2 and "temperature" not in calls[1]

    async def limited(**kw):
        raise anthropic.RateLimitError("slow down sk-SECRET", response=resp(429), body=None)
    with pytest.raises(LLMRateLimited) as e:
        await AnthropicProvider(client=Box(messages=Box(create=limited))).complete(system="s", user="u", model="m")
    assert "SECRET" not in str(e.value)

    async def broken(**kw):
        raise anthropic.APIConnectionError(request=REQ)
    with pytest.raises(LLMError):
        await AnthropicProvider(client=Box(messages=Box(create=broken))).complete(system="s", user="u", model="m")


def chat(text="hello", pt=9, ct=4):
    from openai.types import CompletionUsage
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice
    return ChatCompletion(id="c", created=0, model="gpt", object="chat.completion", usage=CompletionUsage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
                          choices=[Choice(finish_reason="stop", index=0, message=ChatCompletionMessage(role="assistant", content=text))])


async def test_openai_compat_usage_json_mode_and_parameter_peeling():
    import openai
    calls = []

    async def create(**kw):
        calls.append(dict(kw))
        if "max_tokens" in kw:
            raise openai.BadRequestError("Unsupported parameter: 'max_tokens'. Use max_completion_tokens", response=resp(400), body=None)
        if "temperature" in kw:
            raise openai.BadRequestError("temperature does not support 0.0", response=resp(400), body=None)
        return chat('{"x": 2}')
    p = OpenAIProvider(client=Box(chat=Box(completions=Box(create=create))), key="")
    r = await p.complete(system="S", user="U", model="gpt", json_mode=True, max_tokens=20)
    assert (r.text, r.tokens_in, r.tokens_out) == ('{"x": 2}', 9, 4)
    assert calls[0]["response_format"] == {"type": "json_object"} and "max_completion_tokens" in calls[-1] and "temperature" not in calls[-1]


async def test_openai_rate_limit_and_configuration_rules():
    import openai

    async def limited(**kw):
        raise openai.RateLimitError("too many", response=resp(429), body=None)
    p = OpenAICompatProvider("groq", "k", "https://api.groq.com/openai/v1", True, client=Box(chat=Box(completions=Box(create=limited))))
    with pytest.raises(LLMRateLimited):
        await p.complete(system="s", user="u", model="m")
    assert not OpenAICompatProvider("groq", "", "u", True).is_configured()
    assert OpenAICompatProvider("ollama", "", "http://localhost:11434/v1", False).is_configured()
    assert not OpenAICompatProvider("ollama", "", None, False).is_configured()


async def test_gemini_parses_text_usage_and_429():
    from google.genai import errors, types
    r0 = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text='{"k": 1}')]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=5, candidates_token_count=3))
    seen = {}

    async def gen(**kw):
        seen.update(kw)
        return r0
    client = Box(aio=Box(models=Box(generate_content=gen)))
    r = await GeminiProvider(client=client).complete(system="S", user="U", model="gemini-x", json_mode=True, max_tokens=30)
    assert (r.text, r.tokens_in, r.tokens_out) == ('{"k": 1}', 5, 3)
    assert seen["config"].response_mime_type == "application/json" and seen["config"].system_instruction == "S"

    async def over(**kw):
        raise errors.APIError(429, {"error": {"message": "quota"}})
    with pytest.raises(LLMRateLimited):
        await GeminiProvider(client=Box(aio=Box(models=Box(generate_content=over)))).complete(system="s", user="u", model="m")


def test_unconfigured_without_keys():
    assert not AnthropicProvider(key="").is_configured() and not GeminiProvider(key="").is_configured()
    assert not OpenAIProvider(key="").is_configured()
