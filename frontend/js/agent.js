window.AgentModule = (function() {
    var state = App.getState();
    var selectedFile = null;
    var isProcessing = false;
    var uploadInProgress = false;
    var stageElements = {};

    function addMessage(type, content, details) {
        var container = document.getElementById('agentMessages');
        if (!container) return;

        var msgDiv = document.createElement('div');
        msgDiv.className = 'agent-message ' + type;

        var icon = '';
        if (type === 'system') icon = App.icon('stethoscope', 16);
        else if (type === 'user') icon = App.icon('user', 16);
        else if (type === 'agent' || type === 'success') icon = App.icon('bot', 16);
        else if (type === 'progress') icon = App.icon('loader', 16);
        else if (type === 'warning') icon = App.icon('alertTriangle', 16);
        else if (type === 'error') icon = App.icon('xCircle', 16);

        msgDiv.innerHTML = '<div class="agent-message-icon">' + icon + '</div>' +
            '<div class="agent-message-content">' + content + '</div>';

        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
        return msgDiv;
    }

    function updateLastMessage(type, content) {
        var container = document.getElementById('agentMessages');
        if (!container) return;
        var messages = container.querySelectorAll('.agent-message.' + type);
        if (messages.length > 0) {
            var last = messages[messages.length - 1];
            var contentEl = last.querySelector('.agent-message-content');
            if (contentEl) contentEl.innerHTML = content;
            container.scrollTop = container.scrollHeight;
        } else {
            addMessage(type, content);
        }
    }

    function addStageMessage(stageNum, stageName, status, detail) {
        var type = 'progress';
        if (status === 'completed') type = 'success';
        else if (status === 'failed') type = 'error';

        var icon = status === 'running' ? App.icon('loader', 14) :
                   status === 'completed' ? App.icon('checkCircle', 14) :
                   status === 'failed' ? App.icon('xCircle', 14) : App.icon('circlePause', 14);

        var content = '<div class="stage-name">' + icon + ' 阶段' + stageNum + '/5: ' + stageName + '</div>';
        if (detail) {
            content += '<div class="stage-detail">' + detail + '</div>';
        }
        if (status === 'running') {
            content += '<div class="stage-progress"><div class="stage-progress-bar" style="width:60%"></div></div>';
        }

        addMessage(type, content);
    }

    function initAgent() {
        var dropZone = document.getElementById('agentDropZone');
        var audioFile = document.getElementById('agentAudioFile');
        var processBtn = document.getElementById('agentProcess');
        var textDebugBtn = document.getElementById('agentTextDebug');
        var languageSelect = document.getElementById('agentLanguage');

        if (dropZone && audioFile) {
            dropZone.addEventListener('click', function() { audioFile.click(); });

            dropZone.addEventListener('dragover', function(e) {
                e.preventDefault();
                dropZone.classList.add('drag-over');
            });

            dropZone.addEventListener('dragleave', function() {
                dropZone.classList.remove('drag-over');
            });

            dropZone.addEventListener('drop', function(e) {
                e.preventDefault();
                dropZone.style.borderColor = '';
                var files = e.dataTransfer.files;
                if (files.length > 0) handleFileSelect(files[0]);
            });

            audioFile.addEventListener('change', function(e) {
                if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
            });
        }

        function handleFileSelect(file) {
            var ext = file.name.split('.').pop().toLowerCase();
            if (ext !== 'wav' && ext !== 'mp3') {
                addMessage('error', '<p>仅支持 wav 和 mp3 格式</p>');
                return;
            }
            selectedFile = file;
            dropZone.classList.add('selected');
            var contentEl = dropZone.querySelector('.agent-upload-content');
            if (contentEl) {
                contentEl.innerHTML = '<span style="color:var(--ide-success);font-size:13px;">已选择: ' +
                    App.escapeHtml(file.name) + '</span>' +
                    '<span class="agent-upload-hint">点击重新选择</span>';
            }

            if (!state.visitId) {
                processBtn.innerHTML = App.icon('upload', 14) + ' 上传音频';
                processBtn.disabled = false;
            }
        }

        if (processBtn) {
            processBtn.addEventListener('click', function() {
                if (isProcessing) return;
                if (!state.visitId && selectedFile) {
                    uploadAndTranscribe();
                } else if (state.hasTranscription || state.visitId) {
                    processEMR();
                }
            });
        }

        if (languageSelect) {
            languageSelect.addEventListener('change', function() {
                state.language = this.value;
            });
        }

        if (textDebugBtn) {
            textDebugBtn.addEventListener('click', function() {
                var modal = document.getElementById('textDebugModal');
                if (modal) modal.style.display = 'flex';
            });
        }

        initTextDebugModal();

        App.on('visitIdSet', function(data) {
            if (processBtn) {
                processBtn.innerHTML = App.icon('sparkles', 14) + ' 生成病历';
                processBtn.disabled = false;
            }
        });

        App.on('transcriptionLoaded', function(data) {
            state.hasTranscription = true;
            if (processBtn) {
                processBtn.innerHTML = App.icon('sparkles', 14) + ' 生成病历';
                processBtn.disabled = false;
            }
            if (data.turns) {
                addMessage('success',
                    '<p>' + App.icon('mic', 14) + ' 语音转写已完成，共识别 <strong>' + data.turns.length + '</strong> 个对话轮次</p>' +
                    '<p class="agent-hint">点击「生成病历」开始处理</p>'
                );
            }
        });

        App.on('emrStatusLoaded', function(data) {
            if (processBtn) {
                processBtn.innerHTML = App.icon('refreshCw', 14) + ' 重新生成';
                processBtn.disabled = false;
            }
        });

        if (state.visitId) {
            addMessage('system',
                '<p>已加载就诊记录</p>' +
                '<p class="agent-hint">就诊ID: ' + App.escapeHtml(state.visitId) + '</p>'
            );
            if (state.hasTranscription) {
                if (processBtn) {
                    processBtn.innerHTML = App.icon('sparkles', 14) + ' 生成病历';
                    processBtn.disabled = false;
                }
            } else {
                if (processBtn) {
                    processBtn.innerHTML = App.icon('mic', 14) + ' 开始转写';
                    processBtn.disabled = false;
                }
            }
        }

        var clearBtn = document.getElementById('clearAgentBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function() {
                var container = document.getElementById('agentMessages');
                if (container) {
                    container.innerHTML = '';
                    var welcomeMsg = document.createElement('div');
                    welcomeMsg.className = 'agent-message system';
                    welcomeMsg.innerHTML = '<div class="agent-message-icon">' +
                        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2m16 0h2m-7-1v2m-6-2v2"/></svg>' +
                        '</div>' +
                        '<div class="agent-message-content">' +
                        '<p>欢迎使用门诊病历生成系统</p>' +
                        '<p class="agent-hint">请上传音频文件开始，或使用文本调试模式输入对话内容</p>' +
                        '</div>';
                    container.appendChild(welcomeMsg);
                }
            });
        }
    }

    function initTextDebugModal() {
        var modal = document.getElementById('textDebugModal');
        if (!modal) return;

        document.getElementById('closeTextDebugModal').addEventListener('click', function() {
            modal.style.display = 'none';
        });

        document.getElementById('cancelTextDebug').addEventListener('click', function() {
            modal.style.display = 'none';
        });

        modal.querySelector('.ide-modal-backdrop').addEventListener('click', function() {
            modal.style.display = 'none';
        });

        document.getElementById('startTextDebug').addEventListener('click', async function() {
            var text = document.getElementById('dialogTextInput').value.trim();
            var language = document.getElementById('debugLanguageSelect').value;

            if (!text) {
                alert('请输入对话文本');
                return;
            }

            var btn = document.getElementById('startTextDebug');
            btn.disabled = true;
            btn.textContent = '创建中...';

            try {
                var response = await fetch('/api/emr/debug/create-from-text', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ dialog_text: text, language: language })
                });
                var result = await response.json();

                if (result.status === 'success') {
                    modal.style.display = 'none';
                    state.visitId = result.visit_id;
                    App.setState({ visitId: result.visit_id });
                    App.updateTitlebar(result.visit_id, false);

                    addMessage('success',
                        '<p>' + App.icon('pencil', 14) + ' 文本调试模式已创建</p>' +
                        '<p class="agent-hint">就诊ID: ' + App.escapeHtml(result.visit_id) + '</p>'
                    );

                    App.updateStatusBar('文本调试模式就绪');
                    App.emit('visitIdSet', { visitId: result.visit_id });

                    var processBtn = document.getElementById('agentProcess');
                    if (processBtn) {
                        processBtn.innerHTML = App.icon('sparkles', 14) + ' 生成病历';
                        processBtn.disabled = false;
                    }
                } else {
                    addMessage('error', '<p>创建失败: ' + (result.error || '未知错误') + '</p>');
                }
            } catch (error) {
                addMessage('error', '<p>请求失败: ' + error.message + '</p>');
            } finally {
                btn.disabled = false;
                btn.textContent = '开始调试';
            }
        });
    }

    async function uploadAndTranscribe() {
        if (!selectedFile) return;
        isProcessing = true;
        var processBtn = document.getElementById('agentProcess');
        if (processBtn) processBtn.disabled = true;

        addMessage('user', '<p>' + App.icon('upload', 14) + ' 上传音频: ' + App.escapeHtml(selectedFile.name) + '</p>');

        var formData = new FormData();
        formData.append('audio_file', selectedFile);
        formData.append('language', state.language);

        try {
            var response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            var result = await response.json();

            if (result.success) {
                state.visitId = result.visit_id;
                App.setState({ visitId: result.visit_id });
                App.updateTitlebar(result.visit_id, false);

                addMessage('success',
                    '<p>' + App.icon('checkCircle', 14) + ' 音频上传成功</p>' +
                    '<p class="agent-hint">就诊ID: ' + App.escapeHtml(result.visit_id) + '</p>'
                );

                App.updateStatusBar('上传成功，开始转写...');
                App.emit('visitIdSet', { visitId: result.visit_id });

                await startTranscription(result.visit_id);
            } else {
                addMessage('error', '<p>上传失败: ' + (result.message || '未知错误') + '</p>');
                App.updateStatusBar('上传失败', 'error');
                isProcessing = false;
                if (processBtn) processBtn.disabled = false;
            }
        } catch (error) {
            addMessage('error', '<p>上传失败: ' + error.message + '</p>');
            App.updateStatusBar('上传失败', 'error');
            isProcessing = false;
            if (processBtn) processBtn.disabled = false;
        }
    }

    async function startTranscription(visitId) {
        addMessage('progress', '<p>' + App.icon('mic', 14) + ' 开始语音转写...</p>');

        try {
            var response = await fetch('/api/asr/transcribe/' + visitId, { method: 'POST' });
            var result = await response.json();

            if (result.success) {
                await pollTranscription(result.task_id, visitId);
            } else {
                addMessage('error', '<p>转写启动失败: ' + (result.message || '未知错误') + '</p>');
                isProcessing = false;
                var processBtn = document.getElementById('agentProcess');
                if (processBtn) processBtn.disabled = false;
            }
        } catch (error) {
            addMessage('error', '<p>转写请求失败: ' + error.message + '</p>');
            isProcessing = false;
            var processBtn = document.getElementById('agentProcess');
            if (processBtn) processBtn.disabled = false;
        }
    }

    function pollTranscription(taskId, visitId) {
        var maxAttempts = 60;
        var attempts = 0;

        function poll() {
            fetch('/api/task/' + taskId)
                .then(function(r) { return r.json(); })
                .then(function(result) {
                    if (result.status === 'completed') {
                        App.updateStatusBar('转写完成');

                        fetch('/api/asr/transcript/' + visitId)
                            .then(function(r) { return r.json(); })
                            .then(function(transcriptData) {
                                state.hasTranscription = true;
                                App.setState({ hasTranscription: true });
                                if (transcriptData.audio_duration) {
                                    state.audioDuration = transcriptData.audio_duration;
                                }
                                if (transcriptData.language) {
                                    state.language = transcriptData.language;
                                    App.updateStatusBarInfo({ language: transcriptData.language });
                                }

                                var turnCount = transcriptData.turns ? transcriptData.turns.length : 0;
                                App.updateStatusBarInfo({ speaker: turnCount + ' 轮次' });

                                updateLastMessage('progress',
                                    '<p>' + App.icon('mic', 14) + ' 语音转写完成，共识别 <strong>' + turnCount + '</strong> 个对话轮次</p>' +
                                    '<p class="agent-hint">时长: ' + App.formatDuration(state.audioDuration) + '</p>'
                                );

                                isProcessing = false;
                                var processBtn = document.getElementById('agentProcess');
                                if (processBtn) {
                                    processBtn.innerHTML = App.icon('sparkles', 14) + ' 生成病历';
                                    processBtn.disabled = false;
                                }

                                App.emit('transcriptionLoaded', transcriptData);
                            });
                    } else if (result.status === 'failed') {
                        updateLastMessage('error',
                            '<p>转写失败: ' + (result.error_message || '未知错误') + '</p>'
                        );
                        App.updateStatusBar('转写失败', 'error');
                        isProcessing = false;
                        var processBtn = document.getElementById('agentProcess');
                        if (processBtn) {
                            processBtn.innerHTML = App.icon('refreshCw', 14) + ' 重试转写';
                            processBtn.disabled = false;
                        }
                    } else if (attempts < maxAttempts) {
                        attempts++;
                        if (attempts % 3 === 0) {
                            updateLastMessage('progress',
                                '<p>' + App.icon('mic', 14) + ' 语音转写中... (' + attempts + '/' + maxAttempts + ')</p>' +
                                '<div class="stage-progress"><div class="stage-progress-bar" style="width:' +
                                (attempts / maxAttempts * 100) + '%"></div></div>'
                            );
                        }
                        setTimeout(poll, 2000);
                    } else {
                        updateLastMessage('error', '<p>转写超时，请刷新页面查看结果</p>');
                        App.updateStatusBar('转写超时', 'error');
                        isProcessing = false;
                    }
                })
                .catch(function(err) {
                    console.error('轮询失败:', err);
                    if (attempts < maxAttempts) {
                        attempts++;
                        setTimeout(poll, 2000);
                    }
                });
        }

        poll();
    }

    async function processEMR() {
        if (!state.visitId) {
            addMessage('error', '<p>请先上传音频并完成转写</p>');
            return;
        }
        isProcessing = true;
        var processBtn = document.getElementById('agentProcess');
        if (processBtn) processBtn.disabled = true;

        addMessage('agent', '<p>开始生成SOAP病历...</p>');
        App.updateStatusBar('正在生成病历...');

        var currentStageEl = null;

        try {
            var response = await fetch('/api/emr/process-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    visit_id: state.visitId,
                    use_llm: true,
                    save_intermediate: true
                })
            });

            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var eventType = '';
            var result = null;

            while (true) {
                var readResult = await reader.read();
                if (readResult.done) break;

                buffer += decoder.decode(readResult.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (line.startsWith('event: ')) {
                        eventType = line.substring(7);
                    } else if (line.startsWith('data: ')) {
                        var dataStr = line.substring(6);
                        try {
                            var data = JSON.parse(dataStr);
                            handleSSEEvent(eventType, data);
                            
                            if (eventType === 'complete') {
                                result = data;
                            }
                        } catch (e) {
                            console.error('SSE JSON parse error:', e);
                        }
                    }
                }
            }

            if (result && result.status === 'completed') {
                handleProcessComplete(result);
            }

        } catch (error) {
            var isNetworkError = error.name === 'TypeError' || 
                                 error.message.includes('NetworkError') ||
                                 error.message.includes('fetch') ||
                                 error.message.includes('network');
            
            if (isNetworkError) {
                addMessage('warning',
                    '<p>' + App.icon('alertTriangle', 14) + ' 连接已中断</p>' +
                    '<p class="agent-hint">后端可能仍在处理中，请稍后刷新页面查看结果</p>' +
                    '<p class="agent-hint" style="margin-top:8px;">' +
                    '<button class="check-status-btn" onclick="AgentModule.checkEMRStatus()">' +
                    App.icon('refreshCw', 12) + ' 检查病历状态</button></p>'
                );
                App.updateStatusBar('连接中断', 'warning');
            } else {
                addMessage('error', '<p>病历生成失败: ' + error.message + '</p>');
                App.updateStatusBar('病历生成失败', 'error');
            }
        } finally {
            isProcessing = false;
            if (processBtn) {
                processBtn.innerHTML = App.icon('refreshCw', 14) + ' 重新生成';
                processBtn.disabled = false;
            }
        }
    }

    function handleSSEEvent(eventType, data) {
        console.log('[DEBUG] SSE事件:', eventType, data);
        if (eventType === 'stage_update') {
            updateStageMessage(data.stage, data.name, data.status, data.detail);
        } else if (eventType === 'draft_ready') {
            console.log('[DEBUG] 收到draft_ready事件, data:', data);
            handleDraftReady(data);
        } else if (eventType === 'error') {
            addMessage('error', '<p>病历生成失败: ' + App.escapeHtml(data.error || '未知错误') + '</p>');
            App.updateStatusBar('病历生成失败', 'error');
            isProcessing = false;
        }
    }

    function updateStageMessage(stageNum, stageName, status, detail) {
        var type = status === 'running' ? 'progress' : 
                   status === 'completed' ? 'success' : 'error';

        var content = '<div class="stage-name">阶段' + stageNum + '/4: ' + stageName + '</div>';
        if (detail) {
            content += '<div class="stage-detail">' + App.escapeHtml(detail) + '</div>';
        }
        if (status === 'running') {
            content += '<div class="stage-progress"><div class="stage-progress-bar stage-progress-animated"></div></div>';
        }

        if (stageElements[stageNum]) {
            var el = stageElements[stageNum];
            el.className = 'agent-message ' + type;
            var iconEl = el.querySelector('.agent-message-icon');
            if (iconEl) {
                var newIcon = '';
                if (type === 'progress') newIcon = App.icon('loader', 16);
                else if (type === 'success') newIcon = App.icon('checkCircle', 14);
                else if (type === 'error') newIcon = App.icon('xCircle', 16);
                iconEl.innerHTML = newIcon;
            }
            var contentEl = el.querySelector('.agent-message-content');
            if (contentEl) contentEl.innerHTML = content;
        } else {
            stageElements[stageNum] = addMessage(type, content);
        }
    }

    function handleDraftReady(data) {
        console.log('[DEBUG] handleDraftReady开始:', data);
        if (!data.emr_draft) {
            console.log('[DEBUG] handleDraftReady: emr_draft为空, 跳过');
            return;
        }
        
        var draft = data.emr_draft;
        console.log('[DEBUG] draft内容:', draft);
        var emrRecord = {
            record_id: null,
            version: 0,
            emr_json: {
                subjective: draft.subjective || {},
                objective: draft.objective || {},
                assessment: draft.assessment || {},
                plan: draft.plan || {}
            }
        };
        
        console.log('[DEBUG] 构建emrRecord:', emrRecord);
        
        state.emrRecord = emrRecord;
        App.setState({
            emrRecord: emrRecord
        });
        
        addMessage('success',
            '<p>' + App.icon('sparkles', 14) + ' 草稿已生成！</p>' +
            '<p class="agent-hint">主编辑区已显示草稿，后台正在进行质量核查...</p>'
        );
        
        App.updateStatusBar('草稿已生成，正在进行质量核查...', 'success');
        
        App.emit('emrGenerated', { emrRecord: emrRecord });
    }

    function handleProcessComplete(result) {
        if (result.emr_record) {
            state.emrRecord = result.emr_record;
            state.currentRecordId = result.emr_record.record_id;
            App.setState({
                emrRecord: result.emr_record,
                currentRecordId: result.emr_record.record_id
            });
        }

        addMessage('success',
            '<p>' + App.icon('sparkles', 14) + ' 病历生成完毕！</p>' +
            '<p class="agent-hint">请在主编辑区查看病历内容</p>'
        );

        App.updateTitlebar(state.visitId, true);
        App.updateStatusBar('病历生成完成', 'success');

        if (state.visitId && result.emr_record) {
            CacheModule.saveEMRCache(state.visitId, {
                emrRecord: result.emr_record,
                versions: [],
                visitInfo: {}
            });

            fetch('/api/emr/visit/' + state.visitId)
                .then(function(r) { return r.json(); })
                .then(function(visitInfo) {
                    CacheModule.saveEMRCache(state.visitId, {
                        emrRecord: result.emr_record,
                        versions: [],
                        visitInfo: visitInfo
                    });
                })
                .catch(function() {});
        }

        App.emit('emrGenerated', { emrRecord: result.emr_record });

        if (result.verification_issues) {
            var issues = result.verification_issues;
            var unsupportedCount = (issues.unsupported_claims || []).length;
            var missingCount = (issues.missing_items || []).length;
            var violationCount = (issues.hard_rule_violations || []).length;
            var totalIssues = unsupportedCount + missingCount + violationCount;
            
            if (totalIssues > 0) {
                addMessage('warning',
                    '<p>' + App.icon('alertTriangle', 14) + ' 核查发现 ' + totalIssues + ' 个问题：</p>' +
                    '<p class="agent-hint">无依据声明 ' + unsupportedCount + ' 项 | 关键遗漏 ' + missingCount + ' 项 | 规则冲突 ' + violationCount + ' 项</p>'
                );
            } else {
                addMessage('success',
                    '<p>' + App.icon('checkCircle', 14) + ' 核查通过，无问题发现</p>'
                );
            }
        }
    }

    function checkEMRStatus() {
        if (!state.visitId) {
            addMessage('error', '<p>无法检查状态：缺少就诊ID</p>');
            return;
        }
        
        addMessage('agent', '<p>' + App.icon('loader', 14) + ' 正在检查病历状态...</p>');
        
        fetch('/api/emr/record/' + state.visitId)
            .then(function(r) { 
                if (r.status === 404) {
                    return { status: 'not_found' };
                }
                return r.json();
            })
            .then(function(data) {
                if (data.status === 'not_found' || !data.record_id) {
                    addMessage('agent',
                        '<p>' + App.icon('loader', 14) + ' 病历尚未生成完成</p>' +
                        '<p class="agent-hint">请稍后再试，或查看历史记录面板</p>'
                    );
                } else {
                    state.emrRecord = data;
                    state.currentRecordId = data.record_id;
                    App.setState({
                        emrRecord: data,
                        currentRecordId: data.record_id
                    });
                    
                    addMessage('success',
                        '<p>' + App.icon('checkCircle', 14) + ' 病历已生成完成！</p>' +
                        '<p class="agent-hint">请在主编辑区查看病历内容</p>'
                    );
                    
                    App.updateTitlebar(state.visitId, true);
                    App.updateStatusBar('病历生成完成', 'success');
                    
                    CacheModule.saveEMRCache(state.visitId, {
                        emrRecord: data,
                        versions: [],
                        visitInfo: {}
                    });
                    
                    App.emit('emrGenerated', { emrRecord: data });
                    
                    var processBtn = document.getElementById('agentProcess');
                    if (processBtn) {
                        processBtn.innerHTML = App.icon('refreshCw', 14) + ' 重新生成';
                        processBtn.disabled = false;
                    }
                }
            })
            .catch(function(e) {
                addMessage('error', '<p>检查状态失败: ' + e.message + '</p>');
            });
    }

    document.addEventListener('DOMContentLoaded', function() {
        initAgent();
    });

    return {
        addMessage: addMessage,
        addStageMessage: addStageMessage,
        updateLastMessage: updateLastMessage,
        checkEMRStatus: checkEMRStatus
    };
})();