document.addEventListener('DOMContentLoaded', async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const visitId = urlParams.get('visit_id');
    
    if (!visitId) {
        alert('缺少visit_id参数');
        return;
    }
    
    document.getElementById('visitId').textContent = visitId;
    
    const generateBtn = document.getElementById('generateEMR');
    const viewBtn = document.getElementById('viewEMR');
    const backBtn = document.getElementById('backToResult');
    const loadingSection = document.getElementById('loadingSection');
    const emrSection = document.getElementById('emrSection');
    
    await loadEMRStatus(visitId);
    
    generateBtn.addEventListener('click', async () => {
        generateBtn.disabled = true;
        loadingSection.style.display = 'block';
        
        try {
            const response = await fetch('/api/emr/process', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    visit_id: visitId,
                    use_llm: true,
                    save_intermediate: true
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'completed') {
                loadingSection.style.display = 'none';
                emrSection.style.display = 'block';
                viewBtn.style.display = 'none';
                await displayEMR(result.emr_record);
                await loadEMRVersions(visitId);
            } else {
                throw new Error(result.errors?.join(', ') || '病历生成失败');
            }
        } catch (error) {
            alert('病历生成失败: ' + error.message);
            generateBtn.disabled = false;
            loadingSection.style.display = 'none';
        }
    });
    
    viewBtn.addEventListener('click', async () => {
        emrSection.style.display = 'block';
        viewBtn.style.display = 'none';
        await loadEMRVersions(visitId);
    });
    
    backBtn.addEventListener('click', () => {
        window.location.href = `/static/result.html?visit_id=${visitId}`;
    });
    
    document.getElementById('versionSelect').addEventListener('change', async (e) => {
        const version = e.target.value;
        if (version) {
            await loadEMRByVersion(visitId, version);
        }
    });
    
    async function loadEMRStatus(visitId) {
        try {
            const response = await fetch(`/api/emr/status/${visitId}`);
            const result = await response.json();
            
            document.getElementById('status').textContent = 
                result.has_emr ? '已生成病历' : '未生成病历';
            
            if (result.has_emr) {
                viewBtn.style.display = 'block';
                generateBtn.textContent = '重新生成病历';
            }
        } catch (error) {
            console.error('加载病历状态失败:', error);
        }
    }
    
    async function loadEMRVersions(visitId) {
        try {
            const response = await fetch(`/api/emr/versions/${visitId}`);
            const result = await response.json();
            
            const select = document.getElementById('versionSelect');
            select.innerHTML = '';
            
            result.versions.forEach(v => {
                const option = document.createElement('option');
                option.value = v.version;
                
                let timeStr = '未知时间';
                if (v.created_at) {
                    try {
                        const date = new Date(v.created_at);
                        timeStr = date.toLocaleString('zh-CN', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                        });
                    } catch (e) {
                        console.error('时间解析错误:', e);
                    }
                }
                
                option.textContent = `版本 ${v.version} (${v.record_type}) - ${timeStr}`;
                select.appendChild(option);
            });
            
            if (result.versions.length > 0) {
                await loadEMRByVersion(visitId, result.versions[0].version);
            }
        } catch (error) {
            console.error('加载病历版本失败:', error);
        }
    }
    
    async function loadEMRByVersion(visitId, version) {
        try {
            const response = await fetch(`/api/emr/record/${visitId}?version=${version}`);
            const result = await response.json();
            await displayEMR(result);
        } catch (error) {
            console.error('加载病历失败:', error);
        }
    }
    
    async function displayEMR(emrRecord) {
        const emrJson = emrRecord.emr_json;
        
        displaySection('subjectiveContent', emrJson.subjective);
        displaySection('objectiveContent', emrJson.objective);
        displaySection('assessmentContent', emrJson.assessment);
        displaySection('planContent', emrJson.plan);
    }
    
    function displaySection(elementId, sectionData) {
        const element = document.getElementById(elementId);
        
        if (!sectionData) {
            element.innerHTML = '<p class="empty">暂无数据</p>';
            return;
        }
        
        let html = '';
        
        if (sectionData.text !== undefined && sectionData.text !== null) {
            html += `<div class="section-text">${sectionData.text || '暂无内容'}</div>`;
        }
        
        const fields = Object.keys(sectionData).filter(k => k !== 'text');
        if (fields.length > 0) {
            html += '<div class="section-fields">';
            fields.forEach(field => {
                const fieldData = sectionData[field];
                if (fieldData && fieldData.value !== undefined && fieldData.value !== null) {
                    html += `
                        <div class="field-item">
                            <div class="field-name">${getFieldName(field)}</div>
                            <div class="field-value">${fieldData.value || '暂无'}</div>
                            <div class="field-meta">
                                置信度: ${((fieldData.confidence || 0) * 100).toFixed(1)}%
                            </div>
                        </div>
                    `;
                }
            });
            html += '</div>';
        }
        
        element.innerHTML = html || '<p class="empty">暂无数据</p>';
    }
    
    function getFieldName(field) {
        const nameMap = {
            'chief_complaint': '主诉',
            'history_present_illness': '现病史',
            'past_history': '既往史',
            'physical_examination': '体格检查',
            'auxiliary_examination': '辅助检查',
            'diagnosis': '诊断',
            'treatment': '治疗方案',
            'advice': '医嘱'
        };
        return nameMap[field] || field;
    }
    
    const debugBtn = document.getElementById('debugEMR');
    const debugModal = document.getElementById('debugModal');
    const closeDebugModal = document.getElementById('closeDebugModal');
    const stageSelect = document.getElementById('stageSelect');
    const promptContent = document.getElementById('promptContent');
    const instructionsContent = document.getElementById('instructionsContent');
    const userResponse = document.getElementById('userResponse');
    const submitStage = document.getElementById('submitStage');
    const skipStage = document.getElementById('skipStage');
    const debugResult = document.getElementById('debugResult');
    const resultContent = document.getElementById('resultContent');
    
    let debugStages = [];
    let currentStageIndex = 0;
    let debugContext = {};
    
    debugBtn.addEventListener('click', async () => {
        debugModal.style.display = 'block';
        await loadDebugPrompts();
    });
    
    closeDebugModal.addEventListener('click', () => {
        debugModal.style.display = 'none';
    });
    
    window.addEventListener('click', (e) => {
        if (e.target === debugModal) {
            debugModal.style.display = 'none';
        }
    });
    
    stageSelect.addEventListener('change', () => {
        currentStageIndex = parseInt(stageSelect.value);
        displayCurrentStage();
    });
    
    submitStage.addEventListener('click', async () => {
        const response = userResponse.value.trim();
        if (!response) {
            alert('请输入大模型返回结果');
            return;
        }
        
        try {
            const stage = debugStages[currentStageIndex];
            const contextToSend = { ...debugContext };
            if (stage.segment_index !== undefined) {
                contextToSend.segment_index = stage.segment_index;
            }
            
            const result = await fetch('/api/emr/debug/process-stage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    visit_id: visitId,
                    stage: stage.stage,
                    user_response: response,
                    context: contextToSend
                })
            }).then(r => r.json());
            
            if (result.status === 'success') {
                debugResult.style.display = 'block';
                resultContent.textContent = JSON.stringify(result.result, null, 2);
                
                if (result.context_update) {
                    debugContext = { ...debugContext, ...result.context_update };
                }
                
                if (result.next_stage) {
                    const nextIndex = debugStages.findIndex(s => s.stage === result.next_stage);
                    if (nextIndex !== -1 && nextIndex > currentStageIndex) {
                        currentStageIndex = nextIndex;
                        stageSelect.value = currentStageIndex;
                        
                        if (result.next_prompt) {
                            debugStages[currentStageIndex].prompt = result.next_prompt;
                        }
                        if (result.next_description) {
                            debugStages[currentStageIndex].description = result.next_description;
                            stageSelect.innerHTML = debugStages.map((s, idx) => 
                                `<option value="${idx}">${s.description}</option>`
                            ).join('');
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
                    debugModal.style.display = 'none';
                    location.reload();
                }
            } else {
                alert('处理失败: ' + (result.error || '未知错误'));
            }
        } catch (error) {
            alert('请求失败: ' + error.message);
        }
    });
    
    skipStage.addEventListener('click', () => {
        if (currentStageIndex < debugStages.length - 1) {
            currentStageIndex++;
            stageSelect.value = currentStageIndex;
            displayCurrentStage();
            userResponse.value = '';
        }
    });
    
    async function loadDebugPrompts() {
        try {
            const response = await fetch(`/api/emr/debug/prompts/${visitId}`);
            const data = await response.json();
            
            debugStages = data.stages;
            currentStageIndex = 0;
            debugContext = {};
            
            stageSelect.innerHTML = debugStages.map((stage, index) => 
                `<option value="${index}">${stage.description}</option>`
            ).join('');
            
            displayCurrentStage();
        } catch (error) {
            alert('加载提示词失败: ' + error.message);
        }
    }
    
    function displayCurrentStage() {
        const stage = debugStages[currentStageIndex];
        promptContent.textContent = stage.prompt || '无提示词';
        instructionsContent.textContent = stage.instructions || '无指导步骤';
        userResponse.value = '';
        debugResult.style.display = 'none';
    }
});
