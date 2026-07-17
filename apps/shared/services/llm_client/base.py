"""
LLM 클라이언트의 공통 인터페이스.

각 provider별 클라이언트는 이 추상 클래스를 상속해 구현합니다.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional


def _safe_billing_usage(usage: Any) -> Dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion_tokens = usage.get(
        "completion_tokens",
        usage.get("output_tokens"),
    )
    if (
        isinstance(prompt_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or prompt_tokens < 0
        or isinstance(completion_tokens, bool)
        or not isinstance(completion_tokens, int)
        or completion_tokens < 0
    ):
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


class LLMResponseValidationError(ValueError):
    """Provider output was unusable after a response with optional safe usage."""

    def __init__(self, message: str, *, usage: Any = None):
        super().__init__(message)
        self.usage: Dict[str, int] | None = _safe_billing_usage(usage)


class BaseLLMClient(ABC):
    """
    provider별 클라이언트의 기본 구조를 정의합니다.

    Args:
        model_id: 사용할 모델 식별자 (예: gpt-4o)
        credentials: API 호출에 필요한 자격 정보 딕셔너리
    """

    def __init__(self, model_id: str, credentials: Optional[Dict[str, Any]] = None):
        self.model_id = model_id
        self.credentials = credentials or {}

    @staticmethod
    def _run_coroutine_sync(
        coro_factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Any:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return BaseLLMClient._run_in_new_event_loop(coro_factory)

        try:
            from gevent import get_hub, monkey
        except ImportError:
            pass
        else:
            if monkey.is_module_patched("threading"):
                # gevent-patched threading still hits asyncio's running-loop guard.
                return get_hub().threadpool.apply(
                    BaseLLMClient._run_in_new_event_loop, (coro_factory,)
                )

        import threading

        result: List[Any] = []
        errors: List[BaseException] = []

        def runner() -> None:
            try:
                result.append(BaseLLMClient._run_in_new_event_loop(coro_factory))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()

        if errors:
            raise errors[0]
        return result[0] if result else None

    @staticmethod
    def _run_in_new_event_loop(
        coro_factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Any:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro_factory())
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    @abstractmethod
    async def invoke(self, messages: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        LLM에 메시지를 전달하고 결과를 반환합니다 (비동기).

        Args:
            messages: role/content 형식의 메시지 리스트
            **kwargs: 추가 옵션 (온도, 토큰 제한 등)

        Returns:
            모델 응답을 담은 딕셔너리
        """
        raise NotImplementedError

    def invoke_sync(self, messages: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        LLM에 메시지를 전달하고 결과를 반환합니다 (동기).

        [GEVENT] gevent 환경에서 사용하기 위한 동기 래퍼.
        기본 구현은 새 이벤트 루프를 생성하여 async invoke를 실행합니다.

        Args:
            messages: role/content 형식의 메시지 리스트
            **kwargs: 추가 옵션 (온도, 토큰 제한 등)

        Returns:
            모델 응답을 담은 딕셔너리
        """
        return self._run_coroutine_sync(lambda: self.invoke(messages, **kwargs))

    @abstractmethod
    def get_num_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        메시지 리스트가 소비할 토큰 수를 추정/계산합니다.

        Args:
            messages: role/content 형식의 메시지 리스트

        Returns:
            예상 토큰 수
        """
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """
        단일 텍스트에 대한 임베딩 벡터를 반환합니다.

        Args:
            text: 임베딩할 텍스트

        Returns:
            float 리스트 형태의 벡터
        """
        raise NotImplementedError

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        (선택 구현) 다수 텍스트에 대한 임베딩 벡터 리스트를 반환합니다.
        기본 구현은 embed를 반복 호출합니다.

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            벡터 리스트의 리스트
        """
        return [await self.embed(t) for t in texts]

    def embed_sync(self, text: str) -> List[float]:
        """
        단일 텍스트에 대한 임베딩 벡터를 반환합니다 (동기).

        [GEVENT] gevent 환경에서 사용하기 위한 동기 래퍼.
        기본 구현은 새 이벤트 루프를 생성하여 async embed를 실행합니다.

        Args:
            text: 임베딩할 텍스트

        Returns:
            float 리스트 형태의 벡터
        """
        return self._run_coroutine_sync(lambda: self.embed(text))
