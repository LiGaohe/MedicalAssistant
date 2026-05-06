import asyncio
import aiohttp
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from . import UMLSCandidate, UMLSConcept, UMLSSearchResult
from ...utils.logger import logger


class AsyncUMLSClient:
    UMLS_API_BASE = "https://uts-ws.nlm.nih.gov/rest"
    UMLS_SERVICE = "http://umlsks.nlm.nih.gov"
    TGT_LIFETIME_HOURS = 7

    def __init__(
        self,
        api_key: str,
        cache_service: Optional[Any] = None,
        request_timeout: int = 30,
        max_retries: int = 3,
        rate_limit_delay: float = 0.1,
        max_concurrent: int = 5
    ):
        self.api_key = api_key
        self.cache_service = cache_service
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self.max_concurrent = max_concurrent
        self._last_request_time = 0

        self._tgt_url: Optional[str] = None
        self._tgt_expires_at: Optional[datetime] = None
        self._tgt_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info(f"AsyncUMLSClient initialized with max_concurrent={max_concurrent}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("AsyncUMLSClient session closed")

    async def _get_service_ticket(self) -> str:
        async with self._tgt_lock:
            if self._tgt_url and self._tgt_expires_at and datetime.now() < self._tgt_expires_at:
                logger.debug("Reusing cached TGT")
                try:
                    return await self._get_st_from_tgt(self._tgt_url)
                except Exception as e:
                    logger.warning(f"Failed to get ST from cached TGT: {e}, will obtain new TGT")
                    self._tgt_url = None
                    self._tgt_expires_at = None

            logger.debug("Obtaining new service ticket from UMLS")

            auth_url = "https://utslogin.nlm.nih.gov/cas/v1/api-key"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {"apikey": self.api_key}

            for attempt in range(self.max_retries):
                try:
                    session = await self._get_session()

                    async with session.post(
                        auth_url,
                        data=data,
                        headers=headers,
                        allow_redirects=False
                    ) as response:
                        logger.debug(f"TGT request status: {response.status}")

                        if response.status in [200, 201]:
                            tgt_url = response.headers.get("Location")
                            if not tgt_url:
                                logger.warning("No Location header in TGT response")
                                continue

                            logger.debug(f"Got TGT URL: {tgt_url}")

                            self._tgt_url = tgt_url
                            self._tgt_expires_at = datetime.now() + timedelta(hours=self.TGT_LIFETIME_HOURS)
                            logger.debug(f"TGT cached, expires at: {self._tgt_expires_at}")

                            return await self._get_st_from_tgt(tgt_url)
                        else:
                            text = await response.text()
                            logger.warning(f"TGT request failed with status {response.status}: {text[:100]}")

                except aiohttp.ClientError as e:
                    logger.warning(f"TGT request attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)

            raise RuntimeError("Failed to obtain service ticket from UMLS after max retries")

    async def _get_st_from_tgt(self, tgt_url: str) -> str:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        session = await self._get_session()

        async with session.post(
            tgt_url,
            data={"service": self.UMLS_SERVICE},
            headers=headers
        ) as response:
            text = await response.text()
            logger.debug(f"ST request status: {response.status}, body: {text[:100]}")

            if response.status == 200 and text:
                logger.debug("Successfully obtained service ticket")
                return text.strip()
            else:
                raise RuntimeError(f"Service ticket request failed: {response.status}")

    async def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        url = f"{self.UMLS_API_BASE}{endpoint}"
        logger.debug(f"Making async request to: {url}")

        for attempt in range(self.max_retries):
            await self._rate_limit()

            service_ticket = await self._get_service_ticket()

            request_params = {"ticket": service_ticket}
            if params:
                request_params.update(params)

            try:
                session = await self._get_session()

                async with session.get(url, params=request_params) as response:
                    logger.debug(f"Response status: {response.status}")

                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        logger.warning("Authentication failed (invalid ST), getting new ticket")
                        continue
                    elif response.status == 404:
                        logger.debug(f"Resource not found: {endpoint}")
                        return None
                    else:
                        text = await response.text()
                        logger.warning(f"Request failed with status {response.status}: {text[:200]}")
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(1)

            except aiohttp.ClientError as e:
                logger.warning(f"Request attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)

        return None

    async def search_term(
        self,
        term: str,
        language: str = "CHI",
        sabs: Optional[List[str]] = None,
        search_type: str = "words",
        page_size: int = 20
    ) -> UMLSSearchResult:
        async with self._semaphore:
            logger.info(f"Searching UMLS async for term: '{term}' (language: {language})")

            if self.cache_service:
                cached = self.cache_service.get(term, language)
                if cached:
                    logger.debug(f"Cache hit for term: '{term}'")
                    return cached

            params = {
                "string": term,
                "sabs": ",".join(sabs) if sabs else None,
                "searchType": search_type,
                "pageSize": page_size,
                "language": language
            }

            params = {k: v for k, v in params.items() if v is not None}

            try:
                result = await self._make_request("/search/current", params)

                if not result:
                    return UMLSSearchResult(
                        query=term,
                        candidates=[],
                        error="No response from UMLS API"
                    )

                candidates = []
                results = result.get("result", {}).get("results", [])

                for item in results:
                    candidate = UMLSCandidate(
                        term=item.get("name", ""),
                        cui=item.get("ui", ""),
                        semantic_types=item.get("rootSource", "").split(",") if item.get("rootSource") else [],
                        preferred=item.get("preferred", "false").lower() == "true",
                        score=float(item.get("score", 0.0))
                    )
                    candidates.append(candidate)

                search_result = UMLSSearchResult(
                    query=term,
                    candidates=candidates,
                    total_count=len(candidates),
                    source="UMLS"
                )

                if self.cache_service and candidates:
                    self.cache_service.set(term, search_result, language)

                logger.info(f"Found {len(candidates)} candidates for term: '{term}'")
                return search_result

            except Exception as e:
                logger.error(f"UMLS async search failed for term '{term}': {e}")
                return UMLSSearchResult(
                    query=term,
                    candidates=[],
                    error=str(e)
                )

    async def batch_search(
        self,
        terms: List[str],
        language: str = "ENG",
        sabs: Optional[List[str]] = None,
        search_type: str = "words",
        page_size: int = 20
    ) -> Dict[str, UMLSSearchResult]:
        """
        并发搜索多个术语

        Args:
            terms: 术语列表
            language: 语言代码
            sabs: 源词汇表列表
            search_type: 搜索类型
            page_size: 每页结果数

        Returns:
            术语到搜索结果的映射字典
        """
        logger.info(f"Starting batch search for {len(terms)} terms")

        tasks = [
            self.search_term(term, language, sabs, search_type, page_size)
            for term in terms
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        result_dict = {}
        for term, result in zip(terms, results):
            if isinstance(result, Exception):
                logger.error(f"Batch search failed for term '{term}': {result}")
                result_dict[term] = UMLSSearchResult(
                    query=term,
                    candidates=[],
                    error=str(result)
                )
            else:
                result_dict[term] = result

        success_count = sum(1 for r in result_dict.values() if not r.error)
        logger.info(f"Batch search completed: {success_count}/{len(terms)} successful")

        return result_dict

    async def get_atoms(self, cui: str, language: Optional[str] = None) -> List[Dict]:
        logger.debug(f"Fetching atoms for CUI: {cui}, language: {language}")

        if self.cache_service:
            cached_atoms = self.cache_service.get_atoms(cui)
            if cached_atoms:
                logger.debug(f"Cache hit for atoms: CUI {cui}")
                return cached_atoms

        params = {}
        if language:
            params["language"] = language

        result = await self._make_request(f"/content/current/CUI/{cui}/atoms", params)

        if not result:
            return []

        atoms = result.get("result", [])

        if self.cache_service and atoms:
            self.cache_service.set_atoms(cui, atoms)

        return atoms

    async def health_check(self) -> bool:
        try:
            result = await self.search_term("headache", language="ENG", page_size=1)
            return result.error is None
        except Exception as e:
            logger.error(f"UMLS async health check failed: {e}")
            return False
