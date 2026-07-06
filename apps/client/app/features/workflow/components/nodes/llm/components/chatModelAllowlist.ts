export const CHAT_MODEL_ALLOWLISTS = {
  openai: [
    'gpt-5.5', // 최신 프런티어
    'gpt-5.5-pro', // 최신 고성능
    'gpt-5.4-pro', // 전문 작업용 Pro
    'gpt-5.4', // 전문 작업용
    'gpt-5.4-mini', // 효율형
    'gpt-5.4-nano', // 초경량
    'gpt-5.2', // 범용 플래그십
    'gpt-5.1', // 코딩/명령 이행 강화
    'gpt-5', // GPT-5 시리즈 시작
    'o3-pro', // 초고도 추론
    'o3', // 논리 특화
    'gpt-4.1', // 100만 토큰 컨텍스트
    'gpt-4o', // 멀티모달 표준
    'gpt-5-mini', // 효율 모델
    'gpt-5-nano', // 초경량
    'gpt-4.1-mini', // 경량 GPT-4급
    'gpt-4o-mini', // 저렴한 멀티모달
  ],
  anthropic: [
    'claude-fable-5', // 최신 최상위
    'claude-opus-4-8', // 엔터프라이즈/에이전트
    'claude-opus-4-7', // 고성능 안정화
    'claude-opus-4-6', // 고성능
    'claude-opus-4-5-20251101', // Opus 4.5
    'claude-sonnet-5', // 최신 균형형
    'claude-sonnet-4-6', // 안정 균형형
    'claude-sonnet-4-5-20250929', // 에이전트/컴퓨터 제어
    'claude-haiku-4-5-20251001', // 최신 경량
    'claude-haiku-4-5', // 경량 alias
  ],
  google: [
    'gemini-3.5-flash', // 최신 속도형
    'gemini-3.1-pro-preview', // 최신 고성능
    'gemini-3.1-flash-lite', // 최신 효율형
    'gemini-3-flash-preview', // Gemini 3 Flash
    'gemini-2.5-pro', // 대형 컨텍스트
    'gemini-2.5-flash', // 범용 속도형
    'gemini-2.5-flash-lite', // 초경량
  ],
} as const;

export const CHAT_MODEL_ALLOWLIST_SETS = {
  openai: new Set<string>(CHAT_MODEL_ALLOWLISTS.openai),
  anthropic: new Set<string>(CHAT_MODEL_ALLOWLISTS.anthropic),
  google: new Set<string>(CHAT_MODEL_ALLOWLISTS.google),
} as const;
