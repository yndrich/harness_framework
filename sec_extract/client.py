"""SEC EDGAR HTTP 클라이언트 (표준 라이브러리만 사용).

SEC 정책 준수:
- 모든 요청에 연락처가 담긴 User-Agent 헤더 필수 (없으면 403).
- IP 당 초당 10회 제한 -> 요청 간 최소 간격을 둔다.
- 403/429/5xx 에 지수 백오프 재시도.
- 응답은 URL 기준으로 디스크 캐시 (재실행 비용 절감, 재현성 확보).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# SEC 는 실제 연락 이메일이 담긴 User-Agent 를 요구한다.
DEFAULT_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "sec-extract/0.1 (rnldbal12@gmail.com)"
)
DEFAULT_CACHE_DIR = Path(os.environ.get("SEC_CACHE_DIR", ".sec_cache"))


class SecClient:
    MIN_INTERVAL = 0.12   # 요청 간 최소 간격(초) -> < 10 req/s
    MAX_RETRIES = 5
    RETRY_STATUS = {403, 429, 500, 502, 503, 504}

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT,
                 cache_dir: Path | str = DEFAULT_CACHE_DIR,
                 use_cache: bool = True) -> None:
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self._last_request = 0.0
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- 캐시 ------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{h}.json"

    def get_json(self, url: str, refresh: bool = False):
        if self.use_cache and not refresh:
            p = self._cache_path(url)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        raw = self._fetch(url)
        data = json.loads(raw)
        if self.use_cache:
            self._cache_path(url).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        return data

    # ---- 저수준 요청 -----------------------------------------------------
    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self.MIN_INTERVAL - (now - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/json, text/plain, */*",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                    if resp.info().get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    return data.decode("utf-8")
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in self.RETRY_STATUS:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(1.0 * (attempt + 1))
                continue
        raise RuntimeError(f"Failed to fetch {url}: {last_err}")
