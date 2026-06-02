"""graph/llm.py — OpenAI 클라이언트 래퍼 및 동시 실행 유틸.

- import 시점에는 절대 OpenAI 호출을 하지 않는다(키 없어도 import 되어야 함).
- 실제 네트워크 호출은 함수가 실행될 때만 발생한다.
- 공개 API: MODEL, has_real_key(), get_client(), structured_call(...), run_threaded(...)
"""

import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIError, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

# .env 로드는 import 시점에 1회만 수행(네트워크 호출 아님 — 환경변수만 읽음).
load_dotenv()

# 사용할 모델명. 환경변수로 덮어쓸 수 있고, 없으면 기본값 gpt-4o-mini.
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# get_client() 싱글톤 캐시(최초 호출 때 1회만 생성).
_client = None


def has_real_key() -> bool:
    """실제 사용 가능한 OpenAI 키가 설정돼 있는지 판정한다.

    OPENAI_API_KEY 가 존재하고, 플레이스홀더('sk-your-key')로 시작하지 않으면 True.
    키가 없거나 플레이스홀더면 False(이 경우 호출측은 mock 등으로 대체).
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return False
    # 'sk-your-key...' 같은 예시/플레이스홀더 키는 실제 키로 취급하지 않는다.
    if key.startswith("sk-your-key"):
        return False
    return True


def get_client() -> OpenAI:
    """OpenAI 클라이언트 싱글톤 반환.

    최초 호출 시에만 인스턴스를 만들어 모듈 전역에 캐시한다.
    (생성자 호출 자체는 네트워크 통신을 하지 않으므로 import 제약과 무관하나,
     안전하게 함수 실행 시점에만 생성한다.)
    """
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


@retry(
    # 일시적 오류(레이트리밋/타임아웃/API오류)에 대해 지수 백오프 + 지터로 재시도.
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
)
def structured_call(messages, schema, temperature=0.7):
    """구조화 출력(structured output) 호출.

    messages    : OpenAI chat messages 리스트 [{'role':..,'content':..}, ...]
    schema      : pydantic BaseModel 서브클래스(response_format 으로 사용)
    temperature : 샘플링 온도

    반환: 파싱된 pydantic 객체(resp.choices[0].message.parsed).
    일시적 오류는 tenacity 가 자동 재시도한다.
    """
    client = get_client()
    resp = client.beta.chat.completions.parse(
        model=MODEL,
        messages=messages,
        response_format=schema,
        temperature=temperature,
    )
    return resp.choices[0].message.parsed


def run_threaded(items, fn, max_workers=8):
    """items 각 원소에 fn 을 스레드풀로 동시 적용하고, 입력 순서대로 결과 리스트 반환.

    - executor.map 을 사용하므로 결과는 입력 순서가 보존된다.
    - 예외 처리는 호출측/ fn 내부 책임이다(여기서 None 으로 삼키지 않는다).
      fn 내부에서 자체적으로 try/except 하도록 설계하고, 여기서는 map 결과를 그대로 돌려준다.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fn, items))
