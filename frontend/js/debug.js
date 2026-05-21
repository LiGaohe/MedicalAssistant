window.DebugModule = (function() {
    var state = App.getState();
    var debugStages = [];
    var currentStageIndex = 0;
    var debugContext = {};

    function initDebug() {
        var stageSelect = document.getElementById('debugStageSelect');
        var promptContent = document.getElementById('debugPromptContent');
        var instructionsContent = document.getElementById('debugInstructionsContent');
        var userResponse = document.getElementById('debugUserResponse');
        var submitBtn = document.getElementById('debugSubmitStage');
        var skipBtn = document.getElementById('debugSkipStage');
        var resultSection = document.getElementById('debugResultSection');
        var resultContent = document.getElementById('debugResultContent');
        var copyBtn = document.getElementById('debugCopyPrompt');
        var closeBtn = document.getElementById('closeDebugPanel');

        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                App.setActivePanel('agent');
            });
        }

        if (stageSelect) {
            stageSelect.addEventListener('change', function() {
                currentStageIndex = parseInt(this.value);
                displayCurrentStage();
            });
        }

        if (submitBtn) {
            submitBtn.addEventListener('click', async function() {
                if (!debugStages.length) return;
                var stage = debugStages[currentStageIndex];
                var response = userResponse.value.trim();

                if (stage.auto_process) {
                } else if (!response) {
                    alert('请输入大模型返回结果');
                    return;
                }

                try {
                    var contextToSend = Object.assign({}, debugContext);
                    if (stage.segment_index !== undefined) {
                        contextToSend.segment_index = stage.segment_index;
                    }

                    var result = await fetch('/api/emr/debug/process-stage', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            visit_id: state.visitId,
                            stage: stage.stage,
                            user_response: response,
                            context: contextToSend
                        })
                    }).then(function(r) { return r.json(); });

                    if (result.status === 'success') {
                        resultSection.style.display = 'block';
                        resultContent.textContent = JSON.stringify(result.result, null, 2);

                        if (result.context_update) {
                            Object.assign(debugContext, result.context_update);
                        }

                        if (result.next_stage) {
                            var nextIndex = debugStages.findIndex(function(s) {
                                return s.stage === result.next_stage;
                            });
                            if (nextIndex !== -1 && nextIndex > currentStageIndex) {
                                currentStageIndex = nextIndex;
                                stageSelect.value = currentStageIndex;

                                if (result.next_prompt) {
                                    debugStages[currentStageIndex].prompt = result.next_prompt;
                                }
                                if (result.next_description) {
                                    debugStages[currentStageIndex].description = result.next_description;
                                    stageSelect.innerHTML = debugStages.map(function(s, idx) {
                                        return '<option value="' + idx + '">' + s.description + '</option>';
                                    }).join('');
                                    stageSelect.value = currentStageIndex;
                                }
                                if (result.next_segment_index !== undefined && result.next_segment_index !== null) {
                                    debugStages[currentStageIndex].segment_index = result.next_segment_index;
                                }

                                displayCurrentStage();
                                userResponse.value = '';
                            }
                        } else if (result.completed) {
                            alert('所有阶段处理完成！');
                            App.emit('debugCompleted', result);
                            window.location.reload();
                        }
                    } else {
                        alert('处理失败: ' + (result.error || '未知错误'));
                    }
                } catch (error) {
                    alert('请求失败: ' + error.message);
                }
            });
        }

        if (skipBtn) {
            skipBtn.addEventListener('click', function() {
                if (currentStageIndex < debugStages.length - 1) {
                    currentStageIndex++;
                    stageSelect.value = currentStageIndex;
                    displayCurrentStage();
                    userResponse.value = '';
                }
            });
        }

        if (copyBtn) {
            copyBtn.addEventListener('click', function() {
                var text = promptContent.textContent;
                if (!text || text === '无提示词') {
                    alert('没有可复制的内容');
                    return;
                }

                if (navigator.clipboard) {
                    navigator.clipboard.writeText(text).then(function() {
                        copyBtn.textContent = '已复制';
                        copyBtn.classList.add('copied');
                        setTimeout(function() {
                            copyBtn.textContent = '复制';
                            copyBtn.classList.remove('copied');
                        }, 1500);
                    }).catch(function() {
                        fallbackCopy(text, copyBtn);
                    });
                } else {
                    fallbackCopy(text, copyBtn);
                }
            });
        }

        App.on('panelChanged', function(panelName) {
            if (panelName === 'debug' && state.visitId) {
                loadDebugPrompts();
            }
        });
    }

    function fallbackCopy(text, button) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;opacity:0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            button.textContent = '已复制';
            button.classList.add('copied');
            setTimeout(function() {
                button.textContent = '复制';
                button.classList.remove('copied');
            }, 1500);
        } catch (e) {
            alert('复制失败，请手动复制');
        }
        document.body.removeChild(textarea);
    }

    async function loadDebugPrompts() {
        try {
            var response = await fetch('/api/emr/debug/prompts/' + state.visitId);
            var data = await response.json();

            debugStages = data.stages;
            currentStageIndex = 0;
            debugContext = {};

            var select = document.getElementById('debugStageSelect');
            select.innerHTML = debugStages.map(function(stage, index) {
                return '<option value="' + index + '">' + stage.description + '</option>';
            }).join('');

            displayCurrentStage();
            App.updateStatusBar('调试模式已加载 ' + debugStages.length + ' 个阶段');
        } catch (error) {
            alert('加载提示词失败: ' + error.message);
        }
    }

    function displayCurrentStage() {
        if (!debugStages.length) return;
        var stage = debugStages[currentStageIndex];
        document.getElementById('debugPromptContent').textContent = stage.prompt || '无提示词';
        document.getElementById('debugInstructionsContent').textContent = stage.instructions || '无指导步骤';
        document.getElementById('debugUserResponse').value = '';
        document.getElementById('debugResultSection').style.display = 'none';
    }

    document.addEventListener('DOMContentLoaded', function() {
        initDebug();
    });

    return {
        loadDebugPrompts: loadDebugPrompts
    };
})();