"""모델 라우팅의 정책 신호에 쓰는 가벼운 토큰 정규화 유틸리티.

형태소 분석기를 런타임 의존성으로 추가하지 않고도, 한국어 조사 때문에 같은
핵심어가 서로 다른 신호로 저장되는 가장 흔한 경우를 보수적으로 줄인다.
"""

from __future__ import annotations

import re
import unicodedata


# 짧은 대표 예문에서 `권한과`와 `권한을`을 별개의 입력군 신호로 취급하면
# 오분류 위험이 크다. 어근이 두 글자 이상 남는 경우에만 뒤의 조사만 제거한다.
_KOREAN_PARTICLE_SUFFIXES = (
    "으로부터",
    "에서부터",
    "에게서",
    "으로는",
    "으로도",
    "에게는",
    "에게도",
    "이라도",
    "이라고",
    "이라면",
    "에서",
    "에게",
    "부터",
    "까지",
    "처럼",
    "보다",
    "하고",
    "이며",
    "으로",
    "은",
    "는",
    "을",
    "를",
    "이",
    "가",
    "의",
    "에",
    "와",
    "과",
    "도",
    "만",
    "로",
    "랑",
    "이나",
    "나",
    "든지",
    "든",
    "마다",
)


def normalize_model_routing_lexical_text(value: str) -> str:
    """Normalize case and Unicode without exposing or retaining raw inputs."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def canonicalize_model_routing_lexical_token(value: str) -> str:
    """Return one token with a trailing Korean particle removed when safe."""
    token = normalize_model_routing_lexical_text(value)
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    for suffix in _KOREAN_PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def tokenize_model_routing_lexical_text(value: str) -> list[str]:
    """Tokenize a policy/query string into canonical single-word signals."""
    normalized = normalize_model_routing_lexical_text(value)
    return [
        canonical
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if len(token) >= 2
        if (canonical := canonicalize_model_routing_lexical_token(token))
    ]
