document.addEventListener('DOMContentLoaded', async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const visitId = urlParams.get('visit_id');
    
    if (!visitId) {
        alert('缺少visit_id参数');
        return;
    }
    
    document.getElementById('visitId').textContent = visitId;
    
    const startBtn = document.getElementById('startTranscribe');
    const generateEMRBtn = document.getElementById('generateEMR');
    const configLLMBtn = document.getElementById('configLLM');
    const refreshBtn = document.getElementById('refreshStatus');
    const turnsSection = document.getElementById('turnsSection');
    const loadingSection = document.getElementById('loadingSection');
    
    await loadVisitInfo(visitId);
    
    startBtn.addEventListener('click', async () => {
        startBtn.disabled = true;
        loadingSection.style.display = 'block';
        
        try {
            const response = await fetch(`/api/asr/transcribe/${visitId}`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.success) {
                await pollTaskStatus(result.task_id, visitId);
            } else {
                throw new Error(result.message || '转写失败');
            }
        } catch (error) {
            alert('转写失败: ' + error.message);
            startBtn.disabled = false;
            loadingSection.style.display = 'none';
        }
    });
    
    generateEMRBtn.addEventListener('click', () => {
        window.location.href = `/static/emr.html?visit_id=${visitId}`;
    });
    
    configLLMBtn.addEventListener('click', () => {
        window.location.href = '/static/config.html';
    });
    
    refreshBtn.addEventListener('click', async () => {
        await loadTranscript(visitId);
    });
    
    async function loadVisitInfo(visitId) {
        try {
            const response = await fetch(`/api/asr/transcript/${visitId}`);
            const result = await response.json();
            
            document.getElementById('status').textContent = getStatusText(result.status);
            document.getElementById('audioDuration').textContent = formatDuration(result.audio_duration);
            document.getElementById('audioLanguage').textContent = getLanguageText(result.language);
            
            if (result.status === 'completed') {
                startBtn.style.display = 'none';
                generateEMRBtn.style.display = 'block';
                await loadTranscript(visitId);
            } else if (result.status === 'processing') {
                startBtn.style.display = 'none';
                loadingSection.style.display = 'block';
            }
        } catch (error) {
            console.error('加载就诊信息失败:', error);
        }
    }
    
    async function pollTaskStatus(taskId, visitId) {
        const maxAttempts = 60;
        let attempts = 0;
        
        const poll = async () => {
            try {
                const response = await fetch(`/api/task/${taskId}`);
                const result = await response.json();
                
                if (result.status === 'completed') {
                    loadingSection.style.display = 'none';
                    turnsSection.style.display = 'block';
                    generateEMRBtn.style.display = 'block';
                    await loadTranscript(visitId);
                } else if (result.status === 'failed') {
                    alert('转写失败: ' + result.error_message);
                    startBtn.disabled = false;
                    loadingSection.style.display = 'none';
                } else if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(poll, 2000);
                } else {
                    alert('转写超时，请稍后刷新查看');
                    refreshBtn.style.display = 'block';
                    loadingSection.style.display = 'none';
                }
            } catch (error) {
                console.error('轮询任务状态失败:', error);
                if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(poll, 2000);
                }
            }
        };
        
        poll();
    }
    
    async function loadTranscript(visitId) {
        try {
            const response = await fetch(`/api/asr/transcript/${visitId}`);
            const result = await response.json();
            
            if (result.turns && result.turns.length > 0) {
                turnsSection.style.display = 'block';
                const turnsList = document.getElementById('turnsList');
                turnsList.innerHTML = '';
                
                result.turns.forEach(turn => {
                    const turnDiv = document.createElement('div');
                    turnDiv.className = 'turn-item';
                    
                    const speakerId = turn.speaker || 'unknown';
                    const speakerClass = speakerId === 'spk0' ? 'speaker-0' : 
                                        speakerId === 'spk1' ? 'speaker-1' : 'speaker-other';
                    
                    turnDiv.innerHTML = `
                        <div class="turn-header ${speakerClass}">
                            <span class="time">[${formatTime(turn.start_ms)} - ${formatTime(turn.end_ms)}]</span>
                            <span class="speaker">${speakerId}</span>
                        </div>
                        <div class="turn-text">${turn.text}</div>
                    `;
                    
                    turnsList.appendChild(turnDiv);
                });
            }
        } catch (error) {
            console.error('加载转写结果失败:', error);
        }
    }
    
    function getStatusText(status) {
        const statusMap = {
            'pending': '等待中',
            'processing': '处理中',
            'completed': '已完成',
            'failed': '失败'
        };
        return statusMap[status] || status;
    }
    
    function getLanguageText(language) {
        const languageMap = {
            'zh': '中文',
            'en': 'English'
        };
        return languageMap[language] || language;
    }
    
    function formatDuration(seconds) {
        if (!seconds) return '未知';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}分${secs}秒`;
    }
    
    function formatTime(ms) {
        const seconds = Math.floor(ms / 1000);
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
});
