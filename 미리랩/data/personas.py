"""페르소나 로더.  Owner: data.

HF 'nvidia/Nemotron-Personas-Korea'(parquet) 한 샤드를 샘플링해
state.Persona 스키마 dict 리스트로 변환한다.

설계 원칙:
- 캐시 우선: 한 번 만든 페르소나는 personas_cache.json 에 저장하고
  같은 (n, seed) 요청이면 네트워크 없이 그대로 돌려준다(데모 안정성).
- import 시점에는 어떤 네트워크/IO 도 하지 않는다. 실제 다운로드는
  load_personas() 가 호출될 때, 그것도 캐시가 없을 때만 일어난다.
- 신호(signals) 파생은 순수 파이썬 결정론(같은 입력 -> 같은 출력)으로
  계산한다. LLM 호출 없음.

공개 API:
    load_personas(n=24, seed=42, force=False) -> list[Persona dict]
"""
from __future__ import annotations

import json
import re
import uuid
import hashlib
from pathlib import Path

import pandas as pd

# 이 파일이 위치한 data/ 디렉터리
_DATA_DIR = Path(__file__).resolve().parent
# (n, seed) 단위 캐시. config 가 일치하고 force 가 아니면 그대로 재사용.
_CACHE_PATH = _DATA_DIR / "personas_cache.json"

# HF 데이터셋 식별자
_HF_REPO = "nvidia/Nemotron-Personas-Korea"
_HF_REPO_TYPE = "dataset"


# ----------------------------------------------------------------------------
# 공개 함수
# ----------------------------------------------------------------------------
def load_personas(n: int = 24, seed: int = 42, force: bool = False) -> list[dict]:
    """가상 시민 n명을 만들어 반환한다.

    동작 순서:
      1) force 가 아니고 캐시 파일이 있으며 config(n, seed) 가 일치하면
         캐시를 읽어 즉시 반환한다(네트워크 호출 없음).
      2) 그렇지 않으면 HF 데이터셋에서 parquet 1개를 받아 n명을 샘플링하고
         Persona dict 로 변환한 뒤 캐시에 저장하고 반환한다.
      3) 네트워크 실패 + 사용 가능한 캐시도 없으면 RuntimeError 를 던진다
         (이 경우 호출 측은 데모(mock) 모드로 폴백하면 된다).

    Args:
        n: 만들 페르소나 수.
        seed: 샘플링 random_state (재현성).
        force: True 면 캐시를 무시하고 다시 다운로드/생성한다.

    Returns:
        state.Persona 스키마를 따르는 dict 리스트(길이 <= n).
    """
    # 1) 캐시 우선 ---------------------------------------------------------
    if not force:
        cached = _load_cache(n, seed)
        if cached is not None:
            return cached

    # 2) HF 에서 새로 생성 -------------------------------------------------
    try:
        personas = _build_from_hf(n, seed)
    except Exception as e:  # 네트워크/데이터셋/파싱 등 모든 실패를 포괄
        # 3) 실패 시: 마지막 안전망으로 캐시라도 있으면(config 불일치라도) 쓴다.
        salvage = _load_cache(n, seed, ignore_config=True)
        if salvage is not None:
            return salvage[:n] if len(salvage) > n else salvage
        raise RuntimeError(
            "페르소나 로드 실패: 네트워크/데이터셋 확인. 데모(mock) 모드를 쓰세요."
        ) from e

    # 캐시에 저장(실패해도 반환은 정상 진행)
    _save_cache(personas, n, seed)
    return personas


# ----------------------------------------------------------------------------
# 캐시 입출력
# ----------------------------------------------------------------------------
def _load_cache(n: int, seed: int, ignore_config: bool = False) -> list[dict] | None:
    """캐시 파일을 읽어 config 가 일치하면 personas 리스트를 반환.

    ignore_config=True 면 config 일치 여부와 무관하게(있기만 하면) 반환한다.
    파일이 없거나 깨졌으면 None.
    """
    if not _CACHE_PATH.exists():
        return None
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    personas = blob.get("personas")
    if not isinstance(personas, list) or not personas:
        return None

    if ignore_config:
        return personas

    cfg = blob.get("config") or {}
    if cfg.get("n") == n and cfg.get("seed") == seed:
        return personas
    return None


def _save_cache(personas: list[dict], n: int, seed: int) -> None:
    """페르소나 리스트와 config 를 캐시 파일에 저장한다(실패는 조용히 무시)."""
    payload = {"config": {"n": n, "seed": seed}, "personas": personas}
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 캐시 저장 실패가 기능을 막아선 안 됨


# ----------------------------------------------------------------------------
# HF 다운로드 + 샘플링
# ----------------------------------------------------------------------------
def _build_from_hf(n: int, seed: int) -> list[dict]:
    """HF 데이터셋에서 parquet 1개만 받아 n명을 샘플링하고 변환한다."""
    # import 는 함수 안에서: 모듈 import 시 huggingface_hub 가 없어도 되게.
    from huggingface_hub import hf_hub_download, list_repo_files

    # 저장소의 .parquet 파일 목록 -> 첫 파일 1개만 사용(전체 2GB 회피).
    files = list_repo_files(_HF_REPO, repo_type=_HF_REPO_TYPE)
    parquet_files = sorted(f for f in files if f.endswith(".parquet"))
    if not parquet_files:
        raise RuntimeError("데이터셋에서 parquet 파일을 찾지 못했습니다.")

    local_path = hf_hub_download(
        repo_id=_HF_REPO,
        repo_type=_HF_REPO_TYPE,
        filename=parquet_files[0],
    )

    df = pd.read_parquet(local_path)
    if len(df) == 0:
        raise RuntimeError("parquet 파일이 비어 있습니다.")

    # n 이 데이터보다 많으면 가진 만큼만. random_state 로 재현성 확보.
    sample = df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)

    personas: list[dict] = []
    for idx, (_, row) in enumerate(sample.iterrows()):
        personas.append(_row_to_persona(row, idx))
    return personas


# ----------------------------------------------------------------------------
# 행 -> Persona 변환
# ----------------------------------------------------------------------------
def _g(row, key: str, default=""):
    """행에서 안전하게 값을 꺼낸다(없거나 NaN 이면 default)."""
    try:
        val = row.get(key, default)
    except AttributeError:
        # row 가 dict 가 아닌 경우(pandas Series 인덱싱)
        val = row[key] if key in getattr(row, "index", []) else default
    # NaN / None 처리
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


def _to_int(val, default: int = 0) -> int:
    """안전한 정수 캐스팅."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _to_str(val, default: str = "") -> str:
    """안전한 문자열 캐스팅(공백 정리)."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return s if s else default


def _extract_name(persona_text: str, idx: int) -> str:
    """페르소나 텍스트에서 'XXX 씨' 패턴으로 이름을 뽑는다.

    한글 이름(2~4자) + 선택적 공백 + '씨' 를 찾는다. 실패 시 '시민{idx+1}'.
    """
    if persona_text:
        # 예: "전기태 씨는", "최은지 씨는" -> 이름 부분만 캡처
        m = re.search(r"([가-힣]{2,4})\s*씨", persona_text)
        if m:
            return m.group(1)
    return f"시민{idx + 1}"


def _row_to_persona(row, idx: int) -> dict:
    """HF 데이터셋 한 행을 state.Persona 스키마 dict 로 변환한다."""
    # --- 인구통계(demographics) ---
    sex = _to_str(_g(row, "sex"))
    age = _to_int(_g(row, "age"), default=0)
    marital_status = _to_str(_g(row, "marital_status"))
    family_type = _to_str(_g(row, "family_type"))
    housing_type = _to_str(_g(row, "housing_type"))
    education_level = _to_str(_g(row, "education_level"))
    occupation = _to_str(_g(row, "occupation"))
    district = _to_str(_g(row, "district"))
    province = _to_str(_g(row, "province"))

    demographics = {
        "sex": sex,
        "age": age,
        "marital_status": marital_status,
        "family_type": family_type,
        "housing_type": housing_type,
        "education_level": education_level,
        "occupation": occupation,
        "district": district,
        "province": province,
    }

    # --- persona_text: 요약(persona) + 직업 페르소나(professional) 결합, 600자 컷 ---
    summary = _to_str(_g(row, "persona"))
    professional = _to_str(_g(row, "professional_persona"))
    parts = [p for p in (summary, professional) if p]
    persona_text = "\n".join(parts)
    if len(persona_text) > 600:
        persona_text = persona_text[:600].rstrip()

    # --- name: 'XXX 씨' 추출, 실패 시 시민N ---
    # 추출은 요약 우선, 없으면 직업 페르소나에서.
    name = _extract_name(summary or professional, idx)

    # --- description: 한 줄 요약 ---
    description = f"{age}세 {sex} · {marital_status} · {occupation} · {province} {district}"

    # --- 고유 id (행의 uuid 가 있으면 그대로, 없으면 새로 발급) ---
    pid = _to_str(_g(row, "uuid")) or str(uuid.uuid4())

    # --- signals (결정론적 파생) ---
    signals = _derive_signals(row, pid)

    # --- meta: 프롬프트엔 안 넣는 부가 컬럼 중 있는 것만 ---
    meta = {}
    for key in (
        "cultural_background",
        "hobbies_and_interests",
        "career_goals_and_ambitions",
        "family_persona",
    ):
        v = _to_str(_g(row, key))
        if v:
            meta[key] = v

    return {
        "id": pid,
        "name": name,
        "description": description,
        "sources": [],
        "demographics": demographics,
        "persona_text": persona_text,
        "signals": signals,
        "meta": meta,
    }


# ----------------------------------------------------------------------------
# 신호(signals) 파생 — 순수 파이썬 결정론
# ----------------------------------------------------------------------------
# 학력 티어(높을수록 디지털 친화/소득 기대 ↑)
_EDU_TIER = {
    "초등학교": 0.30,
    "중학교": 0.45,
    "고등학교": 0.60,
    "전문대학": 0.75,
    "2년제 대학교": 0.75,
    "대학교": 0.85,
    "4년제 대학교": 0.85,
    "대학원": 1.00,
    "석사": 1.00,
    "박사": 1.00,
}

# 디지털 친화도를 끌어올리는 직업 키워드
_DIGITAL_UP_KW = (
    "IT", "개발", "프로그래", "소프트웨어", "데이터", "디자인", "엔지니어",
    "사무", "회계", "경영", "기획", "마케팅", "연구", "전문", "관리자", "교사", "교수",
)
# 디지털 친화도를 끌어내리는 직업 키워드
_DIGITAL_DOWN_KW = (
    "무직", "농림", "어업", "농업", "축산", "단순", "노무", "하역", "적재",
    "청소", "경비", "은퇴", "학생",
)

# 소득 'high' 로 보는 직업 키워드
_INCOME_HIGH_KW = (
    "전문", "의사", "변호사", "관리자", "임원", "교수", "경영", "회계사", "약사",
    "판사", "검사", "연구", "개발", "엔지니어",
)
# 소득 'low' 로 보는 직업/상태 키워드
_INCOME_LOW_KW = ("무직", "학생", "은퇴", "단순", "노무", "실업")


def _edu_tier(education_level: str) -> float:
    """학력 문자열 -> 0~1 티어값(부분 일치 허용, 기본 0.55)."""
    if not education_level:
        return 0.55
    for key, val in _EDU_TIER.items():
        if key in education_level:
            return val
    return 0.55


def _age_factor(age: int) -> float:
    """나이 -> 디지털 친화 기본 점수(0~1).

    20대 이하 높음 -> 50 이후 하락 -> 65 이후 급락.
    """
    if age <= 0:
        return 0.55  # 나이 정보 없음: 중간값
    if age < 30:
        return 0.95
    if age < 50:
        # 30~49: 0.95 에서 0.75 로 선형 하락
        return 0.95 - (age - 30) * (0.20 / 20.0)
    if age < 65:
        # 50~64: 0.70 에서 0.40 으로 하락
        return 0.70 - (age - 50) * (0.30 / 15.0)
    # 65 이상: 0.30 에서 급락(85세에 0.10)
    return max(0.10, 0.30 - (age - 65) * (0.20 / 20.0))


def _kw_hit(text: str, keywords) -> bool:
    """text 안에 키워드 중 하나라도 들어 있으면 True."""
    return any(kw in text for kw in keywords)


def _clamp01(x: float) -> float:
    """0~1 범위로 자른다."""
    return max(0.0, min(1.0, x))


def _digital_literacy(age: int, education_level: str, occupation: str) -> float:
    """디지털 리터러시(0~1) 결정론적 추정.

    나이 기본점수 × 학력 보정 × 직업 키워드 보정.
    """
    base = _age_factor(age)
    edu = _edu_tier(education_level)
    # 학력은 0.6~1.0 배율로 완만하게 반영(나이 영향이 더 크도록)
    edu_mult = 0.6 + 0.4 * edu

    score = base * edu_mult

    # 직업 키워드 가산/감산
    if occupation:
        if _kw_hit(occupation, _DIGITAL_UP_KW):
            score += 0.10
        if _kw_hit(occupation, _DIGITAL_DOWN_KW):
            score -= 0.12

    return round(_clamp01(score), 3)


def _income_level(occupation: str, education_level: str) -> str:
    """소득 수준 'low' / 'mid' / 'high' 추정(직업 우선, 학력 보정)."""
    occ = occupation or ""
    # 무직/학생/은퇴 -> low
    if _kw_hit(occ, _INCOME_LOW_KW):
        return "low"
    # 전문직/관리자 -> high
    if _kw_hit(occ, _INCOME_HIGH_KW):
        return "high"
    # 학력 보정: 대학원 이상이면 mid 를 high 로 끌어올림
    if education_level and ("대학원" in education_level
                            or "석사" in education_level
                            or "박사" in education_level):
        return "high"
    return "mid"


def _government_trust(pid: str) -> float:
    """정부 신뢰도(0~1) 결정론적 지터.

    0.5 ± 0.10 범위, uuid 해시 기반(같은 id -> 같은 값).
    """
    # 안정적 해시: hashlib(파이썬 hash() 는 실행마다 솔트가 달라짐).
    h = int(hashlib.md5(pid.encode("utf-8")).hexdigest(), 16)
    jitter = (h % 21 - 10) / 100.0  # -0.10 ~ +0.10
    return round(_clamp01(0.5 + jitter), 3)


def _social_network(family_type: str, occupation: str) -> list[str]:
    """가구형태/직업 기반 사회적 연결망 태그 리스트(중복 제거, 순서 유지)."""
    tags: list[str] = []
    ft = family_type or ""
    occ = occupation or ""

    # 가구형태 기반
    if "혼자" in ft or "1인" in ft or "단독" in ft:
        tags += ["복지관", "경로당"]
    if "자녀" in ft:
        tags += ["가족 단톡방"]
    if "배우자" in ft:
        tags += ["부부 모임"]
    if "부모" in ft:
        tags += ["가족 단톡방"]

    # 직업 기반
    if _kw_hit(occ, ("사무", "회계", "경영", "기획", "관리", "전문")):
        tags += ["직장 동료"]
    if _kw_hit(occ, ("농림", "농업", "어업", "축산")):
        tags += ["마을 이장", "농협"]
    if _kw_hit(occ, ("교사", "교수", "강사")):
        tags += ["학교 동료"]
    if "학생" in occ:
        tags += ["학교 친구", "온라인 커뮤니티"]
    if "무직" in occ or "은퇴" in occ:
        tags += ["동네 이웃"]

    # 비어 있으면 기본값
    if not tags:
        tags = ["동네 이웃"]

    # 중복 제거(순서 유지)
    seen = set()
    uniq: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _derive_signals(row, pid: str) -> dict:
    """행에서 signals dict 를 결정론적으로 파생한다.

    Returns:
        {digital_literacy: float, income_level: str,
         government_trust: float, social_network: list[str]}
    """
    age = _to_int(_g(row, "age"), default=0)
    education_level = _to_str(_g(row, "education_level"))
    occupation = _to_str(_g(row, "occupation"))
    family_type = _to_str(_g(row, "family_type"))

    return {
        "digital_literacy": _digital_literacy(age, education_level, occupation),
        "income_level": _income_level(occupation, education_level),
        "government_trust": _government_trust(pid),
        "social_network": _social_network(family_type, occupation),
    }
