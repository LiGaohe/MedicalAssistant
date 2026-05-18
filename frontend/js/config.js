document.addEventListener('DOMContentLoaded', async function() {
    const form = document.getElementById('llmConfigForm');
    const backBtn = document.getElementById('backToHome');
    const thinkingCheckbox = document.getElementById('thinkingEnabled');
    const thinkingEffortGroup = document.getElementById('thinkingEffortGroup');
    const editingConfigId = document.getElementById('editingConfigId');
    const submitBtn = document.getElementById('submitBtn');
    const cancelEditBtn = document.getElementById('cancelEditBtn');
    
    thinkingCheckbox.addEventListener('change', function() {
        thinkingEffortGroup.style.display = this.checked ? 'block' : 'none';
    });
    
    cancelEditBtn.addEventListener('click', function() {
        exitEditMode();
    });
    
    await loadConfigs();
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const formData = new FormData(form);
        const config = {
            config_name: formData.get('config_name'),
            provider: formData.get('provider'),
            model_name: formData.get('model_name'),
            api_key: formData.get('api_key') || null,
            api_endpoint: formData.get('api_endpoint') || null,
            max_tokens: parseInt(formData.get('max_tokens')) || 2048,
            temperature: formData.get('temperature') || '0.7',
            is_active: document.getElementById('isActive').checked,
            json_mode: document.getElementById('jsonMode').checked,
            thinking_enabled: document.getElementById('thinkingEnabled').checked,
            thinking_effort: document.getElementById('thinkingEffort').value
        };
        
        if (editingConfigId.value && !config.api_key) {
            delete config.api_key;
        }
        
        try {
            const editId = editingConfigId.value;
            let response;
            
            if (editId) {
                response = await fetch(`/api/llm/config/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
            } else {
                response = await fetch('/api/llm/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
            }
            
            const result = await response.json();
            
            if (result.success) {
                alert(editId ? '配置更新成功！' : '配置保存成功！');
                exitEditMode();
                await loadConfigs();
            } else {
                throw new Error(result.detail || result.message || '操作失败');
            }
        } catch (error) {
            alert('操作失败: ' + error.message);
        }
    });
    
    backBtn.addEventListener('click', () => {
        window.location.href = '/';
    });
    
    function enterEditMode(config) {
        editingConfigId.value = config.id;
        document.getElementById('configName').value = config.config_name;
        document.getElementById('provider').value = config.provider;
        document.getElementById('modelName').value = config.model_name;
        document.getElementById('apiKey').value = '';
        document.getElementById('apiEndpoint').value = config.api_endpoint || '';
        document.getElementById('maxTokens').value = config.max_tokens;
        document.getElementById('temperature').value = config.temperature;
        document.getElementById('isActive').checked = config.is_active;
        document.getElementById('jsonMode').checked = config.json_mode;
        document.getElementById('thinkingEnabled').checked = config.thinking_enabled;
        document.getElementById('thinkingEffort').value = config.thinking_effort || 'high';
        
        thinkingEffortGroup.style.display = config.thinking_enabled ? 'block' : 'none';
        
        document.getElementById('apiKey').required = false;
        
        submitBtn.textContent = '更新配置';
        cancelEditBtn.style.display = 'inline-block';
        
        form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    function exitEditMode() {
        editingConfigId.value = '';
        form.reset();
        document.getElementById('isActive').checked = true;
        document.getElementById('jsonMode').checked = false;
        document.getElementById('thinkingEnabled').checked = false;
        document.getElementById('thinkingEffort').value = 'high';
        thinkingEffortGroup.style.display = 'none';
        
        document.getElementById('apiKey').required = true;
        
        submitBtn.textContent = '保存配置';
        cancelEditBtn.style.display = 'none';
    }
    
    async function loadConfigs() {
        try {
            const response = await fetch('/api/llm/configs');
            const result = await response.json();
            
            const configsList = document.getElementById('configsList');
            
            if (!result.configs || result.configs.length === 0) {
                configsList.innerHTML = '<p class="empty">暂无配置</p>';
                return;
            }
            
            configsList.innerHTML = result.configs.map(config => `
                <div class="config-item ${config.is_active ? 'active' : ''}">
                    <div class="config-header">
                        <h3>${config.config_name}</h3>
                        <span class="config-status ${config.is_active ? 'active' : 'inactive'}">
                            ${config.is_active ? '已启用' : '未启用'}
                        </span>
                    </div>
                    <div class="config-details">
                        <p><strong>服务商:</strong> ${config.provider}</p>
                        <p><strong>模型:</strong> ${config.model_name}</p>
                        <p><strong>Max Tokens:</strong> ${config.max_tokens}</p>
                        <p><strong>Temperature:</strong> ${config.temperature}</p>
                        <p><strong>JSON模式:</strong> ${config.json_mode ? '已启用' : '未启用'}</p>
                        <p><strong>思考模式:</strong> ${config.thinking_enabled ? `已启用 (${config.thinking_effort})` : '未启用'}</p>
                    </div>
                    <div class="config-actions">
                        <button class="btn-small btn-edit" onclick="editConfig(${config.id})">
                            编辑
                        </button>
                        <button class="btn-small" onclick="toggleConfig(${config.id}, ${!config.is_active})">
                            ${config.is_active ? '禁用' : '启用'}
                        </button>
                        <button class="btn-small btn-danger" onclick="deleteConfig(${config.id})">
                            删除
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('加载配置失败:', error);
        }
    }
    
    window.editConfig = async function(configId) {
        try {
            const response = await fetch('/api/llm/configs');
            const result = await response.json();
            const config = result.configs.find(c => c.id === configId);
            
            if (!config) {
                alert('配置不存在');
                return;
            }
            
            enterEditMode(config);
        } catch (error) {
            alert('加载配置失败: ' + error.message);
        }
    };
    
    window.toggleConfig = async function(configId, isActive) {
        try {
            const response = await fetch(`/api/llm/config/${configId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ is_active: isActive })
            });
            
            const result = await response.json();
            
            if (result.success) {
                await loadConfigs();
            } else {
                throw new Error(result.message || '操作失败');
            }
        } catch (error) {
            alert('操作失败: ' + error.message);
        }
    };
    
    window.deleteConfig = async function(configId) {
        if (!confirm('确定要删除此配置吗？')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/llm/config/${configId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (result.success) {
                if (editingConfigId.value == configId) {
                    exitEditMode();
                }
                await loadConfigs();
            } else {
                throw new Error(result.message || '删除失败');
            }
        } catch (error) {
            alert('删除失败: ' + error.message);
        }
    };
});
