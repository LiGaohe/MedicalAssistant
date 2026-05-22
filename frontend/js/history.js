window.HistoryModule = (function() {
    var state = App.getState();
    var currentVisitList = [];

    function initHistory() {
        var refreshBtn = document.getElementById('refreshHistoryBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function() {
                loadHistoryList();
            });
        }

        App.on('panelChanged', function(panelName) {
            if (panelName === 'history') {
                loadHistoryList();
            }
        });

        App.on('emrGenerated', function() {
            if (state.activePanel === 'history') {
                loadHistoryList();
            }
        });

        App.on('emrDeleted', function() {
            if (state.activePanel === 'history') {
                loadHistoryList();
            }
        });
    }

    async function loadHistoryList() {
        var listEl = document.getElementById('historyList');
        if (!listEl) return;

        listEl.innerHTML = '<p class="history-loading">加载中...</p>';

        try {
            var response = await fetch('/api/emr/visits');
            if (response.ok) {
                var data = await response.json();
                currentVisitList = data.visits || [];
                mergeCachedData();
                renderHistoryList(currentVisitList);
            } else {
                currentVisitList = loadFromCacheOnly();
                renderHistoryList(currentVisitList);
            }
        } catch (e) {
            currentVisitList = loadFromCacheOnly();
            renderHistoryList(currentVisitList);
        }
    }

    function loadFromCacheOnly() {
        var cached = CacheModule.getAllCachedVisits();
        return cached.map(function(item) {
            return {
                visit_id: item.visitId,
                patient_name: item.patientName,
                visit_date: item.visitDate,
                language: item.language,
                version_count: item.versionCount,
                latest_version: item.latestVersion,
                latest_preview: null,
                versions: [],
                _fromCache: true
            };
        });
    }

    function mergeCachedData() {
        currentVisitList.forEach(function(visit) {
            var cache = CacheModule.loadEMRCache(visit.visit_id);
            if (cache) {
                if (cache.visitInfo.patient_name && !visit.patient_name) {
                    visit.patient_name = cache.visitInfo.patient_name;
                }
                if (cache.visitInfo.visit_date && !visit.visit_date) {
                    visit.visit_date = cache.visitInfo.visit_date;
                }
            }
        });
    }

    function renderHistoryList(visits) {
        var listEl = document.getElementById('historyList');
        if (!listEl) return;

        if (!visits || visits.length === 0) {
            listEl.innerHTML = '<p class="history-empty">暂无历史病历</p>';
            return;
        }

        var html = '';
        visits.forEach(function(visit) {
            html += buildHistoryItem(visit);
        });
        listEl.innerHTML = html;

        bindHistoryActions();
    }

    function buildHistoryItem(visit) {
        var patientName = visit.patient_name || '未知患者';
        var visitDate = visit.visit_date || '未知日期';
        var language = visit.language === 'en' ? 'English' : '中文';
        var versionCount = visit.version_count || 0;
        var isCurrent = state.visitId === visit.visit_id;

        var currentBadge = isCurrent ? '<span class="history-current-badge">当前</span>' : '';
        var previewHtml = visit.latest_preview
            ? '<div class="history-item-preview">' + App.escapeHtml(visit.latest_preview) + '</div>'
            : '';

        return '<div class="history-item' + (isCurrent ? ' history-item-current' : '') + '" data-visit-id="' + visit.visit_id + '">' +
            '<div class="history-item-header">' +
            '<span class="history-item-patient">' + App.escapeHtml(patientName) + '</span>' +
            currentBadge +
            '</div>' +
            '<div class="history-item-meta">' +
            '<span>' + App.escapeHtml(visitDate) + '</span>' +
            '<span>语言: ' + language + '</span>' +
            '<span>' + versionCount + ' 个版本</span>' +
            '</div>' +
            previewHtml +
            '<div class="history-item-actions">' +
            '<button class="history-btn-view" data-action="view" data-visit-id="' + visit.visit_id + '">' +
            App.icon('stethoscope', 12) + ' 查看</button>' +
            '<button class="history-btn-delete" data-action="delete" data-visit-id="' + visit.visit_id + '">' +
            App.icon('x', 12) + ' 删除</button>' +
            '</div>' +
            '</div>';
    }

    function bindHistoryActions() {
        var listEl = document.getElementById('historyList');
        if (!listEl) return;

        listEl.querySelectorAll('.history-btn-view').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var visitId = this.dataset.visitId;
                viewHistoryRecord(visitId);
            });
        });

        listEl.querySelectorAll('.history-btn-delete').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var visitId = this.dataset.visitId;
                deleteHistoryRecord(visitId);
            });
        });
    }

    function viewHistoryRecord(visitId) {
        var cache = CacheModule.loadEMRCache(visitId);
        if (cache && cache.emrRecord) {
            state.visitId = visitId;
            state.emrRecord = cache.emrRecord;
            state.currentRecordId = cache.emrRecord.record_id;
            App.setState({
                visitId: visitId,
                emrRecord: cache.emrRecord,
                currentRecordId: cache.emrRecord.record_id
            });
            App.updateTitlebar(visitId, true);
            App.showEditorContent();
            EditorModule.displayEMR(cache.emrRecord);
            EditorModule.loadEMRVersions(visitId);
            App.setActivePanel('editor');
            App.updateStatusBar('已加载历史病历');
        } else {
            state.visitId = visitId;
            App.setState({ visitId: visitId });
            App.updateTitlebar(visitId, false);
            EditorModule.loadEMRVersions(visitId);
            App.setActivePanel('editor');
            App.updateStatusBar('已切换就诊');
        }
    }

    async function deleteHistoryRecord(visitId) {
        if (!confirm('确定要删除该就诊的所有病历记录吗？此操作不可撤销。')) {
            return;
        }

        try {
            var response = await fetch('/api/emr/record/' + visitId, {
                method: 'DELETE'
            });
            var result = await response.json();

            if (result.status === 'success') {
                CacheModule.removeEMRCache(visitId);
                App.emit('emrDeleted', { visitId: visitId });
                App.updateStatusBar('已删除 ' + (result.deleted_count || 0) + ' 条病历记录');

                if (state.visitId === visitId) {
                    state.visitId = null;
                    state.emrRecord = null;
                    state.currentRecordId = null;
                    App.setState({
                        visitId: null,
                        emrRecord: null,
                        currentRecordId: null
                    });
                    App.showEditorWelcome();
                    App.updateTitlebar('--', false);
                }

                loadHistoryList();
            } else {
                alert('删除失败，请重试');
            }
        } catch (e) {
            alert('删除失败: ' + e.message);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        initHistory();
    });

    return {
        loadHistoryList: loadHistoryList
    };
})();