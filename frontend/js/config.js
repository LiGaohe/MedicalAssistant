document.addEventListener('DOMContentLoaded', async function() {
    const form = document.getElementById('llmConfigForm');
    const backBtn = document.getElementById('backToHome');
    
    await loadConfigs();
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const formData = new FormData(form);
        const config = {
            config_name: formData.get('config_name'),
            provider: formData.get('provider'),
            model_name: formData.get('model_name'),
            api_key: formData.get('api_key'),
            api_endpoint: formData.get('api_endpoint') || null,
            max_tokens: parseInt(formData.get('max_tokens')) || 2048,
            temperature: formData.get('temperature') || '0.7',
            is_active: document.getElementById('isActive').checked
        };
        
        try {
            const response = await fetch('/api/llm/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });
            
            const result = await response.json();
            
            if (result.success) {
                alert('配置保存成功！');
                form.reset();
                await loadConfigs();
            } else {
                throw new Error(result.message || '配置保存失败');
            }
        } catch (error) {
            alert('配置保存失败: ' + error.message);
        }
    });
    
    backBtn.addEventListener('click', () => {
        window.location.href = '/';
    });
    
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
                    </div>
                    <div class="config-actions">
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
                await loadConfigs();
            } else {
                throw new Error(result.message || '删除失败');
            }
        } catch (error) {
            alert('删除失败: ' + error.message);
        }
    };
});
