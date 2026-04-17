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
                viewBtn.style.display = 'block';
                await displayEMR(result.emr_record);
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
        
        if (sectionData.text) {
            html += `<div class="section-text">${sectionData.text}</div>`;
        }
        
        const fields = Object.keys(sectionData).filter(k => k !== 'text');
        if (fields.length > 0) {
            html += '<div class="section-fields">';
            fields.forEach(field => {
                const fieldData = sectionData[field];
                if (fieldData && fieldData.value) {
                    html += `
                        <div class="field-item">
                            <div class="field-name">${getFieldName(field)}</div>
                            <div class="field-value">${fieldData.value}</div>
                            <div class="field-meta">
                                置信度: ${(fieldData.confidence * 100).toFixed(1)}%
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
});
