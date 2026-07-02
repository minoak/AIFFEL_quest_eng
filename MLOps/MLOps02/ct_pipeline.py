from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
import yfinance as yf
from google.cloud import bigquery
import os
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error


# ── 설정 ──
PROJECT_ID = "project-8b858d71-3e0d-4460-a22"
DATASET    = "mlops_practice"
TICKER     = "AAPL"

def extract(**context):
    # 1) yfinance로 원본 주가 당기기 (최근 2년치 일봉)
    df = yf.download(TICKER, period="2y", interval="1d", auto_adjust=False)
    if df.empty:
        raise ValueError(f"{TICKER}: 데이터를 못 가져옴 (네트워크/티커 확인)")

    # yfinance가 컬럼을 MultiIndex로 줄 때가 있어 평탄화
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()  # Date를 인덱스에서 컬럼으로
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    df["ticker"] = TICKER

    client = bigquery.Client(project=PROJECT_ID)

    # 2) 브론즈: 원본 그대로 적재 (손대지 않음, 매번 덮어씀)
    bronze_table = f"{PROJECT_ID}.{DATASET}.stock_bronze"
    client.load_table_from_dataframe(
        df,
        bronze_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"[extract] 브론즈 적재 완료: {len(df)}행 → {bronze_table}")

    # 3) 실버: 정제 + 피처 (결측 제거, 종가 기준 수익률/이동평균)
    silver = df[["date", "ticker", "open", "high", "low", "close", "volume"]].copy()
    silver = silver.dropna().sort_values("date")
    silver["return_1d"] = silver["close"].pct_change()       # 전일 대비 수익률
    silver["ma_5"]      = silver["close"].rolling(5).mean()  # 5일 이동평균
    silver["ma_20"]     = silver["close"].rolling(20).mean() # 20일 이동평균
    silver = silver.dropna().reset_index(drop=True)          # 롤링 초기 결측 제거

    silver_table = f"{PROJECT_ID}.{DATASET}.stock_silver"
    client.load_table_from_dataframe(
        silver,
        silver_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"[extract] 실버 적재 완료: {len(silver)}행 → {silver_table}")

def train(**context):
    client = bigquery.Client(project=PROJECT_ID)
    silver_table = f"{PROJECT_ID}.{DATASET}.stock_silver"  # 원본 (실험 후 복구)
     #silver_table = f"{PROJECT_ID}.{DATASET}.stock_silver_drifted"  # 드리프트 실험
    # 1) BigQuery 실버 읽기 (이번엔 '읽기' 방향)
    df = client.query(f"SELECT * FROM `{silver_table}` ORDER BY date").to_dataframe()
    print(f"[train] 실버 로드: {len(df)}행")

    # 2) 타깃 = 다음날 종가 (shift(-1)로 한 칸 당김)
    df["target"] = df["close"].shift(-1)
    df = df.dropna().reset_index(drop=True)

    features = ["open", "high", "low", "close", "volume", "return_1d", "ma_5", "ma_20"]
    X, y = df[features], df["target"]

    # 3) 워크포워드 분할: 앞 80% 학습 / 뒤 20% 검증 (시간순, 절대 안 섞음)
    split = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]
    print(f"[train] 분할: 학습 {len(X_train)}행 / 검증 {len(X_test)}행 (시간순)")

    # 4) 가벼운 모델 학습 (성능은 논외)
    model = LinearRegression()
    model.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"[train] 검증 MAE: {mae:.4f}")

    # 5) 챌린저 모델 저장 (타임스탬프 버전 + 피처 목록 함께)
    models_dir = os.path.expanduser("~/airflow/models")
    os.makedirs(models_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    challenger_path = os.path.join(models_dir, f"challenger_{ts}.joblib")
    joblib.dump({
        "model": model,
        "mae": mae,              
        "X_eval": X_test,       
        "y_eval": y_test,        
    }, challenger_path)
    
    print(f"[train] 챌린저 저장: {challenger_path}")

    # 다음 칸(evaluate)에 경로 전달 — return하면 Airflow가 XCom에 자동 저장
    return challenger_path

def evaluate(**context):
    models_dir = os.path.expanduser("~/airflow/models")

    # 1) train이 XCom에 남긴 챌린저 경로 꺼내기 (칸 간 소통)
    ti = context["ti"]
    challenger_path = ti.xcom_pull(task_ids="train")
    challenger = joblib.load(challenger_path)
    X_eval, y_eval = challenger["X_eval"], challenger["y_eval"]
    challenger_mae = mean_absolute_error(y_eval, challenger["model"].predict(X_eval))
    print(f"[evaluate] 챌린저 MAE: {challenger_mae:.4f}")

    # 2) 현행 챔피언 찾기 (고정 경로)
    champion_path = os.path.join(models_dir, "champion.joblib")

    # 3) 첫 실행엔 챔피언이 없음 → 챌린저 자동 승격
    if not os.path.exists(champion_path):
        print("[evaluate] 챔피언 없음 (첫 배포) → 챌린저 자동 통과")
        decision = "promote"
    else:
        champion = joblib.load(champion_path)
        champion_mae = mean_absolute_error(y_eval, champion["model"].predict(X_eval))
        print(f"[evaluate] 챔피언 MAE: {champion_mae:.4f}")
        # 4) 게이트 규칙: 챌린저 MAE가 더 낮으면(오차 작으면) 승격
        if challenger_mae < champion_mae:
            print(f"[evaluate] 챌린저 승 ({challenger_mae:.4f} < {champion_mae:.4f}) → 통과")
            decision = "promote"
        else:
            print(f"[evaluate] 챌린저 패 ({challenger_mae:.4f} >= {champion_mae:.4f}) → 기각")
            decision = "reject"

    # 5) 결정 + 어떤 모델인지를 deploy에 전달
    return {"decision": decision, "challenger_path": challenger_path}


def deploy(**context):
    import shutil
    models_dir = os.path.expanduser("~/airflow/models")
    champion_path = os.path.join(models_dir, "champion.joblib")

    # 1) evaluate의 결정 꺼내기
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="evaluate")
    decision = result["decision"]
    challenger_path = result["challenger_path"]

    # 2) 기각이면 아무것도 안 건드림 (기존 챔피언 유지 = 롤백)
    if decision == "reject":
        print("[deploy] 기각 → 배포 안 함, 기존 챔피언 유지")
        return

    # 3) 승격: 배포 전에 기존 챔피언 백업 (되돌릴 근거 남기기)
    if os.path.exists(champion_path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(models_dir, f"champion_backup_{ts}.joblib")
        shutil.copy2(champion_path, backup_path)
        print(f"[deploy] 기존 챔피언 백업: {backup_path}")

    # 4) 원자적 교체: 임시로 쓴 뒤 한 번에 rename (쓰다 만 파일이 챔피언 되는 사고 방지)
    tmp_path = champion_path + ".tmp"
    shutil.copy2(challenger_path, tmp_path)
    os.replace(tmp_path, champion_path)   # os.replace는 원자적
    print(f"[deploy] 챌린저 승격 완료 → 새 챔피언: {champion_path}")

# ── DAG 정의: 이 4개를 순서대로 엮는다 ──
with DAG(
    dag_id="ct_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule="0 9 * * *",          # 지금은 수동 실행만. 나중에 "@daily"로 바꿀 자리
    catchup=False,
    tags=["mlops", "practice"],
) as dag:

    t_extract  = PythonOperator(task_id="extract",  python_callable=extract)
    t_train    = PythonOperator(task_id="train",    python_callable=train)
    t_evaluate = PythonOperator(task_id="evaluate", python_callable=evaluate)
    t_deploy   = PythonOperator(task_id="deploy",   python_callable=deploy)

    # 흐름: extract → train → evaluate → deploy
    t_extract >> t_train >> t_evaluate >> t_deploy

