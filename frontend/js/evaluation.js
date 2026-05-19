document.addEventListener('DOMContentLoaded', async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const recordId = urlParams.get('record_id');
    const visitId = urlParams.get('visit_id');
    
    if (!recordId || !visitId) {
        alert('缺少record_id或visit_id参数');
        return;
    }
    
    document.getElementById('recordId').textContent = recordId;
    document.getElementById('visitId').textContent = visitId;
    
    const runBtn = document.getElementById('runEvaluation');
    const backBtn = document.getElementById('backToEMR');
    const loadingSection = document.getElementById('loadingSection');
    const evaluationSection = document.getElementById('evaluationSection');
    
    runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        loadingSection.style.display = 'block';
        
        try {
            const response = await fetch('/api/evaluation/evaluate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    record_id: parseInt(recordId)
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'success' && result.results) {
                loadingSection.style.display = 'none';
                evaluationSection.style.display = 'block';
                runBtn.style.display = 'none';
                await displayEvaluationResult(result.results);
            } else {
                throw new Error(result.detail || '评估失败');
            }
        } catch (error) {
            alert('评估失败: ' + error.message);
            runBtn.disabled = false;
            loadingSection.style.display = 'none';
        }
    });
    
    backBtn.addEventListener('click', () => {
        window.location.href = `/static/emr.html?visit_id=${visitId}`;
    });
    
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            document.querySelectorAll('.tab-content').forEach(content => {
                content.style.display = 'none';
            });
            
            const tabId = btn.dataset.tab + 'Tab';
            document.getElementById(tabId).style.display = 'block';
        });
    });
    
    await loadExistingEvaluation(recordId);
    
    const debugBtn = document.getElementById('debugEvaluation');
    const debugModal = document.getElementById('debugModal');
    const closeDebugModal = document.getElementById('closeDebugModal');
    const stageSelect = document.getElementById('stageSelect');
    const promptContent = document.getElementById('promptContent');
    const userResponse = document.getElementById('userResponse');
    const submitStage = document.getElementById('submitStage');
    const skipStage = document.getElementById('skipStage');
    const debugResult = document.getElementById('debugResult');
    const resultContent = document.getElementById('resultContent');
    const copyPromptBtn = document.getElementById('copyPrompt');
    
    let debugStages = [];
    let currentStageIndex = 0;
    let debugContext = {};
    
    debugBtn.addEventListener('click', async () => {
        debugModal.style.display = 'block';
        await loadDebugPrompts();
    });
    
    copyPromptBtn.addEventListener('click', async () => {
        const text = promptContent.textContent;
        if (!text || text === '无提示词') {
            alert('没有可复制的内容');
            return;
        }
        
        try {
            await navigator.clipboard.writeText(text);
            copyPromptBtn.textContent = '已复制';
            copyPromptBtn.classList.add('copied');
            setTimeout(() => {
                copyPromptBtn.textContent = '复制';
                copyPromptBtn.classList.remove('copied');
            }, 1500);
        } catch (err) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                copyPromptBtn.textContent = '已复制';
                copyPromptBtn.classList.add('copied');
                setTimeout(() => {
                    copyPromptBtn.textContent = '复制';
                    copyPromptBtn.classList.remove('copied');
                }, 1500);
            } catch (e) {
                alert('复制失败，请手动复制');
            }
            document.body.removeChild(textarea);
        }
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
        const stage = debugStages[currentStageIndex];
        const response = userResponse.value.trim();
        
        // 检查是否是自动执行阶段
        if (stage.auto_process) {
            // 自动执行阶段不需要用户输入
        } else if (!response) {
            alert('请输入大模型返回结果');
            return;
        }
        
        try {
            const contextToSend = { ...debugContext, record_id: parseInt(recordId) };
            
            const result = await fetch('/api/evaluation/debug/process-stage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
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
                
                if (result.completed) {
                    alert('所有阶段处理完成！评估结果已保存。');
                    debugModal.style.display = 'none';
                    location.reload();
                } else if (result.next_stage) {
                    const nextIndex = debugStages.findIndex(s => s.stage === result.next_stage);
                    if (nextIndex !== -1 && nextIndex > currentStageIndex) {
                        currentStageIndex = nextIndex;
                        stageSelect.value = currentStageIndex;
                        
                        if (result.next_prompt) {
                            debugStages[currentStageIndex].prompt = result.next_prompt;
                        }
                        
                        displayCurrentStage();
                        userResponse.value = '';
                    }
                }
            } else {
                alert('处理失败: ' + (result.detail || '未知错误'));
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
            const response = await fetch(`/api/evaluation/debug/prompts/${recordId}`);
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
        userResponse.value = '';
        debugResult.style.display = 'none';
    }
});

async function loadExistingEvaluation(recordId) {
    try {
        const response = await fetch(`/api/evaluation/list/${recordId}`);
        const result = await response.json();
        
        if (result.evaluations && result.evaluations.length > 0) {
            const latest = result.evaluations[0];
            document.getElementById('runEvaluation').style.display = 'none';
            document.getElementById('evaluationSection').style.display = 'block';
            await displayEvaluationResult(latest);
        }
    } catch (error) {
        console.log('No existing evaluation found');
    }
}

async function displayEvaluationResult(result) {
    const overallScore = result.overall_score || 0;
    document.getElementById('overallScore').textContent = (overallScore * 100).toFixed(1);
    
    const scoreCircle = document.getElementById('overallScoreCircle');
    if (overallScore >= 0.8) {
        scoreCircle.className = 'score-circle score-good';
    } else if (overallScore >= 0.6) {
        scoreCircle.className = 'score-circle score-medium';
    } else {
        scoreCircle.className = 'score-circle score-poor';
    }
    
    let consistency, completeness, quality, safety;
    let supportRate, recallRate, qualityScore, hasHighRisk, highRiskCount;
    
    if (result.consistency !== undefined) {
        consistency = result.consistency || {};
        completeness = result.completeness || {};
        quality = result.quality || {};
        safety = result.safety || {};
        
        supportRate = consistency.summary?.support_rate || 0;
        recallRate = completeness.summary?.recall_rate || 0;
        qualityScore = quality.total_score || 0;
        hasHighRisk = safety.has_high_risk || false;
        highRiskCount = safety.high_risk_count || 0;
    } else {
        consistency = result.consistency_result || {};
        completeness = result.completeness_result || {};
        quality = result.quality_result || {};
        safety = result.safety_result || {};
        
        supportRate = result.support_rate || consistency.summary?.support_rate || 0;
        recallRate = result.recall_rate || completeness.summary?.recall_rate || 0;
        qualityScore = result.quality_total_score || quality.total_score || 0;
        hasHighRisk = result.has_high_risk !== undefined ? result.has_high_risk : (safety.has_high_risk || false);
        highRiskCount = result.high_risk_count !== undefined ? result.high_risk_count : (safety.high_risk_count || 0);
    }
    
    document.getElementById('consistencyScore').textContent = (supportRate * 100).toFixed(1) + '%';
    document.getElementById('consistencyBar').style.width = (supportRate * 100) + '%';
    
    document.getElementById('completenessScore').textContent = (recallRate * 100).toFixed(1) + '%';
    document.getElementById('completenessBar').style.width = (recallRate * 100) + '%';
    
    const qualityPercent = (qualityScore / 10) * 100;
    document.getElementById('qualityScore').textContent = qualityScore.toFixed(1) + '/10';
    document.getElementById('qualityBar').style.width = qualityPercent + '%';
    
    const riskStatus = document.getElementById('riskStatus');
    if (hasHighRisk) {
        riskStatus.textContent = `发现 ${highRiskCount} 个高风险问题`;
        riskStatus.className = 'risk-status risk-high';
    } else {
        riskStatus.textContent = '未发现高风险问题';
        riskStatus.className = 'risk-status risk-low';
    }
    
    displayConsistencyResult(consistency);
    displayCompletenessResult(completeness);
    displayQualityResult(quality);
    displaySafetyResult(safety);
}

function displayConsistencyResult(consistencyResult) {
    if (!consistencyResult) return;
    
    const facts = consistencyResult.facts || [];
    const totalFacts = facts.length;
    const supportedFacts = facts.filter(f => f.is_supported).length;
    const unsupportedFacts = totalFacts - supportedFacts;
    
    document.getElementById('totalFacts').textContent = totalFacts;
    document.getElementById('supportedFacts').textContent = supportedFacts;
    document.getElementById('unsupportedFacts').textContent = unsupportedFacts;
    
    const factsList = document.getElementById('factsList');
    factsList.innerHTML = '';
    
    facts.forEach((fact, index) => {
        const factItem = document.createElement('div');
        factItem.className = 'fact-item ' + (fact.is_supported ? 'supported' : 'unsupported');
        
        factItem.innerHTML = `
            <div class="fact-header">
                <span class="fact-status">${fact.is_supported ? '✓' : '✗'}</span>
                <span class="fact-text">${fact.fact || fact.fact_text || fact.claim || '未知事实'}</span>
            </div>
            <div class="fact-evidence">
                <strong>证据：</strong>${fact.evidence_text || fact.evidence || fact.source_text || '无'}
            </div>
            <div class="fact-reasoning">
                <strong>推理：</strong>${fact.reasoning || ''}
            </div>
        `;
        
        factsList.appendChild(factItem);
    });
    
    const conflicts = consistencyResult.internal_conflicts || [];
    const conflictsList = document.getElementById('conflictsList');
    conflictsList.innerHTML = '';
    
    if (conflicts.length === 0) {
        conflictsList.innerHTML = '<p class="no-issues">未发现内部矛盾</p>';
    } else {
        conflicts.forEach(conflict => {
            const conflictItem = document.createElement('div');
            conflictItem.className = 'conflict-item';
            conflictItem.innerHTML = `
                <div class="conflict-description">${conflict.description || conflict.conflict_type}</div>
                <div class="conflict-details">
                    <p><strong>矛盾点1：</strong>${conflict.content_1 || conflict.point1 || conflict.location_1}</p>
                    <p><strong>矛盾点2：</strong>${conflict.content_2 || conflict.point2 || conflict.location_2}</p>
                </div>
            `;
            conflictsList.appendChild(conflictItem);
        });
    }
}

function displayCompletenessResult(completenessResult) {
    if (!completenessResult) return;
    
    const keyFacts = completenessResult.coverage || completenessResult.key_facts || [];
    const totalKeyFacts = keyFacts.length;
    const fullCoverage = keyFacts.filter(f => f.coverage_status === 'full' || f.coverage === 'full').length;
    const partialCoverage = keyFacts.filter(f => f.coverage_status === 'partial' || f.coverage === 'partial').length;
    const noCoverage = keyFacts.filter(f => f.coverage_status === 'none' || f.coverage === 'none').length;
    
    document.getElementById('totalKeyFacts').textContent = totalKeyFacts;
    document.getElementById('fullCoverage').textContent = fullCoverage;
    document.getElementById('partialCoverage').textContent = partialCoverage;
    document.getElementById('noCoverage').textContent = noCoverage;
    
    const coverageList = document.getElementById('coverageList');
    coverageList.innerHTML = '';
    
    keyFacts.forEach(fact => {
        const coverage = fact.coverage_status || fact.coverage;
        const item = document.createElement('div');
        item.className = 'coverage-item ' + coverage;
        
        item.innerHTML = `
            <div class="coverage-header">
                <span class="coverage-status">${
                    coverage === 'full' ? '✓ 完全覆盖' :
                    coverage === 'partial' ? '◐ 部分覆盖' : '✗ 未覆盖'
                }</span>
                <span class="coverage-fact">${fact.fact || fact.fact_text}</span>
            </div>
            <div class="coverage-evidence">
                <strong>病历内容：</strong>${fact.emr_text || fact.emr_content || '无'}
            </div>
        `;
        
        coverageList.appendChild(item);
    });
}

function displayQualityResult(qualityResult) {
    console.log('Quality Result:', qualityResult);
    
    if (!qualityResult || Object.keys(qualityResult).length === 0) {
        document.getElementById('qualityScores').innerHTML = '<p class="no-issues">暂无质量评估数据</p>';
        document.getElementById('overallAssessment').textContent = '--';
        return;
    }
    
    const scores = qualityResult.scores || {};
    console.log('Scores:', scores);
    
    const qualityScores = document.getElementById('qualityScores');
    qualityScores.innerHTML = '';
    
    const dimensions = [
        { key: 'structure_completeness', name: '结构完整性', altKey: 'structure' },
        { key: 'organization_clarity', name: '组织清晰度', altKey: 'organization' },
        { key: 'conciseness', name: '表达简洁性', altKey: 'conciseness' },
        { key: 'readability', name: '可理解性', altKey: 'readability' },
        { key: 'terminology_appropriateness', name: '术语规范性', altKey: 'terminology' }
    ];
    
    dimensions.forEach(dim => {
        const scoreObj = scores[dim.key] || scores[dim.altKey] || {};
        const score = typeof scoreObj === 'object' ? (scoreObj.score || 0) : (scoreObj || 0);
        const item = document.createElement('div');
        item.className = 'quality-item';
        item.innerHTML = `
            <span class="quality-name">${dim.name}</span>
            <div class="quality-bar">
                <div class="quality-bar-fill" style="width: ${(score / 2) * 100}%"></div>
            </div>
            <span class="quality-value">${score}/2</span>
        `;
        qualityScores.appendChild(item);
    });
    
    document.getElementById('overallAssessment').textContent = qualityResult.overall_assessment || '--';
}

function displaySafetyResult(safetyResult) {
    if (!safetyResult) return;
    
    const hasHighRisk = safetyResult.has_high_risk;
    const safetyIcon = document.getElementById('safetyIcon');
    const safetyText = document.getElementById('safetyText');
    const safetyStatus = document.getElementById('safetyStatus');
    
    if (hasHighRisk) {
        safetyIcon.textContent = '⚠';
        safetyText.textContent = `发现 ${safetyResult.high_risk_count || 0} 个高风险问题`;
        safetyStatus.className = 'safety-status has-risk';
    } else {
        safetyIcon.textContent = '✓';
        safetyText.textContent = '未发现高风险错误';
        safetyStatus.className = 'safety-status no-risk';
    }
    
    const risks = safetyResult.risks || [];
    const risksList = document.getElementById('risksList');
    risksList.innerHTML = '';
    
    if (risks.length === 0) {
        risksList.innerHTML = '<p class="no-issues">未发现安全风险</p>';
    } else {
        risks.forEach(risk => {
            const item = document.createElement('div');
            item.className = 'risk-item ' + (risk.severity === 'high' ? 'high-risk' : 'medium-risk');
            
            item.innerHTML = `
                <div class="risk-header">
                    <span class="risk-type">${risk.risk_type || risk.type}</span>
                    <span class="risk-severity">${risk.severity === 'high' ? '高风险' : '中风险'}</span>
                </div>
                <div class="risk-description">${risk.description}</div>
                <div class="risk-evidence">
                    <strong>原文：</strong>${risk.emr_content || risk.original_text || ''}
                </div>
                <div class="risk-suggestion">
                    <strong>建议：</strong>${risk.correct_content || risk.suggestion || ''}
                </div>
            `;
            
            risksList.appendChild(item);
        });
    }
}
