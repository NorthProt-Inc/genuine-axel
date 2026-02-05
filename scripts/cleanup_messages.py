#!/usr/bin/env python3
import sqlite3
import json
import os
import re
import shutil
import logging
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Iterator, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai 패키지가 필요합니다.")
    print("  pip install google-genai")
    sys.exit(1)

from dotenv import load_dotenv

# 로그 레벨 조정 - HTTP 요청 로그 숨김
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
DB_PATH = DATA_ROOT / "sqlite" / "sqlite_memory.db"
CHECKPOINT_FILE = DATA_ROOT / "cleanup_checkpoint.json"
BACKUP_DIR = Path("/home/northprot/backups/axnmihn")

BATCH_SIZE = 50
PARALLEL_WORKERS = 10  # 동시 처리 수
MODEL_NAME = "gemini-3-pro-preview"

CLEANUP_PROMPT = """이 대화 메시지를 정리해주세요:
1. 불필요한 로그/메타정보 제거 (예: [System Log: ...], 타임스탬프, 에러 스택트레이스)
2. 핵심 내용만 유지
3. 대화 맥락과 감정 보존
4. 500자 이내로 압축 (이미 짧으면 그대로)
5. 원문이 한국어면 한국어로, 영어면 영어로 유지

정리된 메시지만 출력하세요. 설명이나 부가 텍스트 없이 정리된 내용만 반환하세요.

원본:
{content}"""


class KeyRotator:
    """3개 API 키 로테이션 (thread-safe)"""

    def __init__(self):
        load_dotenv(PROJECT_ROOT / ".env")

        self.keys = [
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_API_KEY_1"),
            os.getenv("GEMINI_API_KEY_2"),
        ]
        self.keys = [k for k in self.keys if k]

        if not self.keys:
            raise ValueError("GEMINI_API_KEY가 .env에 없습니다")

        self.current_idx = 0
        self.lock = threading.Lock()
        self.call_counts = {i: 0 for i in range(len(self.keys))}

        # 각 키별 클라이언트 미리 생성
        self.clients = [genai.Client(api_key=k) for k in self.keys]
        logger.info(f"API 키 {len(self.keys)}개 로드됨")

    def get_client(self) -> genai.Client:
        with self.lock:
            client = self.clients[self.current_idx]
            self.call_counts[self.current_idx] += 1
            self.current_idx = (self.current_idx + 1) % len(self.keys)
            return client

    def get_stats(self) -> dict:
        return {f"key_{i}": cnt for i, cnt in self.call_counts.items()}


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            checkpoint = json.load(f)
            logger.info(f"체크포인트 로드: ID {checkpoint.get('last_processed_id', 0)}, "
                       f"{checkpoint.get('processed_count', 0)}개 처리됨")
            return checkpoint
    return {"last_processed_id": 0, "processed_count": 0}


def save_checkpoint(msg_id: int, count: int, started_at: str):
    data = {
        "last_processed_id": msg_id,
        "processed_count": count,
        "started_at": started_at,
        "updated_at": datetime.now().isoformat()
    }
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def batched(iterable, n: int) -> Iterator:
    """리스트를 n개씩 묶어서 반환"""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == n:
            yield batch
            batch = []
    if batch:
        yield batch


def preprocess_content(content: str) -> str:
    """LLM 호출 전 간단한 정규식 정리"""
    if not content:
        return content

    # [System Log: ...] 패턴 제거
    content = re.sub(r'\[System Log:.*?\]', '', content, flags=re.DOTALL)

    # System Log: ... 패턴 제거
    content = re.sub(r'^System Log:.*$', '', content, flags=re.MULTILINE)

    # 연속 개행 축소
    content = re.sub(r'\n{3,}', '\n\n', content)

    # 앞뒤 공백 제거
    content = content.strip()

    return content


def clean_single_message(msg_id: int, content: str, client: genai.Client, max_retries: int = 2) -> Tuple[int, Optional[str], str]:
    """단일 메시지 정리 (병렬 처리용)

    Returns: (msg_id, cleaned_content, status)
    status: 'updated', 'skipped', 'error'
    """
    if not content or len(content.strip()) < 10:
        return (msg_id, content, 'skipped')

    # 전처리
    preprocessed = preprocess_content(content)

    # 이미 충분히 짧으면 전처리만 적용
    if len(preprocessed) < 100:
        if preprocessed != content:
            return (msg_id, preprocessed, 'updated')
        return (msg_id, content, 'skipped')

    prompt = CLEANUP_PROMPT.format(content=preprocessed)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=1024,
                    http_options={"timeout": 60000},  # 60초 타임아웃
                )
            )

            if response.text:
                cleaned = response.text.strip()
                if len(cleaned) < 5 or cleaned.startswith("Error"):
                    return (msg_id, preprocessed, 'updated' if preprocessed != content else 'skipped')
                return (msg_id, cleaned, 'updated' if cleaned != content else 'skipped')

        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str or "quota" in error_str:
                time.sleep((attempt + 1) * 5)
            elif "timeout" in error_str:
                logger.warning(f"메시지 {msg_id} 타임아웃 (시도 {attempt + 1})")
                time.sleep(2)
            else:
                time.sleep(2)

    # 모든 재시도 실패시 전처리된 원본 반환
    return (msg_id, preprocessed, 'updated' if preprocessed != content else 'skipped')


def create_backup() -> Path:
    """DB 백업 생성"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"sqlite_memory_before_cleanup_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_path)
    logger.info(f"백업 생성: {backup_path}")

    return backup_path


def get_message_stats(conn: sqlite3.Connection) -> dict:
    """메시지 통계 조회"""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM messages")
    total = cursor.fetchone()[0]

    cursor.execute("""
        SELECT
            CASE
                WHEN LENGTH(content) < 100 THEN '<100'
                WHEN LENGTH(content) < 500 THEN '100-500'
                WHEN LENGTH(content) < 1000 THEN '500-1K'
                WHEN LENGTH(content) < 5000 THEN '1K-5K'
                ELSE '>5K'
            END as size_range,
            COUNT(*) as cnt
        FROM messages
        GROUP BY size_range
        ORDER BY size_range
    """)

    distribution = {row[0]: row[1] for row in cursor.fetchall()}

    return {"total": total, "distribution": distribution}


def run_cleanup(dry_run: bool = False, limit: Optional[int] = None) -> dict:
    """메시지 정리 실행 (병렬 처리)"""
    if not DB_PATH.exists():
        logger.error(f"DB 없음: {DB_PATH}")
        return {"error": "Database not found"}

    start_time = datetime.now()
    started_at = start_time.isoformat()

    results = {
        "started_at": started_at,
        "dry_run": dry_run,
    }

    # 백업 생성
    if not dry_run:
        backup_path = create_backup()
        results["backup_path"] = str(backup_path)

    # 체크포인트 로드
    checkpoint = load_checkpoint()
    start_id = checkpoint.get("last_processed_id", 0)
    processed_count = checkpoint.get("processed_count", 0)

    if start_id > 0:
        logger.info(f"ID {start_id} 이후부터 재개, 이미 {processed_count}개 처리됨")

    # 키 로테이터 초기화
    rotator = KeyRotator()

    conn = sqlite3.connect(DB_PATH, timeout=60.0)

    try:
        # 처리 전 통계
        stats_before = get_message_stats(conn)
        results["before"] = stats_before
        logger.info(f"처리 전: 총 {stats_before['total']}개 메시지")

        if dry_run:
            logger.info("Dry run 모드 - 실제 수정 없음")
            results["status"] = "dry_run"
            return results

        cursor = conn.cursor()

        # 메시지 조회
        query = "SELECT id, content FROM messages WHERE id > ? ORDER BY id"
        params = [start_id]
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        messages = cursor.fetchall()

        total_to_process = len(messages)
        logger.info(f"처리할 메시지: {total_to_process}개 (병렬 {PARALLEL_WORKERS}개)")

        if total_to_process == 0:
            logger.info("처리할 메시지 없음")
            results["status"] = "no_messages"
            return results

        updated = 0
        skipped = 0
        errors = 0

        for batch_num, batch in enumerate(batched(messages, BATCH_SIZE)):
            batch_start = time.time()
            batch_results: List[Tuple[int, Optional[str], str]] = []

            # 병렬 처리
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
                futures = {}
                for msg_id, content in batch:
                    client = rotator.get_client()
                    future = executor.submit(clean_single_message, msg_id, content, client)
                    futures[future] = msg_id

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        batch_results.append(result)
                    except Exception as e:
                        msg_id = futures[future]
                        logger.error(f"메시지 {msg_id} 처리 실패: {e}")
                        errors += 1

            # DB 업데이트 (순차적으로)
            for msg_id, cleaned, status in batch_results:
                if status == 'updated' and cleaned:
                    cursor.execute(
                        "UPDATE messages SET content = ? WHERE id = ?",
                        (cleaned, msg_id)
                    )
                    updated += 1
                elif status == 'skipped':
                    skipped += 1
                else:
                    errors += 1

            processed_count += len(batch)

            # 배치 커밋 및 체크포인트
            conn.commit()
            last_id = batch[-1][0]
            save_checkpoint(last_id, processed_count, started_at)

            batch_time = time.time() - batch_start
            progress = processed_count / (total_to_process + start_id) * 100
            logger.info(f"배치 {batch_num + 1}: {len(batch)}개 처리, "
                       f"진행률 {progress:.1f}%, 소요 {batch_time:.1f}초")

        # 체크포인트 삭제 (완료시)
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
            logger.info("체크포인트 삭제됨 (완료)")

        # 처리 후 통계
        stats_after = get_message_stats(conn)
        results["after"] = stats_after

        results["processed"] = processed_count
        results["updated"] = updated
        results["skipped"] = skipped
        results["errors"] = errors
        results["key_usage"] = rotator.get_stats()
        results["status"] = "success"

    except KeyboardInterrupt:
        results["status"] = "interrupted"
        results["processed"] = processed_count
        logger.info("중단됨. 다음 실행시 체크포인트에서 재개됩니다.")

    except Exception as e:
        logger.error(f"처리 실패: {e}")
        results["status"] = "error"
        results["error"] = str(e)

    finally:
        conn.close()
        elapsed = (datetime.now() - start_time).total_seconds()
        results["elapsed_seconds"] = round(elapsed, 1)
        logger.info(f"총 소요시간: {elapsed:.1f}초")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="메시지 정리 스크립트 - LLM으로 대화 메시지 요약/정리 (병렬 처리)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/cleanup_messages.py              # 전체 실행
  python scripts/cleanup_messages.py --dry-run    # 통계만 확인
  python scripts/cleanup_messages.py --limit 100  # 100개만 처리 (테스트)
  python scripts/cleanup_messages.py --json       # JSON 출력
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 수정 없이 통계만 확인"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="처리할 최대 메시지 수 (테스트용)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="결과를 JSON으로 출력"
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="체크포인트 삭제 후 처음부터 시작"
    )

    args = parser.parse_args()

    if args.reset_checkpoint and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("체크포인트 삭제됨")

    results = run_cleanup(dry_run=args.dry_run, limit=args.limit)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print()
        if results.get("status") == "success":
            print("메시지 정리 완료")
            print(f"  처리: {results.get('processed', 0)}개")
            print(f"  수정: {results.get('updated', 0)}개")
            print(f"  스킵: {results.get('skipped', 0)}개")
            print(f"  에러: {results.get('errors', 0)}개")
            print(f"  소요: {results.get('elapsed_seconds', 0)}초")
            if results.get("backup_path"):
                print(f"  백업: {results['backup_path']}")
        elif results.get("status") == "dry_run":
            print("메시지 통계 (dry run)")
            before = results.get("before", {})
            print(f"  총 메시지: {before.get('total', 0)}개")
            print("  크기 분포:")
            for size, cnt in before.get("distribution", {}).items():
                print(f"    {size}: {cnt}개")
        elif results.get("status") == "interrupted":
            print("중단됨")
            print(f"  처리됨: {results.get('processed', 0)}개")
            print("  다음 실행시 체크포인트에서 재개됩니다.")
        else:
            print(f"실패: {results.get('error', 'Unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
