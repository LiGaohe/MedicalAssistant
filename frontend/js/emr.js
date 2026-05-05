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
    const evaluateBtn = document.getElementById('evaluateEMR');
    const backBtn = document.getElementById('backToResult');
    const editBtn = document.getElementById('editEMR');
    const saveBtn = document.getElementById('saveEMR');
    const cancelEditBtn = document.getElementById('cancelEdit');
    const printBtn = document.getElementById('printEMR');
    const toggleEvidenceBtn = document.getElementById('toggleEvidence');
    const loadingSection = document.getElementById('loadingSection');
    const emrSection = document.getElementById('emrSection');
    
    let currentEMRRecord = null;
    let currentRecordId = null;
    let isEditing = false;
    let evidenceVisible = false;
    let evidenceData = [];
    
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
                evaluateBtn.style.display = 'block';
                currentRecordId = result.emr_record.record_id;
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
    
    evaluateBtn.addEventListener('click', () => {
        if (currentRecordId) {
            window.location.href = `/static/evaluation.html?record_id=${currentRecordId}&visit_id=${visitId}`;
        } else {
            alert('请先生成病历');
        }
    });
    
    document.getElementById('versionSelect').addEventListener('change', async (e) => {
        const version = e.target.value;
        if (version) {
            await loadEMRByVersion(visitId, version);
        }
    });
    
    editBtn.addEventListener('click', () => {
        if (!currentEMRRecord) {
            alert('请先加载病历');
            return;
        }
        enterEditMode();
    });
    
    saveBtn.addEventListener('click', async () => {
        await saveEMREdits();
    });
    
    cancelEditBtn.addEventListener('click', () => {
        exitEditMode();
        displayEMR(currentEMRRecord);
    });
    
    printBtn.addEventListener('click', () => {
        printEMR();
    });
    
    toggleEvidenceBtn.addEventListener('click', async () => {
        if (evidenceVisible) {
            hideEvidence();
        } else {
            await showEvidence();
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
                evaluateBtn.style.display = 'block';
                generateBtn.textContent = '重新生成病历';
                if (result.latest_record_id) {
                    currentRecordId = result.latest_record_id;
                }
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
            currentEMRRecord = result;
            await displayEMR(result);
            await loadEvidenceData(visitId);
        } catch (error) {
            console.error('加载病历失败:', error);
        }
    }
    
    async function loadEvidenceData(visitId) {
        try {
            const response = await fetch(`/api/emr/evidence/${visitId}`);
            const result = await response.json();
            evidenceData = result.evidence || [];
        } catch (error) {
            console.error('加载证据数据失败:', error);
            evidenceData = [];
        }
    }
    
    async function displayEMR(emrRecord) {
        const emrJson = emrRecord.emr_json;
        
        displaySection('subjectiveContent', emrJson.subjective, 'subjective');
        displaySection('objectiveContent', emrJson.objective, 'objective');
        displaySection('assessmentContent', emrJson.assessment, 'assessment');
        displaySection('planContent', emrJson.plan, 'plan');
    }
    
    function displaySection(elementId, sectionData, sectionName) {
        const element = document.getElementById(elementId);
        
        if (!sectionData) {
            element.innerHTML = '<p class="empty">暂无数据</p>';
            return;
        }
        
        let html = '';
        
        if (sectionData.text !== undefined && sectionData.text !== null) {
            html += `<div class="section-text" data-field="${sectionName}.text">${sectionData.text || '暂无内容'}</div>`;
        }
        
        const fields = Object.keys(sectionData).filter(k => k !== 'text' && k !== 'evidence_traces');
        if (fields.length > 0) {
            html += '<div class="section-fields">';
            fields.forEach(field => {
                const fieldData = sectionData[field];
                if (fieldData && fieldData.value !== undefined && fieldData.value !== null) {
                    const evidenceHtml = buildEvidenceHtml(sectionName, field, fieldData);
                    html += `
                        <div class="field-item" data-field="${sectionName}.${field}">
                            <div class="field-name">${getFieldName(field)}</div>
                            <div class="field-value">${fieldData.value || '暂无'}</div>
                            ${evidenceHtml}
                        </div>
                    `;
                }
            });
            html += '</div>';
        }
        
        element.innerHTML = html || '<p class="empty">暂无数据</p>';
        
        setTimeout(() => addExpandListeners(), 0);
    }
    
    function buildEvidenceHtml(sectionName, field, fieldData) {
        const traces = fieldData.evidence_traces || [];
        if (traces.length === 0) {
            return '';
        }
        
        const fieldValue = fieldData.value || '';
        
        let html = '<div class="evidence-traces"><strong>证据来源：</strong>';
        if (fieldValue) {
            html += `<div class="evidence-final-value"><strong>最终病历：</strong>${fieldValue}</div>`;
        }
        html += '<ul>';
        traces.forEach((trace, idx) => {
            const speaker = trace.speaker || '未知';
            const originalSpeaker = trace.original_speaker || speaker;
            const speakerCorrected = trace.speaker_corrected || false;
            const content = trace.content || '';
            const turnText = trace.turn_text || '';
            const turnIndex = trace.turn_index !== undefined ? trace.turn_index : '-';
            
            let speakerHtml = `<span class="evidence-speaker">${speaker}</span>`;
            if (speakerCorrected) {
                speakerHtml = `<span class="evidence-speaker corrected">${speaker}</span>
                    <span class="evidence-speaker-correction" title="说话人已纠正">
                        (原: ${originalSpeaker} → 纠正后: ${speaker})
                    </span>`;
            }
            
            html += `
                <li class="evidence-item" data-turn-index="${turnIndex}">
                    <div class="evidence-header">
                        ${speakerHtml}
                        <span class="evidence-turn">轮次 ${turnIndex}</span>
                    </div>
                    <div class="evidence-detail">
                        <div class="evidence-label">LLM标注片段：</div>
                        <div class="evidence-content">${createExpandableText(content, 150)}</div>
                        ${turnText ? `
                        <div class="evidence-label">完整转写文本：</div>
                        <div class="evidence-turn-text">${createExpandableText(turnText, 150)}</div>
                        ` : ''}
                    </div>
                </li>
            `;
        });
        html += '</ul></div>';
        return html;
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
    
    function enterEditMode() {
        isEditing = true;
        editBtn.style.display = 'none';
        saveBtn.style.display = 'inline-block';
        cancelEditBtn.style.display = 'inline-block';
        
        const sections = ['subjectiveContent', 'objectiveContent', 'assessmentContent', 'planContent'];
        sections.forEach(sectionId => {
            const section = document.getElementById(sectionId);
            makeSectionEditable(section);
        });
    }
    
    function exitEditMode() {
        isEditing = false;
        editBtn.style.display = 'inline-block';
        saveBtn.style.display = 'none';
        cancelEditBtn.style.display = 'none';
    }
    
    function makeSectionEditable(section) {
        const textDivs = section.querySelectorAll('.section-text');
        textDivs.forEach(div => {
            const text = div.textContent;
            const field = div.dataset.field;
            div.innerHTML = `<textarea class="edit-textarea" data-field="${field}">${text}</textarea>`;
        });
        
        const valueDivs = section.querySelectorAll('.field-value');
        valueDivs.forEach(div => {
            const text = div.textContent;
            div.innerHTML = `<textarea class="edit-textarea field-edit">${text}</textarea>`;
        });
    }
    
    async function saveEMREdits() {
        if (!currentEMRRecord) {
            alert('没有可保存的病历');
            return;
        }
        
        const updatedEMR = JSON.parse(JSON.stringify(currentEMRRecord.emr_json));
        
        const textareas = document.querySelectorAll('.edit-textarea');
        textareas.forEach(textarea => {
            const field = textarea.dataset.field;
            const value = textarea.value;
            
            if (field) {
                const parts = field.split('.');
                if (parts.length === 2) {
                    const [section, fieldName] = parts;
                    if (fieldName === 'text') {
                        if (!updatedEMR[section]) updatedEMR[section] = {};
                        updatedEMR[section].text = value;
                    }
                }
            }
        });
        
        const fieldEdits = document.querySelectorAll('.field-edit');
        fieldEdits.forEach(textarea => {
            const fieldItem = textarea.closest('.field-item');
            if (fieldItem) {
                const field = fieldItem.dataset.field;
                if (field) {
                    const parts = field.split('.');
                    if (parts.length === 2) {
                        const [section, fieldName] = parts;
                        if (!updatedEMR[section]) updatedEMR[section] = {};
                        if (!updatedEMR[section][fieldName]) updatedEMR[section][fieldName] = {};
                        updatedEMR[section][fieldName].value = textarea.value;
                    }
                }
            }
        });
        
        try {
            const response = await fetch(`/api/emr/record/${visitId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    emr_json: updatedEMR,
                    record_type: 'user_edited'
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                alert(`病历保存成功！新版本: ${result.version}`);
                exitEditMode();
                await loadEMRVersions(visitId);
            } else {
                throw new Error(result.message || '保存失败');
            }
        } catch (error) {
            alert('保存失败: ' + error.message);
        }
    }
    
    function printEMR() {
        const printWindow = window.open('', '_blank');
        const emrContent = document.getElementById('emrContent').cloneNode(true);
        
        const editElements = emrContent.querySelectorAll('.edit-textarea');
        editElements.forEach(el => {
            const span = document.createElement('span');
            span.textContent = el.value;
            el.parentNode.replaceChild(span, el);
        });
        
        const evidenceElements = emrContent.querySelectorAll('.evidence-traces');
        evidenceElements.forEach(el => el.remove());
        
        const printStyles = `
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: SimSun, serif; padding: 40px; line-height: 1.8; }
                h1 { text-align: center; font-size: 24px; margin-bottom: 30px; }
                h3 { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 5px; margin: 20px 0 10px 0; }
                .emr-part { margin-bottom: 30px; }
                .section-text { margin-bottom: 15px; text-indent: 2em; }
                .field-item { margin-bottom: 10px; }
                .field-name { font-weight: bold; display: inline; }
                .field-value { display: inline; }
                .field-meta { display: none; }
                .section-fields { margin-top: 10px; }
                @media print {
                    body { padding: 0; }
                }
            </style>
        `;
        
        printWindow.document.write(`
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>病历打印</title>
                ${printStyles}
            </head>
            <body>
                <h1>门诊病历</h1>
                <p style="text-align: center; margin-bottom: 20px;">
                    就诊记录: ${visitId} | 打印时间: ${new Date().toLocaleString('zh-CN')}
                </p>
                ${emrContent.innerHTML}
            </body>
            </html>
        `);
        
        printWindow.document.close();
        printWindow.focus();
        setTimeout(() => {
            printWindow.print();
        }, 500);
    }
    
    async function showEvidence() {
        const panel = document.getElementById('evidencePanel');
        const list = document.getElementById('evidenceList');
        
        if (evidenceData.length === 0) {
            await loadEvidenceData(visitId);
        }
        
        if (evidenceData.length === 0) {
            list.innerHTML = '<p class="empty">暂无证据溯源数据</p>';
        } else {
            let html = '<table class="evidence-table"><thead><tr>';
            html += '<th>字段类型</th><th>最终病历</th><th>标注片段</th><th>原始转写</th><th>说话人</th><th>轮次</th>';
            html += '</tr></thead><tbody>';
            
            evidenceData.forEach((ev, idx) => {
                const turnText = ev.turn_text || '-';
                const fieldValue = ev.field_value || '-';
                const content = ev.content || '-';
                
                html += `<tr>
                    <td>${getFieldName(ev.field_type)}</td>
                    <td class="evidence-value-cell" title="${escapeHtml(fieldValue)}">${createExpandableText(fieldValue, 100)}</td>
                    <td class="evidence-content-cell" title="${escapeHtml(content)}">${createExpandableText(content, 100)}</td>
                    <td class="evidence-turn-cell" title="${escapeHtml(turnText)}">${createExpandableText(turnText, 100)}</td>
                    <td>${ev.speaker || '-'}</td>
                    <td>${ev.turn_index !== null ? ev.turn_index : '-'}</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
            list.innerHTML = html;
            
            addExpandListeners();
        }
        
        panel.style.display = 'block';
        toggleEvidenceBtn.textContent = '隐藏证据溯源';
        evidenceVisible = true;
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function createExpandableText(text, maxLength) {
        if (!text || text.length <= maxLength) {
            return `<span class="full-text">${escapeHtml(text)}</span>`;
        }
        const truncated = text.substring(0, maxLength);
        return `<span class="truncated-text">${escapeHtml(truncated)}...</span>
                <span class="full-text" style="display:none;">${escapeHtml(text)}</span>
                <button class="expand-btn" data-expanded="false">展开</button>`;
    }
    
    function addExpandListeners() {
        document.querySelectorAll('.expand-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const parent = this.parentElement;
                const truncated = parent.querySelector('.truncated-text');
                const full = parent.querySelector('.full-text');
                
                if (this.dataset.expanded === 'false') {
                    if (truncated) truncated.style.display = 'none';
                    if (full) full.style.display = 'inline';
                    this.textContent = '收起';
                    this.dataset.expanded = 'true';
                } else {
                    if (truncated) truncated.style.display = 'inline';
                    if (full) full.style.display = 'none';
                    this.textContent = '展开';
                    this.dataset.expanded = 'false';
                }
            });
        });
    }
    
    function hideEvidence() {
        document.getElementById('evidencePanel').style.display = 'none';
        toggleEvidenceBtn.textContent = '显示证据溯源';
        evidenceVisible = false;
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
