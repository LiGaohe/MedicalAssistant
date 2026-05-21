window.ConfigSidebarModule = (function() {
    var llmForm = null;

    function initConfig() {
        llmForm = document.getElementById('llmConfigForm');
        var thinkingCheckbox = document.getElementById('thinkingEnabled');
        var thinkingEffortGroup = document.getElementById('thinkingEffortGroup');
        var editingConfigId = document.getElementById('editingConfigId');
        var submitBtn = document.getElementById('configSubmitBtn');
        var cancelEditBtn = document.getElementById('configCancelEditBtn');

        if (thinkingCheckbox) {
            thinkingCheckbox.addEventListener('change', function() {
                thinkingEffortGroup.style.display = this.checked ? 'flex' : 'none';
            });
        }

        if (cancelEditBtn) {
            cancelEditBtn.addEventListener('click', function() { exitEditMode(); });
        }

        if (llmForm) {
                llmForm.addEventListener('submit', async function(e) {
                    e.preventDefault();

                    var formData = new FormData(llmForm);
                var config = {
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
                    var editId = editingConfigId.value;
                    var response;

                    if (editId) {
                        response = await fetch('/api/llm/config/' + editId, {
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

                    var result = await response.json();

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
        }

        var configTabs = document.querySelectorAll('.config-tab');
        configTabs.forEach(function(tab) {
            tab.addEventListener('click', function() {
                configTabs.forEach(function(t) { t.classList.remove('active'); });
                this.classList.add('active');

                var tabContents = document.querySelectorAll('.config-tab-content');
                tabContents.forEach(function(c) { c.classList.remove('active'); });

                var target = document.getElementById(
                    'configTab' + this.dataset.configTab.charAt(0).toUpperCase() + this.dataset.configTab.slice(1)
                );
                if (target) target.classList.add('active');
            });
        });

        loadConfigs();
    }

    function enterEditMode(config) {
        document.getElementById('editingConfigId').value = config.id;
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

        document.getElementById('thinkingEffortGroup').style.display = config.thinking_enabled ? 'flex' : 'none';
        document.getElementById('apiKey').required = false;

        document.getElementById('configSubmitBtn').textContent = '更新配置';
        document.getElementById('configCancelEditBtn').style.display = 'inline-block';

        var tabForm = document.getElementById('configTabForm');
        if (tabForm) tabForm.classList.add('active');
        var tabList = document.getElementById('configTabList');
        if (tabList) tabList.classList.remove('active');

        var tabs = document.querySelectorAll('.config-tab');
        tabs.forEach(function(t) { t.classList.remove('active'); });
        if (tabs[0]) tabs[0].classList.add('active');

        llmForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function exitEditMode() {
        document.getElementById('editingConfigId').value = '';
        document.getElementById('llmConfigForm').reset();
        document.getElementById('isActive').checked = true;
        document.getElementById('jsonMode').checked = false;
        document.getElementById('thinkingEnabled').checked = false;
        document.getElementById('thinkingEffort').value = 'high';
        document.getElementById('thinkingEffortGroup').style.display = 'none';
        document.getElementById('apiKey').required = true;
        document.getElementById('configSubmitBtn').textContent = '保存配置';
        document.getElementById('configCancelEditBtn').style.display = 'none';
    }

    async function loadConfigs() {
        try {
            var response = await fetch('/api/llm/configs');
            var result = await response.json();
            var list = document.getElementById('configsList');

            if (!result.configs || result.configs.length === 0) {
                list.innerHTML = '<p class="empty">暂无配置</p>';
                return;
            }

            list.innerHTML = result.configs.map(function(config) {
                return '<div class="config-item' + (config.is_active ? ' active' : '') + '">' +
                    '<div class="config-item-header">' +
                        '<h4>' + App.escapeHtml(config.config_name) + '</h4>' +
                        '<span class="config-item-status' +
                            (config.is_active ? ' enabled' : ' disabled') + '">' +
                            (config.is_active ? '已启用' : '未启用') +
                        '</span>' +
                    '</div>' +
                    '<div class="config-item-details">' +
                        '<span>服务商: ' + App.escapeHtml(config.provider) + '</span>' +
                        '<span>模型: ' + App.escapeHtml(config.model_name) + '</span>' +
                        '<span>Max Tokens: ' + config.max_tokens + '</span>' +
                        '<span>Temperature: ' + config.temperature + '</span>' +
                        (config.json_mode ? '<span>JSON模式: 已启用</span>' : '') +
                        (config.thinking_enabled ? '<span>思考模式: ' + (config.thinking_effort || 'high') + '</span>' : '') +
                    '</div>' +
                    '<div class="config-item-actions">' +
                        '<button class="config-item-btn" onclick="ConfigSidebarModule.editConfig(' +
                            config.id + ')">编辑</button>' +
                        '<button class="config-item-btn" onclick="ConfigSidebarModule.toggleConfig(' +
                            config.id + ', ' + (!config.is_active) + ')">' +
                            (config.is_active ? '禁用' : '启用') +
                        '</button>' +
                        '<button class="config-item-btn danger" onclick="ConfigSidebarModule.deleteConfig(' +
                            config.id + ')">删除</button>' +
                    '</div>' +
                '</div>';
            }).join('');
        } catch (error) {
            console.error('加载配置失败:', error);
        }
    }

    async function editConfig(configId) {
        try {
            var response = await fetch('/api/llm/configs');
            var result = await response.json();
            var config = result.configs.find(function(c) { return c.id === configId; });

            if (!config) {
                alert('配置不存在');
                return;
            }
            enterEditMode(config);
        } catch (error) {
            alert('加载配置失败: ' + error.message);
        }
    }

    async function toggleConfig(configId, isActive) {
        try {
            var response = await fetch('/api/llm/config/' + configId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isActive })
            });
            var result = await response.json();
            if (result.success) {
                await loadConfigs();
            } else {
                throw new Error(result.message || '操作失败');
            }
        } catch (error) {
            alert('操作失败: ' + error.message);
        }
    }

    async function deleteConfig(configId) {
        if (!confirm('确定要删除此配置吗？')) return;
        try {
            var response = await fetch('/api/llm/config/' + configId, { method: 'DELETE' });
            var result = await response.json();
            if (result.success) {
                if (document.getElementById('editingConfigId').value == configId) {
                    exitEditMode();
                }
                await loadConfigs();
            } else {
                throw new Error(result.message || '删除失败');
            }
        } catch (error) {
            alert('删除失败: ' + error.message);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        initConfig();
    });

    return {
        editConfig: editConfig,
        toggleConfig: toggleConfig,
        deleteConfig: deleteConfig,
        loadConfigs: loadConfigs
    };
})();