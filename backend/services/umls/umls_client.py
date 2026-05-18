import requests
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from . import UMLSCandidate, UMLSConcept, UMLSSearchResult
from ...utils.logger import logger


class UMLSClient:
    UMLS_API_BASE = "https://uts-ws.nlm.nih.gov/rest"
    UMLS_SERVICE = "http://umlsks.nlm.nih.gov"
    TGT_LIFETIME_HOURS = 7
    
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
        
        self._tgt_url: Optional[str] = None
        self._tgt_expires_at: Optional[datetime] = None
        
        logger.info(f"UMLSClient initialized with API key prefix: {api_key[:8]}...")
        
    def _get_service_ticket(self) -> str:
        if self._tgt_url and self._tgt_expires_at and datetime.now() < self._tgt_expires_at:
            logger.debug("Reusing cached TGT")
            try:
                return self._get_st_from_tgt(self._tgt_url)
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
                session = requests.Session()
                
                response = session.post(
                    auth_url,
                    data=data,
                    headers=headers,
                    timeout=self.request_timeout,
                    allow_redirects=False
                )
                
                logger.debug(f"TGT request status: {response.status_code}")
                
                if response.status_code in [200, 201]:
                    tgt_url = response.headers.get("Location")
                    if not tgt_url:
                        logger.warning("No Location header in TGT response")
                        continue
                    
                    logger.debug(f"Got TGT URL: {tgt_url}")
                    
                    self._tgt_url = tgt_url
                    self._tgt_expires_at = datetime.now() + timedelta(hours=self.TGT_LIFETIME_HOURS)
                    logger.debug(f"TGT cached, expires at: {self._tgt_expires_at}")
                    
                    return self._get_st_from_tgt(tgt_url)
                else:
                    logger.warning(f"TGT request failed with status {response.status_code}: {response.text[:100]}")
                    
            except requests.RequestException as e:
                logger.warning(f"TGT request attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
        
        raise RuntimeError("Failed to obtain service ticket from UMLS after max retries")
    
    def _get_st_from_tgt(self, tgt_url: str) -> str:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        st_response = requests.post(
            tgt_url,
            data={"service": self.UMLS_SERVICE},
            headers=headers,
            timeout=self.request_timeout
        )
        
        logger.debug(f"ST request status: {st_response.status_code}, body: {st_response.text[:100]}")
        
        if st_response.status_code == 200 and st_response.text:
            logger.debug("Successfully obtained service ticket")
            return st_response.text.strip()
        else:
            raise RuntimeError(f"Service ticket request failed: {st_response.status_code}")
    
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
        url = f"{self.UMLS_API_BASE}{endpoint}"
        
        logger.debug(f"Making request to: {url}")
        
        for attempt in range(self.max_retries):
            self._rate_limit()
            
            service_ticket = self._get_service_ticket()
            
            request_params = {"ticket": service_ticket}
            if params:
                request_params.update(params)
            
            try:
                response = requests.get(
                    url,
                    params=request_params,
                    timeout=self.request_timeout
                )
                
                logger.debug(f"Response status: {response.status_code}")
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    logger.warning("Authentication failed (invalid ST), getting new ticket")
                    continue
                elif response.status_code == 404:
                    logger.debug(f"Resource not found: {endpoint}")
                    return None
                else:
                    logger.warning(f"Request failed with status {response.status_code}: {response.text[:200]}")
                    if attempt < self.max_retries - 1:
                        time.sleep(1)
                        
            except requests.RequestException as e:
                logger.warning(f"Request attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
        
        return None
    
    MEDICAL_SOURCES = [
        "SNOMEDCT_US",
        "ICD10CM",
        "ICD10PCS",
        "ICD11",
        "MTH",
        "MSH",
        "RXNORM",
        "LNC",
        "HPO",
        "MEDCIN",
        "MEDLINEPLUS",
    ]
    
    EXCLUDED_SOURCES = [
        "PHENX",
        "LCH",
        "CHV",
        "MTHMST",
        "MTHSPL",
    ]
    
    def search_term(
        self,
        term: str,
        language: str = "CHI",
        sabs: Optional[List[str]] = None,
        search_type: str = "words",
        page_size: int = 20,
        medical_only: bool = True
    ) -> UMLSSearchResult:
        logger.info(f"Searching UMLS for term: '{term}' (language: {language})")
        
        if self.cache_service:
            cached = self.cache_service.get(term, language)
            if cached:
                logger.debug(f"Cache hit for term: '{term}'")
                return cached
        
        if medical_only and sabs is None:
            sabs = self.MEDICAL_SOURCES
        
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
                name = item.get("name", "")
                
                if len(name) > 100:
                    logger.debug(f"Skipping long name candidate: '{name[:50]}...'")
                    continue
                
                if any(pattern in name for pattern in [":Find:", ":Pt:", "^Patient:", "PhenX"]):
                    logger.debug(f"Skipping questionnaire-style candidate: '{name[:50]}...'")
                    continue
                
                candidate = UMLSCandidate(
                    term=name,
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
        
        if self.cache_service:
            cached_atoms = self.cache_service.get_atoms(cui)
            if cached_atoms:
                logger.debug(f"Cache hit for atoms: CUI {cui}")
                return cached_atoms
        
        params = {}
        if language:
            params["language"] = language
        
        result = self._make_request(f"/content/current/CUI/{cui}/atoms", params)
        
        if not result:
            return []
        
        atoms = result.get("result", [])
        
        if self.cache_service and atoms:
            self.cache_service.set_atoms(cui, atoms)
        
        return atoms
    
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
