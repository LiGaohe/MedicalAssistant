document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const audioFile = document.getElementById('audioFile');
    const uploadBtn = document.getElementById('uploadBtn');
    const configBtn = document.getElementById('configBtn');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const visitDate = document.getElementById('visitDate');
    
    const today = new Date().toISOString().split('T')[0];
    visitDate.value = today;
    
    let selectedFile = null;
    
    dropZone.addEventListener('click', () => audioFile.click());
    
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });
    
    audioFile.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
    
    configBtn.addEventListener('click', () => {
        window.location.href = '/static/config.html';
    });
    
    function handleFileSelect(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (ext !== 'wav' && ext !== 'mp3') {
            alert('仅支持wav和mp3格式');
            return;
        }
        
        selectedFile = file;
        dropZone.innerHTML = `<p>已选择: ${file.name}</p><p class="hint">点击重新选择</p>`;
        uploadBtn.disabled = false;
    }
    
    uploadBtn.addEventListener('click', async () => {
        if (!selectedFile) {
            alert('请先选择音频文件');
            return;
        }
        
        uploadBtn.disabled = true;
        progressSection.style.display = 'block';
        
        const formData = new FormData();
        formData.append('audio_file', selectedFile);
        formData.append('patient_name', document.getElementById('patientName').value);
        formData.append('visit_date', visitDate.value);
        
        try {
            progressFill.style.width = '30%';
            progressText.textContent = '上传进度: 30%';
            
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                progressFill.style.width = '100%';
                progressText.textContent = '上传成功！正在跳转...';
                
                setTimeout(() => {
                    window.location.href = `/static/result.html?visit_id=${result.visit_id}`;
                }, 1000);
            } else {
                throw new Error(result.message || '上传失败');
            }
        } catch (error) {
            alert('上传失败: ' + error.message);
            uploadBtn.disabled = false;
            progressSection.style.display = 'none';
        }
    });
});
