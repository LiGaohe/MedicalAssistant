window.AgentModule = (function() {
    var state = App.getState();
    var selectedFile = null;
    var isProcessing = false;
    var uploadInProgress = false;
    var stageElements = {};
    var receivedPhaseComplete = false;

    var pipelineMode = 'quick';
    var enableHallucinationCheck = false;
    var enablePostVerification = false;

    /**
     * 渲染流程选择UI组件
     * @returns {string} HTML字符串
     */
    function renderPipelineModeSelector() {
        var currentModeName = getModeDisplayName(pipelineMode);
        var html = '<div class="pipeline-mode-selector" id="pipelineModeSelector">' +
            '<div class="pipeline-mode-header" id="pipelineModeHeader">' +
            '<span class="pipeline-mode-header-label">生成模式</span>' +
            '<span class="pipeline-mode-header-value" id="pipelineModeHeaderValue">' + App.escapeHtml(currentModeName) + '</span>' +
            '<span class="pipeline-mode-header-arrow" id="pipelineModeHeaderArrow">▼</span>' +
            '</div>' +
            '<div class="pipeline-mode-body" id="pipelineModeBody">' +
            '<div class="pipeline-mode-options">' +
            // 快速草稿模式（推荐）
            '<div class="pipeline-mode-option' + (pipelineMode === 'quick' ? ' selected' : '') + '" data-mode="quick">' +
            '<div class="mode-radio">' +
            '<span class="radio-icon">' + (pipelineMode === 'quick' ? App.icon('checkCircle', 14) : App.icon('circle', 14)) + '</span>' +
            '<span class="mode-label">快速草稿（推荐）</span>' +
            '</div>' +
            '<div class="mode-desc">仅生成草稿，最快速度</div>' +
            '</div>' +
            // 标准流程模式
            '<div class="pipeline-mode-option' + (pipelineMode === 'standard' ? ' selected' : '') + '" data-mode="standard">' +
            '<div class="mode-radio">' +
            '<span class="radio-icon">' + (pipelineMode === 'standard' ? App.icon('checkCircle', 14) : App.icon('circle', 14)) + '</span>' +
            '<span class="mode-label">标准流程</span>' +
            '</div>' +
            '<div class="mode-desc">转写清洗 + 草稿生成</div>' +
            '</div>' +
            // 完整流程模式
            '<div class="pipeline-mode-option' + (pipelineMode === 'full' ? ' selected' : '') + '" data-mode="full">' +
            '<div class="mode-radio">' +
            '<span class="radio-icon">' + (pipelineMode === 'full' ? App.icon('checkCircle', 14) : App.icon('circle', 14)) + '</span>' +
            '<span class="mode-label">完整流程</span>' +
            '</div>' +
            '<div class="mode-desc">全流程：清洗→草稿→核查→修订</div>' +
            '</div>' +
            '</div>' +
            // 可选复选框
            '<div class="pipeline-mode-checkboxes">' +
            '<div class="pipeline-checkbox' + (enableHallucinationCheck ? ' checked' : '') + '" id="hallucinationCheckToggle">' +
            '<span class="checkbox-icon">' + (enableHallucinationCheck ? App.icon('checkSquare', 14) : App.icon('square', 14)) + '</span>' +
            '<span class="checkbox-label">启用幻觉检查</span>' +
            '</div>' +
            '<div class="pipeline-checkbox' + (enablePostVerification ? ' checked' : '') + '" id="postVerificationToggle">' +
            '<span class="checkbox-icon">' + (enablePostVerification ? App.icon('checkSquare', 14) : App.icon('square', 14)) + '</span>' +
            '<span class="checkbox-label">启用后置核查</span>' +
            '</div>' +
            '</div>' +
            '</div>' +
            '</div>';
        return html;
    }

    /**
     * 初始化流程选择组件事件绑定
     */
    function initPipelineModeSelectorEvents() {
        var selector = document.getElementById('pipelineModeSelector');
        if (!selector) return;

        var header = document.getElementById('pipelineModeHeader');
        if (header) {
            header.addEventListener('click', function() {
                togglePipelineModeBody();
            });
        }

        selector.querySelectorAll('.pipeline-mode-option').forEach(function(option) {
            option.addEventListener('click', function(e) {
                e.stopPropagation();
                var mode = this.getAttribute('data-mode');
                setPipelineMode(mode);
            });
        });

        var hallucinationToggle = document.getElementById('hallucinationCheckToggle');
        if (hallucinationToggle) {
            hallucinationToggle.addEventListener('click', function(e) {
                e.stopPropagation();
                enableHallucinationCheck = !enableHallucinationCheck;
                updateCheckboxState(this, enableHallucinationCheck);
            });
        }

        var postVerificationToggle = document.getElementById('postVerificationToggle');
        if (postVerificationToggle) {
            postVerificationToggle.addEventListener('click', function(e) {
                e.stopPropagation();
                enablePostVerification = !enablePostVerification;
                updateCheckboxState(this, enablePostVerification);
            });
        }
    }

    var pipelineModeBodyExpanded = false;

    function togglePipelineModeBody() {
        var body = document.getElementById('pipelineModeBody');
        var arrow = document.getElementById('pipelineModeHeaderArrow');
        if (!body) return;

        pipelineModeBodyExpanded = !pipelineModeBodyExpanded;
        if (pipelineModeBodyExpanded) {
            body.style.display = 'block';
            if (arrow) arrow.textContent = '▲';
        } else {
            body.style.display = 'none';
            if (arrow) arrow.textContent = '▼';
        }
    }

    /**
     * 设置流程模式
     * @param {string} mode - 模式名称 (quick/standard/full)
     */
    function setPipelineMode(mode) {
        pipelineMode = mode;
        var selector = document.getElementById('pipelineModeSelector');
        if (!selector) return;

        selector.querySelectorAll('.pipeline-mode-option').forEach(function(option) {
            var optionMode = option.getAttribute('data-mode');
            if (optionMode === mode) {
                option.classList.add('selected');
                option.querySelector('.radio-icon').innerHTML = App.icon('checkCircle', 14);
            } else {
                option.classList.remove('selected');
                option.querySelector('.radio-icon').innerHTML = App.icon('circle', 14);
            }
        });

        var headerValue = document.getElementById('pipelineModeHeaderValue');
        if (headerValue) {
            headerValue.textContent = getModeDisplayName(mode);
        }

        if (pipelineModeBodyExpanded) {
            pipelineModeBodyExpanded = false;
            var body = document.getElementById('pipelineModeBody');
            var arrow = document.getElementById('pipelineModeHeaderArrow');
            if (body) body.style.display = 'none';
            if (arrow) arrow.textContent = '▼';
        }

        console.log('[PipelineModeSelector] 模式切换为: ' + mode);
    }

    /**
     * 更新复选框状态
     * @param {HTMLElement} checkboxEl - 复选框元素
     * @param {boolean} checked - 是否选中
     */
    function updateCheckboxState(checkboxEl, checked) {
        if (checked) {
            checkboxEl.classList.add('checked');
            checkboxEl.querySelector('.checkbox-icon').innerHTML = App.icon('checkSquare', 14);
        } else {
            checkboxEl.classList.remove('checked');
            checkboxEl.querySelector('.checkbox-icon').innerHTML = App.icon('square', 14);
        }
    }

    /**
     * 获取当前流程参数配置
     * @returns {Object} 参数对象
     */
    function getPipelineParams() {
        var params = {
            skip_cleaning: true,
            skip_hallucination_check: true,
            stop_after_draft: true
        };

        // 根据模式设置参数
        if (pipelineMode === 'quick') {
            // 快速草稿：skip_cleaning=true&skip_hallucination_check=true&stop_after_draft=true
            params.skip_cleaning = true;
            params.skip_hallucination_check = true;
            params.stop_after_draft = true;
        } else if (pipelineMode === 'standard') {
            // 标准流程：skip_cleaning=false&skip_hallucination_check=true&stop_after_draft=true
            params.skip_cleaning = false;
            params.skip_hallucination_check = true;
            params.stop_after_draft = true;
        } else if (pipelineMode === 'full') {
            // 完整流程：skip_cleaning=false&skip_hallucination_check=false&stop_after_draft=false
            params.skip_cleaning = false;
            params.skip_hallucination_check = false;
            params.stop_after_draft = false;
        }

        // 复选框覆盖参数
        if (enableHallucinationCheck) {
            params.skip_hallucination_check = false;
        }
        if (enablePostVerification) {
            params.stop_after_draft = false;
        }

        console.log('[PipelineModeSelector] 当前参数配置:', params);
        return params;
    }

    /**
     * 获取模式的显示名称
     * @param {string} mode - 模式名称
     * @returns {string} 显示名称
     */
    function getModeDisplayName(mode) {
        var names = {
            'quick': '快速草稿',
            'standard': '标准流程',
            'full': '完整流程'
        };
        return names[mode] || mode;
    }

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
                    
                    renderAndInitPipelineSelector();
                }
            });
        }

        renderAndInitPipelineSelector();
        initActionBar();
    }
    
    /**
     * 渲染并初始化流程选择组件
     */
    function renderAndInitPipelineSelector() {
        var inputArea = document.querySelector('.agent-input-area');
        if (!inputArea) return;
        
        // 检查是否已存在组件，如果存在则移除
        var existingSelector = document.getElementById('pipelineModeSelector');
        if (existingSelector) {
            existingSelector.remove();
        }
        
        // 在上传区域之后插入流程选择组件
        var uploadZone = document.getElementById('agentDropZone');
        if (uploadZone) {
            var selectorDiv = document.createElement('div');
            selectorDiv.innerHTML = renderPipelineModeSelector();
            uploadZone.parentNode.insertBefore(selectorDiv.firstChild, uploadZone.nextSibling);
            
            // 初始化事件绑定
            initPipelineModeSelectorEvents();
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
        receivedPhaseComplete = false;
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

        // 获取流程参数配置
        var pipelineParams = getPipelineParams();
        
        // 构建Query参数URL（后端API期望控制参数作为Query参数）
        var queryParams = new URLSearchParams({
            stop_after_draft: pipelineParams.stop_after_draft,
            skip_cleaning: pipelineParams.skip_cleaning,
            skip_hallucination_check: pipelineParams.skip_hallucination_check
        });
        var sseUrl = '/api/emr/process-stream?' + queryParams.toString();
        
        // 构建模式描述信息
        var modeDesc = getModeDisplayName(pipelineMode);
        var extraFeatures = [];
        if (enableHallucinationCheck) extraFeatures.push('幻觉检查');
        if (enablePostVerification) extraFeatures.push('后置核查');
        if (extraFeatures.length > 0) {
            modeDesc += ' | ' + extraFeatures.join(' | ');
        }
        
        addMessage('agent', '<p>开始生成SOAP病历...</p>' +
            '<p class="agent-hint">执行模式: ' + modeDesc + '</p>');
        App.updateStatusBar('正在生成病历 [' + modeDesc + ']...');

        // 重置阶段跟踪状态
        stageElements = {};
        stageIdMap = {};
        executedStageCount = 0;
        receivedPhaseComplete = false;

        try {
            var response = await fetch(sseUrl, {
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

            if (!result && receivedPhaseComplete) {
                App.updateStatusBar('草稿阶段完成，请选择后处理', 'success');
            } else if (!result && !receivedPhaseComplete) {
                addMessage('error', '<p>病历生成未完成：未收到完成信号</p>');
                App.updateStatusBar('病历生成未完成', 'error');
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

    // 阶段计数器：跟踪实际执行的阶段数量
    var executedStageCount = 0;
    var stageIdMap = {}; // 将后端stage编号映射到实际执行顺序
    
    function handleSSEEvent(eventType, data) {
        console.log('[DEBUG] SSE事件:', eventType, data);
        if (eventType === 'stage_update') {
            if (data.status === 'skipped') {
                console.log('[DEBUG] 阶段跳过:', data.stage, data.name);
                return;
            }
            updateStageMessage(data.stage, data.name, data.status, data.detail);
        } else if (eventType === 'draft_ready') {
            console.log('[DEBUG] 收到draft_ready事件, data:', data);
            handleDraftReady(data);
        } else if (eventType === 'draft_text_ready') {
            console.log('[DEBUG] 收到draft_text_ready事件, data:', data);
            if (data.draft_text) {
                addMessage('success',
                    '<p>' + App.icon('sparkles', 14) + ' 草稿已生成</p>' +
                    '<p class="agent-hint">可在编辑器中查看/编辑病历，点击右下角按钮继续处理或保存</p>'
                );
                App.updateStatusBar('草稿已生成', 'success');
            }
        } else if (eventType === 'error') {
            addMessage('error', '<p>病历生成失败: ' + App.escapeHtml(data.error || '未知错误') + '</p>');
            App.updateStatusBar('病历生成失败', 'error');
            isProcessing = false;
        } else if (eventType === 'phase_complete') {
            handlePhaseComplete(data);
        }
    }

    function updateStageMessage(stageNum, stageName, status, detail) {
        var type = status === 'running' ? 'progress' : 
                   status === 'completed' ? 'success' : 'error';

        // 动态计算实际执行的阶段顺序
        if (!stageIdMap[stageNum] && status !== 'skipped') {
            executedStageCount++;
            stageIdMap[stageNum] = executedStageCount;
        }
        var actualStageIndex = stageIdMap[stageNum] || executedStageCount;
        
        // 计算总阶段数（根据当前模式）
        var totalStages = 4; // 默认完整流程4阶段
        var params = getPipelineParams();
        if (params.skip_cleaning) totalStages--; // 跳过清洗阶段
        if (params.skip_hallucination_check) totalStages--; // 跳过幻觉检查
        if (params.stop_after_draft) totalStages = Math.min(totalStages, 2); // 草稿后停止
        
        // 确保总阶段数至少为当前已执行阶段数
        totalStages = Math.max(totalStages, actualStageIndex);

        var content = '<div class="stage-name">阶段' + actualStageIndex + '/' + totalStages + ': ' + stageName + '</div>';
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
        
        // 更新状态栏显示当前阶段
        if (status === 'running') {
            App.updateStatusBar('正在处理: ' + stageName + ' [' + actualStageIndex + '/' + totalStages + ']');
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
            '<p class="agent-hint">主编辑区已显示草稿，等待后处理...</p>'
        );
        
        App.updateStatusBar('草稿已生成，等待后处理...', 'success');
        
        App.emit('emrGenerated', { emrRecord: emrRecord });
    }

    function handlePhaseComplete(data) {
        receivedPhaseComplete = true;
        addMessage('success',
            '<p>' + App.icon('checkCircle', 14) + ' 草稿生成阶段完成</p>' +
            '<p class="agent-hint">可在编辑器中查看/编辑病历，点击右下角按钮继续处理或保存</p>'
        );
        updateActionBarState('draft_complete');
    }

    var pipelineState = {
        currentStageIndex: 2,
        stageNames: ['转写清洗', '草稿生成', '证据溯源', '幻觉检查', '完成'],
        canFinalize: false
    };

    function initActionBar() {
        var nextStageBtn = document.getElementById('nextStageBtn');
        var finalizeEMRBtn = document.getElementById('finalizeEMRBtn');

        if (nextStageBtn) {
            nextStageBtn.addEventListener('click', function() {
                executeNextStage();
            });
        }

        if (finalizeEMRBtn) {
            finalizeEMRBtn.addEventListener('click', function() {
                finalizeEMRRecord();
            });
        }

        updateActionBarState('initial');
    }

    function updateActionBarState(stateName) {
        var stageLabel = document.getElementById('currentStageLabel');
        var nextStageBtn = document.getElementById('nextStageBtn');
        var finalizeEMRBtn = document.getElementById('finalizeEMRBtn');

        if (stateName === 'initial') {
            if (stageLabel) stageLabel.textContent = '当前阶段：未开始';
            if (nextStageBtn) { nextStageBtn.textContent = '下一步'; nextStageBtn.disabled = true; }
            if (finalizeEMRBtn) { finalizeEMRBtn.disabled = true; }
            pipelineState.currentStageIndex = 0;
            pipelineState.canFinalize = false;
        } else if (stateName === 'draft_complete') {
            if (stageLabel) stageLabel.textContent = '当前阶段：草稿生成';
            if (nextStageBtn) { nextStageBtn.textContent = '证据溯源'; nextStageBtn.disabled = false; }
            if (finalizeEMRBtn) { finalizeEMRBtn.disabled = false; }
            pipelineState.currentStageIndex = 2;
            pipelineState.canFinalize = true;
        } else if (stateName === 'evidence_complete') {
            if (stageLabel) stageLabel.textContent = '当前阶段：证据溯源';
            if (nextStageBtn) { nextStageBtn.textContent = '幻觉检查'; nextStageBtn.disabled = false; }
            if (finalizeEMRBtn) { finalizeEMRBtn.disabled = false; }
            pipelineState.currentStageIndex = 3;
            pipelineState.canFinalize = true;
        } else if (stateName === 'hallucination_complete') {
            if (stageLabel) stageLabel.textContent = '当前阶段：幻觉检查';
            if (nextStageBtn) { nextStageBtn.textContent = '完成'; nextStageBtn.disabled = true; }
            if (finalizeEMRBtn) { finalizeEMRBtn.disabled = false; }
            pipelineState.currentStageIndex = 4;
            pipelineState.canFinalize = true;
        } else if (stateName === 'complete') {
            if (stageLabel) stageLabel.textContent = '当前阶段：已完成';
            if (nextStageBtn) { nextStageBtn.disabled = true; }
            if (finalizeEMRBtn) { finalizeEMRBtn.disabled = false; }
            pipelineState.currentStageIndex = 5;
            pipelineState.canFinalize = true;
        }
    }

    async function executeNextStage() {
        var nextStageBtn = document.getElementById('nextStageBtn');
        if (nextStageBtn) {
            nextStageBtn.disabled = true;
            nextStageBtn.innerHTML = App.icon('loader', 14) + ' 处理中...';
        }

        App.updateStatusBar('正在执行下一阶段处理...');

        var emrDraft = state.emrRecord ? state.emrRecord.emr_json : null;

        try {
            var response = await fetch('/api/emr/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    visit_id: state.visitId,
                    mode: 'next_stage_only',
                    current_stage: pipelineState.currentStageIndex,
                    emr_draft: emrDraft
                })
            });
            var result = await response.json();

            if (result.status === 'success') {
                if (result.emr_record && result.emr_record.emr_json) {
                    state.emrRecord = { emr_json: result.emr_record.emr_json };
                    App.setState({ emrRecord: state.emrRecord });
                    EditorModule.displayEMR(state.emrRecord);
                }

                var newState = '';
                if (pipelineState.currentStageIndex === 2) newState = 'evidence_complete';
                else if (pipelineState.currentStageIndex === 3) newState = 'hallucination_complete';
                else if (pipelineState.currentStageIndex === 4) newState = 'complete';

                updateActionBarState(newState);
                addMessage('success', '<p>' + App.icon('checkCircle', 14) + ' 阶段处理完成</p>');
                App.updateStatusBar('阶段处理完成', 'success');
            } else {
                addMessage('error', '<p>处理失败: ' + App.escapeHtml(result.errors ? result.errors.join(', ') : '未知错误') + '</p>');
                App.updateStatusBar('处理失败', 'error');
                if (nextStageBtn) nextStageBtn.disabled = false;
            }
        } catch (error) {
            addMessage('error', '<p>请求失败: ' + error.message + '</p>');
            App.updateStatusBar('请求失败', 'error');
            if (nextStageBtn) nextStageBtn.disabled = false;
        } finally {
            if (nextStageBtn && !nextStageBtn.disabled) {
                nextStageBtn.innerHTML = pipelineState.currentStageIndex < 4 ? pipelineState.stageNames[pipelineState.currentStageIndex + 1] : '完成';
            }
        }
    }

    async function finalizeEMRRecord() {
        var finalizeEMRBtn = document.getElementById('finalizeEMRBtn');
        if (finalizeEMRBtn) {
            finalizeEMRBtn.disabled = true;
            finalizeEMRBtn.innerHTML = App.icon('loader', 14) + ' 保存中...';
        }

        App.updateStatusBar('正在保存病历...');

        var emrDraft = state.emrRecord ? state.emrRecord.emr_json : null;

        try {
            var response = await fetch('/api/emr/finalize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ visit_id: state.visitId, emr_draft: emrDraft })
            });
            var result = await response.json();

            if (result.status === 'success' || response.ok) {
                addMessage('success',
                    '<p>' + App.icon('checkCircle', 14) + ' 病历已保存</p>'
                );

                if (result.record_id) {
                    state.emrRecord.record_id = result.record_id;
                }
                if (result.version !== undefined) {
                    state.emrRecord.version = result.version;
                }
                App.setState({ emrRecord: state.emrRecord });

                App.updateStatusBar('病历已保存', 'success');
                App.updateTitlebar(state.visitId, true);
                updateActionBarState('complete');
            } else {
                addMessage('error', '<p>病历保存失败: ' + App.escapeHtml(result.error || '未知错误') + '</p>');
                App.updateStatusBar('病历保存失败', 'error');
                if (finalizeEMRBtn) finalizeEMRBtn.disabled = false;
            }
        } catch (error) {
            addMessage('error', '<p>病历保存失败: ' + error.message + '</p>');
            App.updateStatusBar('病历保存失败', 'error');
            if (finalizeEMRBtn) finalizeEMRBtn.disabled = false;
        } finally {
            if (finalizeEMRBtn && !finalizeEMRBtn.disabled) {
                finalizeEMRBtn.innerHTML = App.icon('save', 14) + ' 保存病历';
            }
        }
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