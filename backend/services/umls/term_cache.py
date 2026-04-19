import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import asdict
import threading

from . import UMLSSearchResult
from ...utils.logger import logger


class TermCache:
    def __init__(
        self,
        cache_dir: str = "data/cache/umls",
        default_ttl_hours: int = 24 * 7,
        max_memory_cache_size: int = 1000
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_hours = default_ttl_hours
        self.max_memory_cache_size = max_memory_cache_size
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        logger.info(f"TermCache initialized at {cache_dir}, TTL: {default_ttl_hours}h")
    
    def _get_cache_key(self, term: str, language: str = "CHI") -> str:
        key_string = f"{term.lower()}:{language}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_cache_file_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"
    
    def get(
        self,
        term: str,
        language: str = "CHI"
    ) -> Optional[UMLSSearchResult]:
        cache_key = self._get_cache_key(term, language)
        
        with self._lock:
            if cache_key in self._memory_cache:
                cached_entry = self._memory_cache[cache_key]
                if self._is_entry_valid(cached_entry):
                    logger.debug(f"Memory cache hit for term: '{term}'")
                    return self._dict_to_result(cached_entry["data"])
                else:
                    del self._memory_cache[cache_key]
        
        cache_file = self._get_cache_file_path(cache_key)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_entry = json.load(f)
                
                if self._is_entry_valid(cached_entry):
                    result = self._dict_to_result(cached_entry["data"])
                    
                    with self._lock:
                        self._add_to_memory_cache(cache_key, cached_entry)
                    
                    logger.debug(f"File cache hit for term: '{term}'")
                    return result
                else:
                    cache_file.unlink()
                    logger.debug(f"Expired cache entry removed for term: '{term}'")
                    
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to read cache file for term '{term}': {e}")
                cache_file.unlink()
        
        return None
    
    def set(
        self,
        term: str,
        result: UMLSSearchResult,
        language: str = "CHI",
        ttl_hours: Optional[int] = None
    ) -> None:
        if not result.candidates:
            logger.debug(f"Skipping cache for term '{term}' - no candidates")
            return
        
        cache_key = self._get_cache_key(term, language)
        ttl = ttl_hours or self.default_ttl_hours
        
        cached_entry = {
            "term": term,
            "language": language,
            "data": self._result_to_dict(result),
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=ttl)).isoformat(),
            "ttl_hours": ttl
        }
        
        with self._lock:
            self._add_to_memory_cache(cache_key, cached_entry)
        
        cache_file = self._get_cache_file_path(cache_key)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cached_entry, f, ensure_ascii=False, indent=2)
            logger.debug(f"Cached result for term: '{term}'")
        except Exception as e:
            logger.warning(f"Failed to write cache file for term '{term}': {e}")
    
    def _add_to_memory_cache(self, cache_key: str, entry: Dict[str, Any]) -> None:
        if len(self._memory_cache) >= self.max_memory_cache_size:
            oldest_key = min(
                self._memory_cache.keys(),
                key=lambda k: self._memory_cache[k].get("created_at", "")
            )
            del self._memory_cache[oldest_key]
            logger.debug("Evicted oldest entry from memory cache")
        
        self._memory_cache[cache_key] = entry
    
    def _is_entry_valid(self, entry: Dict[str, Any]) -> bool:
        try:
            expires_at = datetime.fromisoformat(entry.get("expires_at", ""))
            return datetime.now() < expires_at
        except (ValueError, TypeError):
            return False
    
    def _result_to_dict(self, result: UMLSSearchResult) -> Dict[str, Any]:
        return {
            "query": result.query,
            "candidates": [
                {
                    "term": c.term,
                    "cui": c.cui,
                    "semantic_types": c.semantic_types,
                    "preferred": c.preferred,
                    "score": c.score
                }
                for c in result.candidates
            ],
            "total_count": result.total_count,
            "source": result.source,
            "error": result.error
        }
    
    def _dict_to_result(self, data: Dict[str, Any]) -> UMLSSearchResult:
        from . import UMLSCandidate
        
        candidates = [
            UMLSCandidate(
                term=c["term"],
                cui=c["cui"],
                semantic_types=c.get("semantic_types", []),
                preferred=c.get("preferred", False),
                score=c.get("score", 0.0)
            )
            for c in data.get("candidates", [])
        ]
        
        return UMLSSearchResult(
            query=data["query"],
            candidates=candidates,
            total_count=data.get("total_count", len(candidates)),
            source=data.get("source", "UMLS"),
            error=data.get("error")
        )
    
    def clear_expired(self) -> int:
        cleared_count = 0
        now = datetime.now()
        
        with self._lock:
            expired_keys = [
                k for k, v in self._memory_cache.items()
                if not self._is_entry_valid(v)
            ]
            for key in expired_keys:
                del self._memory_cache[key]
                cleared_count += 1
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                
                expires_at = datetime.fromisoformat(entry.get("expires_at", ""))
                if now >= expires_at:
                    cache_file.unlink()
                    cleared_count += 1
                    
            except (json.JSONDecodeError, ValueError, KeyError):
                cache_file.unlink()
                cleared_count += 1
        
        logger.info(f"Cleared {cleared_count} expired cache entries")
        return cleared_count
    
    def clear_all(self) -> int:
        cleared_count = 0
        
        with self._lock:
            cleared_count += len(self._memory_cache)
            self._memory_cache.clear()
        
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            cleared_count += 1
        
        logger.info(f"Cleared all {cleared_count} cache entries")
        return cleared_count
    
    def get_stats(self) -> Dict[str, Any]:
        file_count = len(list(self.cache_dir.glob("*.json")))
        
        with self._lock:
            memory_count = len(self._memory_cache)
        
        return {
            "memory_cache_size": memory_count,
            "file_cache_size": file_count,
            "max_memory_cache_size": self.max_memory_cache_size,
            "default_ttl_hours": self.default_ttl_hours,
            "cache_dir": str(self.cache_dir)
        }
