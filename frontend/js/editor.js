window.EditorModule = (function() {
    var state = App.getState();
    var isEditing = false;
    var evidenceVisible = false;

    function initEditor() {
        var versionSelect = document.getElementById('versionSelect');
        if (versionSelect) {
            versionSelect.addEventListener('change', function() {
                var version = this.value;
                if (version && state.visitId) {
                    loadEMRByVersion(state.visitId, version);
                }
            });
        }

        var editBtn = document.getElementById('editEMR');
        var saveBtn = document.getElementById('saveEMR');
        var cancelBtn = document.getElementById('cancelEdit');
        var toggleEvidenceBtn = document.getElementById('toggleEvidence');

        if (editBtn) {
            editBtn.addEventListener('click', function() {
                if (!state.emrRecord) {
                    alert('请先加载病历');
                    return;
                }
                enterEditMode();
            });
        }

        if (saveBtn) {
            saveBtn.addEventListener('click', function() { saveEMREdits(); });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() { exitEditMode(); });
        }

        if (toggleEvidenceBtn) {
            toggleEvidenceBtn.addEventListener('click', function() {
                if (evidenceVisible) {
                    hideEvidence();
                } else {
                    showEvidence();
                }
            });
        }

        var soapHeaders = document.querySelectorAll('.soap-section-header');
        soapHeaders.forEach(function(header) {
            header.addEventListener('click', function() {
                var section = this.parentElement;
                section.classList.toggle('collapsed');
            });
        });

        App.on('emrGenerated', function(data) {
            currentEMRRecord = data.emrRecord;
            App.showEditorContent();
            displayEMR(data.emrRecord);
            if (state.visitId) loadEMRVersions(state.visitId);
            loadEvidenceData(state.visitId);
            App.setActivePanel('editor');
        });

        App.on('emrStatusLoaded', function(data) {
            if (state.visitId) {
                loadEMRVersions(state.visitId);
            }
        });

        App.on('printEMR', function() {
            printEMR();
        });
    }

    var currentEMRRecord = null;

    async function loadEMRVersions(visitId) {
        try {
            var response = await fetch('/api/emr/versions/' + visitId);
            var result = await response.json();

            var select = document.getElementById('versionSelect');
            if (!select) return;
            select.innerHTML = '';

            result.versions.forEach(function(v) {
                var option = document.createElement('option');
                option.value = v.version;

                var timeStr = '未知时间';
                if (v.created_at) {
                    try {
                        var date = new Date(v.created_at);
                        timeStr = date.toLocaleString('zh-CN', {
                            year: 'numeric', month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit', second: '2-digit'
                        });
                    } catch (e) {}
                }

                option.textContent = '版本 ' + v.version + ' (' + v.record_type + ') - ' + timeStr;
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
            var response = await fetch('/api/emr/record/' + visitId + '?version=' + version);
            var result = await response.json();
            currentEMRRecord = result;
            state.emrRecord = result;
            state.currentRecordId = result.record_id;
            App.setState({ emrRecord: result, currentRecordId: result.record_id });
            displayEMR(result);
            App.updateStatusBarInfo({ version: version });
            await loadEvidenceData(visitId);
        } catch (error) {
            console.error('加载病历失败:', error);
        }
    }

    async function loadEvidenceData(visitId) {
        try {
            var response = await fetch('/api/emr/evidence/' + visitId);
            var result = await response.json();
            App.setState({ evidenceData: result.evidence || [] });
        } catch (error) {
            console.error('加载证据数据失败:', error);
        }
    }

    function displayEMR(emrRecord) {
        var emrJson = emrRecord.emr_json;
        displaySection('subjectiveContent', emrJson.subjective, 'subjective');
        displaySection('objectiveContent', emrJson.objective, 'objective');
        displaySection('assessmentContent', emrJson.assessment, 'assessment');
        displaySection('planContent', emrJson.plan, 'plan');
    }

    function displaySection(elementId, sectionData, sectionName) {
        var element = document.getElementById(elementId);
        if (!element) return;

        if (!sectionData) {
            element.innerHTML = '<p class="empty">暂无数据</p>';
            return;
        }

        var html = '';

        if (sectionData.text !== undefined && sectionData.text !== null) {
            html += '<div class="section-text" data-field="' + sectionName + '.text">' +
                (sectionData.text || '暂无内容') + '</div>';
        }

        var fields = Object.keys(sectionData).filter(function(k) {
            return k !== 'text' && k !== 'evidence_traces';
        });
        if (fields.length > 0) {
            html += '<div class="section-fields">';
            fields.forEach(function(field) {
                var fieldData = sectionData[field];
                if (fieldData && fieldData.value !== undefined && fieldData.value !== null) {
                    var evidenceHtml = buildEvidenceHtml(sectionName, field, fieldData);
                    html += '<div class="field-item" data-field="' + sectionName + '.' + field + '">' +
                        '<div class="field-name">' + App.getFieldName(field) + '</div>' +
                        '<div class="field-value">' + (fieldData.value || '暂无') + '</div>' +
                        evidenceHtml + '</div>';
                }
            });
            html += '</div>';
        }

        element.innerHTML = html || '<p class="empty">暂无数据</p>';
        setTimeout(function() { addExpandListeners(); }, 0);
    }

    function buildEvidenceHtml(sectionName, field, fieldData) {
        var traces = fieldData.evidence_traces || [];
        if (traces.length === 0) return '';

        var fieldValue = fieldData.value || '';
        var html = '<div class="evidence-traces"><strong>证据来源</strong>';
        if (fieldValue) {
            html += '<div class="evidence-final-value"><strong>最终病历</strong>' +
                App.escapeHtml(fieldValue) + '</div>';
        }
        html += '<ul>';
        traces.forEach(function(trace) {
            var speaker = trace.speaker || '未知';
            var originalSpeaker = trace.original_speaker || speaker;
            var speakerCorrected = trace.speaker_corrected || false;
            var content = trace.content || '';
            var turnText = trace.turn_text || '';
            var turnIndex = trace.turn_index !== undefined ? trace.turn_index : '-';

            var speakerHtml = '<span class="evidence-speaker' +
                (speakerCorrected ? ' corrected' : '') + '">' +
                App.escapeHtml(speaker) + '</span>';
            if (speakerCorrected) {
                speakerHtml += ' <span class="evidence-speaker-correction">' +
                    '(原: ' + App.escapeHtml(originalSpeaker) +
                    ' → ' + App.escapeHtml(speaker) + ')</span>';
            }

            html += '<li class="evidence-item" data-turn-index="' + turnIndex + '">' +
                '<div class="evidence-header">' + speakerHtml +
                '<span class="evidence-turn">轮次 ' + turnIndex + '</span></div>' +
                '<div class="evidence-detail">' +
                '<div class="evidence-label">LLM标注片段</div>' +
                '<div class="evidence-content">' + (content ? createExpandableText(content, 150) : '-') + '</div>';
            if (turnText) {
                html += '<div class="evidence-label">完整转写文本</div>' +
                    '<div class="evidence-turn-text">' + createExpandableText(turnText, 150) + '</div>';
            }
            html += '</div></li>';
        });
        html += '</ul></div>';
        return html;
    }

    function enterEditMode() {
        isEditing = true;
        var editBtn = document.getElementById('editEMR');
        var saveBtn = document.getElementById('saveEMR');
        var cancelBtn = document.getElementById('cancelEdit');

        if (editBtn) editBtn.style.display = 'none';
        if (saveBtn) saveBtn.style.display = 'inline-block';
        if (cancelBtn) cancelBtn.style.display = 'inline-block';

        var sections = ['subjectiveContent', 'objectiveContent', 'assessmentContent', 'planContent'];
        sections.forEach(function(sectionId) {
            var section = document.getElementById(sectionId);
            if (section) makeSectionEditable(section);
        });

        App.updateStatusBar('编辑模式');
    }

    function exitEditMode() {
        isEditing = false;
        var editBtn = document.getElementById('editEMR');
        var saveBtn = document.getElementById('saveEMR');
        var cancelBtn = document.getElementById('cancelEdit');

        if (editBtn) editBtn.style.display = 'inline-block';
        if (saveBtn) saveBtn.style.display = 'none';
        if (cancelBtn) cancelBtn.style.display = 'none';
    }

    function makeSectionEditable(section) {
        var textDivs = section.querySelectorAll('.section-text');
        textDivs.forEach(function(div) {
            var text = div.textContent;
            var field = div.dataset.field;
            div.innerHTML = '<textarea class="edit-textarea" data-field="' + field + '">' +
                App.escapeHtml(text) + '</textarea>';
        });

        var valueDivs = section.querySelectorAll('.field-value');
        valueDivs.forEach(function(div) {
            var text = div.textContent;
            div.innerHTML = '<textarea class="edit-textarea">' + App.escapeHtml(text) + '</textarea>';
        });
    }

    async function saveEMREdits() {
        if (!currentEMRRecord) {
            alert('没有可保存的病历');
            return;
        }

        var updatedEMR = JSON.parse(JSON.stringify(currentEMRRecord.emr_json));
        var textareas = document.querySelectorAll('.edit-textarea');

        textareas.forEach(function(textarea) {
            var field = textarea.dataset.field;
            var value = textarea.value;

            if (field) {
                var parts = field.split('.');
                if (parts.length === 2) {
                    var section = parts[0];
                    var fieldName = parts[1];
                    if (fieldName === 'text') {
                        if (!updatedEMR[section]) updatedEMR[section] = {};
                        updatedEMR[section].text = value;
                    }
                }
            }
        });

        var fieldEdits = document.querySelectorAll('.field-item .edit-textarea');
        fieldEdits.forEach(function(textarea) {
            var fieldItem = textarea.closest('.field-item');
            if (fieldItem) {
                var field = fieldItem.dataset.field;
                if (field) {
                    var parts = field.split('.');
                    if (parts.length === 2) {
                        var section = parts[0];
                        var fieldName = parts[1];
                        if (!updatedEMR[section]) updatedEMR[section] = {};
                        if (!updatedEMR[section][fieldName]) updatedEMR[section][fieldName] = {};
                        updatedEMR[section][fieldName].value = textarea.value;
                    }
                }
            }
        });

        try {
            var response = await fetch('/api/emr/record/' + state.visitId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ emr_json: updatedEMR, record_type: 'user_edited' })
            });
            var result = await response.json();

            if (result.status === 'success') {
                alert('病历保存成功！新版本: ' + result.version);
                exitEditMode();
                await loadEMRVersions(state.visitId);
                App.updateStatusBar('病历已保存', 'success');
            } else {
                throw new Error(result.message || '保存失败');
            }
        } catch (error) {
            alert('保存失败: ' + error.message);
        }
    }

    function printEMR() {
        var patientName = '';
        var visitDate = '';

        fetch('/api/emr/visit/' + state.visitId)
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(visitInfo) {
                if (visitInfo) {
                    patientName = visitInfo.patient_name || '';
                    visitDate = visitInfo.visit_date || '';
                }
                doPrint(patientName, visitDate);
            })
            .catch(function() { doPrint('', ''); });
    }

    function doPrint(patientName, visitDate) {
        var printWindow = window.open('', '_blank');
        var emrContent = document.getElementById('emrContent').cloneNode(true);

        var editElements = emrContent.querySelectorAll('.edit-textarea');
        editElements.forEach(function(el) {
            var span = document.createElement('span');
            span.textContent = el.value;
            el.parentNode.replaceChild(span, el);
        });

        var evidenceElements = emrContent.querySelectorAll('.evidence-traces');
        evidenceElements.forEach(function(el) { el.remove(); });

        var headerInfo = '';
        if (patientName || visitDate) {
            var parts = [];
            if (patientName) parts.push('患者姓名: ' + patientName);
            if (visitDate) parts.push('就诊日期: ' + visitDate);
            headerInfo = '<p class="patient-info">' + parts.join(' | ') + '</p>';
        }

        printWindow.document.write('<!DOCTYPE html><html><head><meta charset="UTF-8">' +
            '<title>病历打印</title>' +
            '<style>' +
            '* { margin: 0; padding: 0; box-sizing: border-box; }' +
            'body { font-family: SimSun, serif; padding: 40px; line-height: 1.8; color: #000; background: #fff; }' +
            'h1 { text-align: center; font-size: 24px; margin-bottom: 30px; }' +
            'h3 { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 5px; margin: 20px 0 10px 0; }' +
            '.soap-section { margin-bottom: 30px; }' +
            '.section-text { margin-bottom: 15px; text-indent: 2em; }' +
            '.field-item { margin-bottom: 10px; }' +
            '.field-name { font-weight: bold; display: inline; }' +
            '.field-value { display: inline; }' +
            '.patient-info { text-align: center; margin-bottom: 20px; font-size: 14px; }' +
            '@media print { body { padding: 0; } }' +
            '</style></head><body>' +
            '<h1>门诊病历</h1>' + headerInfo + emrContent.innerHTML +
            '</body></html>');

        printWindow.document.close();
        printWindow.focus();
        setTimeout(function() { printWindow.print(); }, 500);
    }

    async function showEvidence() {
        var panel = document.getElementById('evidencePanel');
        var list = document.getElementById('evidenceList');
        var evidenceData = App.getState().evidenceData;

        if (!evidenceData || evidenceData.length === 0) {
            if (state.visitId) await loadEvidenceData(state.visitId);
            evidenceData = App.getState().evidenceData;
        }

        if (!evidenceData || evidenceData.length === 0) {
            list.innerHTML = '<p class="empty">暂无证据溯源数据</p>';
        } else {
            var html = '<table class="editor-evidence-table"><thead><tr>';
            html += '<th>字段类型</th><th>最终病历</th><th>标注片段</th><th>原始转写</th><th>说话人</th><th>轮次</th>';
            html += '</tr></thead><tbody>';

            evidenceData.forEach(function(ev) {
                var turnText = ev.turn_text || '-';
                var fieldValue = ev.field_value || '-';
                var content = ev.content || '-';

                html += '<tr>' +
                    '<td>' + App.getFieldName(ev.field_type) + '</td>' +
                    '<td title="' + App.escapeHtml(fieldValue) + '">' +
                        createExpandableText(fieldValue, 100) + '</td>' +
                    '<td title="' + App.escapeHtml(content) + '">' +
                        createExpandableText(content, 100) + '</td>' +
                    '<td title="' + App.escapeHtml(turnText) + '">' +
                        createExpandableText(turnText, 100) + '</td>' +
                    '<td>' + (ev.speaker || '-') + '</td>' +
                    '<td>' + (ev.turn_index !== null ? ev.turn_index : '-') + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table>';
            list.innerHTML = html;
            addExpandListeners();
        }

        panel.style.display = 'block';
        evidenceVisible = true;
        document.getElementById('toggleEvidence').innerHTML = App.icon('paperclip', 14) + ' 隐藏溯源';
    }

    function hideEvidence() {
        document.getElementById('evidencePanel').style.display = 'none';
        evidenceVisible = false;
        document.getElementById('toggleEvidence').innerHTML = App.icon('paperclip', 14) + ' 证据溯源';
    }

    function createExpandableText(text, maxLength) {
        if (!text || text.length <= maxLength) {
            return '<span class="full-text">' + App.escapeHtml(text) + '</span>';
        }
        var truncated = text.substring(0, maxLength);
        return '<span class="truncated-text">' + App.escapeHtml(truncated) + '...</span>' +
            '<span class="full-text" style="display:none;">' + App.escapeHtml(text) + '</span>' +
            '<button class="expand-btn" data-expanded="false">展开</button>';
    }

    function addExpandListeners() {
        document.querySelectorAll('.expand-btn').forEach(function(btn) {
            if (btn.dataset.bound) return;
            btn.dataset.bound = 'true';
            btn.addEventListener('click', function() {
                var parent = this.parentElement;
                var truncated = parent.querySelector('.truncated-text');
                var full = parent.querySelector('.full-text');

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

    document.addEventListener('DOMContentLoaded', function() {
        initEditor();
    });

    return {
        displayEMR: displayEMR,
        loadEMRVersions: loadEMRVersions
    };
})();