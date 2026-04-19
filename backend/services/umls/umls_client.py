import requests
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import asdict

from . import UMLSCandidate, UMLSConcept, UMLSSearchResult
from ...utils.logger import logger


class UMLSClient:
    UMLS_API_BASE = "https://uts-ws.nlm.nih.gov/rest"
    
    def __init__(
        self,
        api_key: str,
        cache_service: Optional[Any] = None,
        request_timeout: int = 30,
        max_retries: int = 3,
        rate_limit_delay: float = 0.1
    ):
        self.api_key = api_key
        self.cache_service = cache_service
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0
        self._ticket_granting_ticket: Optional[str] = None
        self._tgt_expiry: Optional[datetime] = None
        
        logger.info(f"UMLSClient initialized with API key prefix: {api_key[:8]}...")
        
    def _get_service_ticket(self) -> str:
        now = datetime.now()
        
        if self._ticket_granting_ticket and self._tgt_expiry and now < self._tgt_expiry:
            st_url = f"https://utslogin.nlm.nih.gov/sso/serviceTicket"
            params = {"service": self.UMLS_API_BASE}
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            try:
                response = requests.post(
                    st_url,
                    data=params,
                    headers=headers,
                    timeout=self.request_timeout
                )
                if response.status_code == 200:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Failed to get service ticket from existing TGT: {e}")
        
        auth_url = "https://utslogin.nlm.nih.gov/cas/v1/api-key"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"apikey": self.api_key}
        
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    auth_url,
                    data=data,
                    headers=headers,
                    timeout=self.request_timeout
                )
                
                if response.status_code == 201:
                    self._ticket_granting_ticket = response.text.strip()
                    self._tgt_expiry = now + timedelta(hours=8)
                    logger.debug("Successfully obtained TGT from UMLS")
                    break
                else:
                    logger.warning(f"TGT request failed with status {response.status_code}")
                    
            except requests.RequestException as e:
                logger.warning(f"TGT request attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
        else:
            raise RuntimeError("Failed to obtain TGT from UMLS after max retries")
        
        st_url = "https://utslogin.nlm.nih.gov/sso/serviceTicket"
        params = {"service": self.UMLS_API_BASE}
        
        try:
            response = requests.post(
                st_url,
                data=params,
                headers=headers,
                timeout=self.request_timeout
            )
            if response.status_code == 200:
                return response.text.strip()
            else:
                raise RuntimeError(f"Failed to get service ticket: {response.status_code}")
        except requests.RequestException as e:
            raise RuntimeError(f"Service ticket request failed: {e}")
    
    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        self._rate_limit()
        
        service_ticket = self._get_service_ticket()
        
        url = f"{self.UMLS_API_BASE}{endpoint}"
        request_params = {"ticket": service_ticket}
        if params:
            request_params.update(params)
        
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    params=request_params,
                    timeout=self.request_timeout
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    logger.warning("Authentication failed, refreshing ticket")
                    self._ticket_granting_ticket = None
                    service_ticket = self._get_service_ticket()
                    request_params["ticket"] = service_ticket
                    continue
                elif response.status_code == 404:
                    logger.debug(f"Resource not found: {endpoint}")
                    return None
                else:
                    logger.warning(f"Request failed with status {response.status_code}: {response.text}")
                    if attempt < self.max_retries - 1:
                        time.sleep(1)
                        
            except requests.RequestException as e:
                logger.warning(f"Request attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
        
        return None
    
    def search_term(
        self,
        term: str,
        language: str = "CHI",
        sabs: Optional[List[str]] = None,
        search_type: str = "words",
        page_size: int = 20
    ) -> UMLSSearchResult:
        logger.info(f"Searching UMLS for term: '{term}' (language: {language})")
        
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
            result = self._make_request("/search/current", params)
            
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
            logger.error(f"UMLS search failed for term '{term}': {e}")
            return UMLSSearchResult(
                query=term,
                candidates=[],
                error=str(e)
            )
    
    def get_concept(self, cui: str) -> Optional[UMLSConcept]:
        logger.debug(f"Fetching UMLS concept: {cui}")
        
        result = self._make_request(f"/content/current/CUI/{cui}")
        
        if not result:
            return None
        
        concept_data = result.get("result", {})
        
        return UMLSConcept(
            cui=cui,
            name=concept_data.get("name", ""),
            semantic_types=concept_data.get("semanticTypes", []),
            definitions=[d.get("value", "") for d in concept_data.get("definitions", [])],
            atoms=concept_data.get("atoms", []),
            relations=concept_data.get("relations", [])
        )
    
    def get_atoms(self, cui: str, language: Optional[str] = None) -> List[Dict]:
        logger.debug(f"Fetching atoms for CUI: {cui}, language: {language}")
        
        params = {}
        if language:
            params["language"] = language
        
        result = self._make_request(f"/content/current/CUI/{cui}/atoms", params)
        
        if not result:
            return []
        
        return result.get("result", [])
    
    def get_definitions(self, cui: str) -> List[Dict]:
        logger.debug(f"Fetching definitions for CUI: {cui}")
        
        result = self._make_request(f"/content/current/CUI/{cui}/definitions")
        
        if not result:
            return []
        
        return result.get("result", [])
    
    def get_relations(self, cui: str) -> List[Dict]:
        logger.debug(f"Fetching relations for CUI: {cui}")
        
        result = self._make_request(f"/content/current/CUI/{cui}/relations")
        
        if not result:
            return []
        
        return result.get("result", [])
    
    def search_by_code(
        self,
        code: str,
        source: str
    ) -> Optional[UMLSCandidate]:
        logger.debug(f"Searching UMLS by code: {code} from source: {source}")
        
        params = {
            "code": code,
            "sabs": source
        }
        
        result = self._make_request("/search/current", params)
        
        if not result:
            return None
        
        results = result.get("result", {}).get("results", [])
        if results:
            item = results[0]
            return UMLSCandidate(
                term=item.get("name", ""),
                cui=item.get("ui", ""),
                semantic_types=item.get("rootSource", "").split(",") if item.get("rootSource") else [],
                preferred=True,
                score=1.0
            )
        
        return None
    
    def health_check(self) -> bool:
        try:
            result = self.search_term("headache", language="ENG", page_size=1)
            return result.error is None
        except Exception as e:
            logger.error(f"UMLS health check failed: {e}")
            return False
