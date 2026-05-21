window.App = (function() {
    var listeners = {};

    function on(event, callback) {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(callback);
    }

    function emit(event, data) {
        if (listeners[event]) {
            listeners[event].forEach(function(cb) { cb(data); });
        }
    }

    var state = {
        visitId: null,
        emrRecord: null,
        currentRecordId: null,
        isEditing: false,
        evidenceVisible: false,
        evidenceData: [],
        activePanel: 'agent',
        sidebarVisible: true,
        emrStatus: null,
        language: 'zh',
        audioDuration: null,
        hasTranscription: false
    };

    function getState() {
        return state;
    }

    function setState(updates) {
        Object.assign(state, updates);
    }

    function updateStatusBar(message, type) {
        var el = document.getElementById('statusbarMessage');
        if (el) {
            el.textContent = message;
            el.className = 'statusbar-item';
            if (type) {
                el.classList.add(type);
            }
        }
    }

    function updateStatusBarInfo(info) {
        if (info.version !== undefined) {
            var verEl = document.getElementById('statusbarVersion');
            if (verEl) verEl.textContent = '版本: ' + info.version;
        }
        if (info.language !== undefined) {
            var langEl = document.getElementById('statusbarLanguage');
            if (langEl) langEl.textContent = '语言: ' + (info.language === 'zh' ? '中文' : 'English');
        }
        if (info.speaker !== undefined) {
            var spkEl = document.getElementById('statusbarSpeaker');
            if (spkEl) spkEl.textContent = '说话人: ' + info.speaker;
        }
    }

    function updateTitlebar(visitId, hasEmr) {
        var visitEl = document.getElementById('titlebarVisitId');
        if (visitEl && visitId) {
            visitEl.textContent = '就诊ID: ' + visitId;
        }
        var statusEl = document.getElementById('titlebarStatus');
        if (statusEl) {
            statusEl.textContent = hasEmr ? '已生成病历' : '未生成病历';
            statusEl.className = 'titlebar-status' + (hasEmr ? ' has-emr' : '');
        }
        var printBtn = document.getElementById('titlebarPrint');
        var evalBtn = document.getElementById('titlebarEvaluate');
        if (printBtn) printBtn.disabled = !hasEmr;
        if (evalBtn) evalBtn.disabled = !hasEmr;
    }

    function setActivePanel(panelName) {
        state.activePanel = panelName;

        var activityBtns = document.querySelectorAll('.activity-btn');
        activityBtns.forEach(function(btn) {
            btn.classList.remove('active');
            if (btn.dataset.panel === panelName) {
                btn.classList.add('active');
            }
        });

        var sidebar = document.getElementById('sidebar');
        var panels = document.querySelectorAll('.sidebar-panel');
        panels.forEach(function(p) { p.classList.remove('active'); });

        if (panelName === 'editor') {
            if (sidebar) sidebar.style.display = 'none';
        } else {
            if (sidebar) sidebar.style.display = 'flex';
            var targetPanel = document.getElementById('sidebar-panel-' + panelName);
            if (targetPanel) targetPanel.classList.add('active');
        }

        emit('panelChanged', panelName);
    }

    function showEditorWelcome() {
        var welcome = document.getElementById('editor-welcome');
        var content = document.getElementById('editor-content');
        if (welcome) welcome.style.display = 'flex';
        if (content) content.style.display = 'none';
    }

    function showEditorContent() {
        var welcome = document.getElementById('editor-welcome');
        var content = document.getElementById('editor-content');
        if (welcome) welcome.style.display = 'none';
        if (content) content.style.display = 'flex';
    }

    function formatDuration(seconds) {
        if (!seconds) return '未知';
        var mins = Math.floor(seconds / 60);
        var secs = Math.floor(seconds % 60);
        return mins + '分' + secs + '秒';
    }

    function formatTime(ms) {
        var seconds = Math.floor(ms / 1000);
        var mins = Math.floor(seconds / 60);
        var secs = seconds % 60;
        return mins + ':' + (secs < 10 ? '0' : '') + secs;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getFieldName(field) {
        var nameMap = {
            'chief_complaint': '主诉',
            'history_present_illness': '现病史',
            'past_history': '既往史',
            'denied_symptoms': '否认症状',
            'physical_examination': '体格检查',
            'auxiliary_examination': '辅助检查',
            'diagnosis': '诊断',
            'treatment': '治疗方案',
            'advice': '医嘱'
        };
        return nameMap[field] || field;
    }

    document.addEventListener('DOMContentLoaded', function() {
        var urlParams = new URLSearchParams(window.location.search);
        var visitId = urlParams.get('visit_id');
        if (visitId) {
            state.visitId = visitId;
            updateTitlebar(visitId, false);
            loadInitialData(visitId);
        }

        var activityBtns = document.querySelectorAll('.activity-btn');
        activityBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var panel = this.dataset.panel;
                setActivePanel(panel);
            });
        });

        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.key === '1') {
                e.preventDefault();
                setActivePanel('editor');
            } else if (e.ctrlKey && e.key === '2') {
                e.preventDefault();
                setActivePanel('agent');
            } else if (e.ctrlKey && e.key === '3') {
                e.preventDefault();
                setActivePanel('debug');
            } else if (e.ctrlKey && e.key === '4') {
                e.preventDefault();
                setActivePanel('config');
            }
        });

        var titlebarPrint = document.getElementById('titlebarPrint');
        if (titlebarPrint) {
            titlebarPrint.addEventListener('click', function() {
                emit('printEMR');
            });
        }

        var titlebarEvaluate = document.getElementById('titlebarEvaluate');
        if (titlebarEvaluate) {
            titlebarEvaluate.addEventListener('click', function() {
                if (state.currentRecordId && state.visitId) {
                    window.open('/static/evaluation.html?record_id=' + state.currentRecordId + '&visit_id=' + state.visitId, '_blank');
                }
            });
        }

        var welcomeAgentLink = document.getElementById('welcomeAgentLink');
        if (welcomeAgentLink) {
            welcomeAgentLink.addEventListener('click', function() {
                setActivePanel('agent');
            });
        }
    });

    function loadInitialData(visitId) {
        updateStatusBar('加载就诊信息...');

        fetch('/api/emr/status/' + visitId)
            .then(function(r) { return r.json(); })
            .then(function(result) {
                state.emrStatus = result;
                var hasEmr = result.has_emr;
                updateTitlebar(visitId, hasEmr);

                if (result.language) {
                    state.language = result.language;
                    updateStatusBarInfo({ language: result.language });
                }

                if (hasEmr && result.latest_record_id) {
                    state.currentRecordId = result.latest_record_id;
                    emit('emrStatusLoaded', result);
                }
                updateStatusBar('就绪');
            })
            .catch(function(err) {
                console.error('加载状态失败:', err);
                updateStatusBar('加载状态失败', 'error');
            });

        fetch('/api/asr/transcript/' + visitId)
            .then(function(r) { return r.json(); })
            .then(function(result) {
                if (result.language) {
                    state.language = result.language;
                    updateStatusBarInfo({ language: result.language });
                }
                if (result.audio_duration) {
                    state.audioDuration = result.audio_duration;
                }
                if (result.turns && result.turns.length > 0) {
                    state.hasTranscription = true;
                    updateStatusBarInfo({ speaker: result.turns.length + ' 轮次' });
                    emit('transcriptionLoaded', result);
                }
            })
            .catch(function(err) {
                console.log('加载转写信息失败:', err);
            });
    }

    function icon(name, size) {
        size = size || 16;
        var s = 'width="' + size + '" height="' + size + '"';
        var attrs = 'xmlns="http://www.w3.org/2000/svg" ' + s + ' viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
        var icons = {
            stethoscope: '<svg ' + attrs + '><path d="M11 2v2M5 2v2m0-1H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/></svg>',
            printer: '<svg ' + attrs + '><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect width="12" height="8" x="6" y="14" rx="1"/></svg>',
            barChart: '<svg ' + attrs + '><path d="M3 3v18h18m-3-4V9m-5 8V5M8 17v-3"/></svg>',
            sparkles: '<svg ' + attrs + '><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594zM20 2v4m2-2h-4"/><circle cx="4" cy="20" r="2"/></svg>',
            bot: '<svg ' + attrs + '><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2m16 0h2m-7-1v2m-6-2v2"/></svg>',
            messageSquare: '<svg ' + attrs + '><path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/></svg>',
            pencil: '<svg ' + attrs + '><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497zM15 5l4 4"/></svg>',
            save: '<svg ' + attrs + '><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7M7 3v4a1 1 0 0 0 1 1h7"/></svg>',
            paperclip: '<svg ' + attrs + '><path d="m16 6l-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/></svg>',
            user: '<svg ' + attrs + '><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
            x: '<svg ' + attrs + '><path d="M18 6L6 18M6 6l12 12"/></svg>',
            upload: '<svg ' + attrs + '><path d="M12 3v12m5-7l-5-5l-5 5m14 7v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/></svg>',
            mic: '<svg ' + attrs + '><path d="M12 19v3m7-12v2a7 7 0 0 1-14 0v-2"/><rect width="6" height="13" x="9" y="2" rx="3"/></svg>',
            checkCircle: '<svg ' + attrs + '><path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11l3 3L22 4"/></svg>',
            xCircle: '<svg ' + attrs + '><circle cx="12" cy="12" r="10"/><path d="m15 9l-6 6m0-6l6 6"/></svg>',
            loader: '<svg ' + attrs + ' class="icon-spin"><path d="M12 2v4m4.2 1.8l2.9-2.9M18 12h4m-5.8 4.2l2.9 2.9M12 18v4m-7.1-2.9l2.9-2.9M2 12h4M4.9 4.9l2.9 2.9"/></svg>',
            refreshCw: '<svg ' + attrs + '><path d="M3 12a9 9 0 0 1 9-9a9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5m5 4a9 9 0 0 1-9 9a9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
            circlePause: '<svg ' + attrs + '><circle cx="12" cy="12" r="10"/><path d="M10 15V9m4 6V9"/></svg>'
        };
        return icons[name] || '';
    }

    return {
        state: state,
        on: on,
        emit: emit,
        getState: getState,
        setState: setState,
        updateStatusBar: updateStatusBar,
        updateStatusBarInfo: updateStatusBarInfo,
        updateTitlebar: updateTitlebar,
        setActivePanel: setActivePanel,
        showEditorWelcome: showEditorWelcome,
        showEditorContent: showEditorContent,
        formatDuration: formatDuration,
        formatTime: formatTime,
        escapeHtml: escapeHtml,
        getFieldName: getFieldName,
        icon: icon
    };
})();