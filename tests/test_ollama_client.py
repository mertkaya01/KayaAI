import pytest

from kayaai.config import OllamaSettings
from kayaai.llm.ollama_client import OllamaClient, OllamaError, OllamaModelNotFound, OllamaUnavailable


def test_version_and_models(client, fake_ollama):
    assert client.version() == "0.0.0-fake"
    assert client.is_available()
    assert client.has_model("qwen3:8b")
    assert not client.has_model("llama3:70b")


def test_chat_sends_schema_options_and_parses_metrics(client, fake_ollama):
    fake_ollama.chat_replies = ['{"a": 1}']
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    res = client.chat("qwen3:8b", [{"role": "user", "content": "x"}], format=schema,
                      options={"num_ctx": 4096}, think=False, keep_alive="5m")
    assert res.content == '{"a": 1}'
    assert res.output_tokens == 40 and res.tokens_per_second == 40.0
    body = fake_ollama.chat_paths()[-1]
    assert body["format"] == schema
    assert body["options"] == {"num_ctx": 4096}
    assert body["think"] is False and body["stream"] is False and body["keep_alive"] == "5m"


def test_think_omitted_when_none(client, fake_ollama):
    fake_ollama.chat_replies = ["ok"]
    client.chat("qwen3:8b", [{"role": "user", "content": "x"}])
    assert "think" not in fake_ollama.chat_paths()[-1]


def test_missing_model_raises_not_found_without_retry(client, fake_ollama):
    with pytest.raises(OllamaModelNotFound):
        client.chat("yok:1b", [{"role": "user", "content": "x"}])
    assert len(fake_ollama.chat_paths()) == 1


def test_5xx_is_retried_then_succeeds(client, fake_ollama):
    fake_ollama.chat_replies = [(500, {"error": "boom"}), "ok"]
    assert client.chat("qwen3:8b", [{"role": "user", "content": "x"}]).content == "ok"
    assert len(fake_ollama.chat_paths()) == 2


def test_4xx_not_retried(client, fake_ollama):
    fake_ollama.chat_replies = [(400, {"error": "bad request"})]
    with pytest.raises(OllamaError, match="HTTP 400"):
        client.chat("qwen3:8b", [{"role": "user", "content": "x"}])
    assert len(fake_ollama.chat_paths()) == 1


def test_unreachable_server_raises_unavailable():
    # Kullanılmayan bir port: bağlantı reddedilir.
    c = OllamaClient(OllamaSettings(base_url="http://127.0.0.1:9", max_retries=1, retry_backoff_s=0.01))
    with pytest.raises(OllamaUnavailable):
        c.version()
    assert not c.is_available()
    c.close()


def test_non_local_url_detected():
    assert not OllamaSettings(base_url="http://192.168.1.5:11434").is_local
    assert OllamaSettings(base_url="http://localhost:11434/").is_local
