window.CacheModule = (function() {
    var CACHE_PREFIX = 'emr_cache_';
    var INDEX_KEY = 'emr_cache_index';

    function saveEMRCache(visitId, data) {
        if (!visitId) return;
        try {
            var cacheData = {
                emrRecord: data.emrRecord || null,
                versions: data.versions || [],
                visitInfo: data.visitInfo || {},
                cachedAt: new Date().toISOString()
            };
            var key = CACHE_PREFIX + visitId;
            localStorage.setItem(key, JSON.stringify(cacheData));
            updateCacheIndex(visitId);
        } catch (e) {
            console.error('保存缓存失败:', e);
        }
    }

    function loadEMRCache(visitId) {
        if (!visitId) return null;
        try {
            var key = CACHE_PREFIX + visitId;
            var raw = localStorage.getItem(key);
            if (!raw) return null;
            var data = JSON.parse(raw);
            return data;
        } catch (e) {
            console.error('读取缓存失败:', e);
            return null;
        }
    }

    function removeEMRCache(visitId) {
        if (!visitId) return;
        try {
            var key = CACHE_PREFIX + visitId;
            localStorage.removeItem(key);
            removeFromCacheIndex(visitId);
        } catch (e) {
            console.error('删除缓存失败:', e);
        }
    }

    function getAllCachedVisits() {
        try {
            var indexRaw = localStorage.getItem(INDEX_KEY);
            if (!indexRaw) return [];
            var index = JSON.parse(indexRaw);
            var result = [];
            index.forEach(function(visitId) {
                var data = loadEMRCache(visitId);
                if (data) {
                    result.push({
                        visitId: visitId,
                        cachedAt: data.cachedAt,
                        patientName: data.visitInfo.patient_name || '',
                        visitDate: data.visitInfo.visit_date || '',
                        language: data.visitInfo.language || 'zh',
                        versionCount: data.versions ? data.versions.length : 0,
                        latestVersion: data.versions && data.versions.length > 0 ? data.versions[0].version : null
                    });
                }
            });
            return result;
        } catch (e) {
            console.error('获取缓存列表失败:', e);
            return [];
        }
    }

    function updateCacheIndex(visitId) {
        try {
            var indexRaw = localStorage.getItem(INDEX_KEY);
            var index = indexRaw ? JSON.parse(indexRaw) : [];
            var idx = index.indexOf(visitId);
            if (idx === -1) {
                index.unshift(visitId);
            } else {
                index.splice(idx, 1);
                index.unshift(visitId);
            }
            localStorage.setItem(INDEX_KEY, JSON.stringify(index.slice(0, 100)));
        } catch (e) {
            console.error('更新缓存索引失败:', e);
        }
    }

    function removeFromCacheIndex(visitId) {
        try {
            var indexRaw = localStorage.getItem(INDEX_KEY);
            if (!indexRaw) return;
            var index = JSON.parse(indexRaw);
            var idx = index.indexOf(visitId);
            if (idx !== -1) {
                index.splice(idx, 1);
                localStorage.setItem(INDEX_KEY, JSON.stringify(index));
            }
        } catch (e) {
            console.error('移除缓存索引失败:', e);
        }
    }

    function clearAllCache() {
        try {
            var index = getAllCachedVisits();
            index.forEach(function(item) {
                localStorage.removeItem(CACHE_PREFIX + item.visitId);
            });
            localStorage.removeItem(INDEX_KEY);
        } catch (e) {
            console.error('清除缓存失败:', e);
        }
    }

    return {
        saveEMRCache: saveEMRCache,
        loadEMRCache: loadEMRCache,
        removeEMRCache: removeEMRCache,
        getAllCachedVisits: getAllCachedVisits,
        clearAllCache: clearAllCache
    };
})();