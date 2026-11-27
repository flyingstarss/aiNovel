from langchain_deepseek import ChatDeepSeek

from app import monitor
from app.config import settings


def create_llm(
    temperature: float,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
) -> ChatDeepSeek:
    kwargs = dict(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        temperature=temperature,
        max_tokens=settings.llm_max_tokens,
        max_retries=settings.llm_max_retries,
        extra_body={"thinking": {"type": "disabled"}},
    )
    # 默认 120s 无 chunk 即判定断流，长章节写作时容易误杀；
    # 0 表示关闭该判定，连接是否存活交给底层 TCP 超时处理
    timeout = settings.llm_stream_chunk_timeout
    kwargs["stream_chunk_timeout"] = timeout if timeout and timeout > 0 else None
    if presence_penalty is not None:
        kwargs["presence_penalty"] = presence_penalty
    if frequency_penalty is not None:
        kwargs["frequency_penalty"] = frequency_penalty
    if settings.deepseek_base_url:
        kwargs["api_base"] = settings.deepseek_base_url
    return monitor.attach(ChatDeepSeek(**kwargs))
