# 新UI页面 - 在现有服务中添加新路由
# 这是一个完整的HTML+JS应用，使用模态弹窗和深色主题

NEW_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>✨ AI 文章创意工作室</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      background: linear-gradient(135deg, #0f172e 0%, #1a1f35 100%);
      color: #e0e6ed;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
    }

    /* 容器 */
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 20px;
    }

    /* 顶部导航 */
    header {
      background: rgba(20, 28, 50, 0.8);
      backdrop-filter: blur(10px);
      padding: 20px 0;
      margin-bottom: 40px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      position: sticky;
      top: 0;
      z-index: 100;
    }

    header .inner {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    h1 {
      font-size: 24px;
      font-weight: 700;
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }

    .status-badge {
      padding: 8px 16px;
      background: rgba(99, 102, 241, 0.2);
      border: 1px solid rgba(99, 102, 241, 0.5);
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      color: #a5b4fc;
    }

    .status-badge.running {
      background: rgba(59, 130, 246, 0.2);
      border-color: rgba(59, 130, 246, 0.5);
      color: #93c5fd;
    }

    .status-badge.success {
      background: rgba(34, 197, 94, 0.2);
      border-color: rgba(34, 197, 94, 0.5);
      color: #86efac;
    }

    /* 主体布局 */
    main {
      display: grid;
      grid-template-columns: 400px 1fr;
      gap: 30px;
    }

    /* 左侧配置面板 */
    .config-panel {
      background: rgba(20, 28, 50, 0.5);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 30px;
      height: fit-content;
      position: sticky;
      top: 100px;
    }

    .config-panel h2 {
      font-size: 18px;
      margin-bottom: 20px;
      color: #fff;
    }

    .form-group {
      margin-bottom: 20px;
    }

    .form-group label {
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
      font-weight: 600;
      color: #a0aec0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .form-group input,
    .form-group textarea,
    .form-group select {
      width: 100%;
      padding: 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      color: #e0e6ed;
      font-family: inherit;
      font-size: 13px;
      transition: all 0.2s;
    }

    .form-group input:focus,
    .form-group textarea:focus,
    .form-group select:focus {
      outline: none;
      background: rgba(255, 255, 255, 0.1);
      border-color: #6366f1;
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
    }

    .form-group textarea {
      resize: vertical;
      min-height: 80px;
    }

    /* 按钮 */
    button {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      padding: 12px 16px;
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      color: white;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    button:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(99, 102, 241, 0.3);
    }

    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .btn-secondary {
      background: rgba(255, 255, 255, 0.1);
      color: #a5b4fc;
    }

    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    /* 右侧内容区 */
    .content-area {
      display: flex;
      flex-direction: column;
      gap: 30px;
    }

    .card {
      background: rgba(20, 28, 50, 0.5);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 30px;
    }

    .card h2 {
      font-size: 18px;
      margin-bottom: 20px;
      color: #fff;
    }

    /* 进度条 */
    .progress-container {
      margin-bottom: 20px;
    }

    .progress-steps {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 15px;
      margin-bottom: 20px;
    }

    .step {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
    }

    .step-number {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.1);
      border: 2px solid rgba(255, 255, 255, 0.2);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      color: #a0aec0;
      transition: all 0.3s;
    }

    .step.active .step-number {
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      border-color: #6366f1;
      color: white;
    }

    .step.done .step-number {
      background: linear-gradient(135deg, #10b981 0%, #34d399 100%);
      border-color: #10b981;
      color: white;
    }

    .step-label {
      font-size: 12px;
      color: #a0aec0;
      text-align: center;
    }

    .step.active .step-label {
      color: #6366f1;
      font-weight: 600;
    }

    .step.done .step-label {
      color: #10b981;
    }

    /* 指标网格 */
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 15px;
      margin-bottom: 20px;
    }

    .metric {
      background: rgba(255, 255, 255, 0.05);
      padding: 15px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.1);
    }

    .metric-label {
      font-size: 11px;
      color: #a0aec0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 16px;
      font-weight: 700;
      color: #e0e6ed;
      word-break: break-all;
    }

    /* 模态弹窗 */
    .modal {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(4px);
      z-index: 1000;
      animation: fadeIn 0.2s;
    }

    .modal.active {
      display: flex;
      align-items: center;
      justify-content: center;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    .modal-content {
      background: rgba(20, 28, 50, 0.95);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 40px;
      max-width: 90%;
      width: 1000px;
      max-height: 90vh;
      overflow-y: auto;
      animation: slideUp 0.3s;
    }

    @keyframes slideUp {
      from {
        opacity: 0;
        transform: translateY(20px);
      }
      to {
        opacity: 0;
        transform: translateY(0);
      }
    }

    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 30px;
      padding-bottom: 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }

    .modal-header h2 {
      margin: 0;
      font-size: 24px;
    }

    .modal-close {
      background: none;
      border: none;
      color: #a0aec0;
      font-size: 28px;
      cursor: pointer;
      padding: 0;
      width: auto;
      transition: color 0.2s;
    }

    .modal-close:hover {
      color: #e0e6ed;
    }

    /* 预设网格 */
    .presets-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 15px;
    }

    .preset-card {
      background: rgba(255, 255, 255, 0.05);
      border: 2px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 20px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .preset-card:hover {
      border-color: #6366f1;
      background: rgba(99, 102, 241, 0.1);
    }

    .preset-card.selected {
      border-color: #6366f1;
      background: rgba(99, 102, 241, 0.2);
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.2);
    }

    .preset-card-name {
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #fff;
    }

    .preset-card-info {
      font-size: 12px;
      color: #a0aec0;
      line-height: 1.6;
    }

    .preset-card-info div {
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
    }

    .preset-card-info strong {
      color: #cbd5e1;
    }

    /* 日志 */
    .log-box {
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 15px;
      font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
      font-size: 12px;
      color: #6ee7b7;
      max-height: 300px;
      overflow-y: auto;
      line-height: 1.6;
    }

    .log-line {
      margin-bottom: 4px;
    }

    /* 预览 */
    .preview-frame {
      width: 100%;
      height: 600px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      background: white;
    }

    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: #a0aec0;
    }

    .empty-state svg {
      width: 60px;
      height: 60px;
      margin-bottom: 20px;
      opacity: 0.5;
    }

    /* 响应式 */
    @media (max-width: 1200px) {
      main {
        grid-template-columns: 1fr;
      }

      .config-panel {
        position: static;
      }

      .metrics {
        grid-template-columns: repeat(2, 1fr);
      }

      .modal-content {
        width: 95%;
      }
    }

    @media (max-width: 768px) {
      .progress-steps {
        grid-template-columns: repeat(2, 1fr);
      }

      .metrics {
        grid-template-columns: 1fr;
      }

      .presets-grid {
        grid-template-columns: 1fr;
      }
    }

    /* 加载动画 */
    .loading {
      display: inline-block;
      width: 4px;
      height: 4px;
      background: currentColor;
      border-radius: 50%;
      animation: blink 1.4s infinite;
      margin-left: 4px;
    }

    .loading:nth-child(1) { animation-delay: 0s; }
    .loading:nth-child(2) { animation-delay: 0.2s; }
    .loading:nth-child(3) { animation-delay: 0.4s; }

    @keyframes blink {
      0%, 60%, 100% { opacity: 0.3; }
      30% { opacity: 1; }
    }
  </style>
</head>
<body>
  <header>
    <div class="inner">
      <h1>✨ AI 文章创意工作室</h1>
      <div class="status-badge" id="statusBadge">准备就绪</div>
    </div>
  </header>

  <div class="container">
    <main>
      <!-- 左侧配置面板 -->
      <div class="config-panel">
        <h2>📝 生成配置</h2>

        <div class="form-group">
          <label>选择灵感</label>
          <select id="presetSelect">
            <option value="">加载中...</option>
          </select>
        </div>

        <button class="btn-secondary" id="generatePresetsBtn" type="button">
          🔄 换一批灵感
        </button>

        <div style="margin: 25px 0; padding: 20px 0; border-top: 1px solid rgba(255,255,255,0.1); border-bottom: 1px solid rgba(255,255,255,0.1);">
          <div class="form-group">
            <label>或输入创意描述</label>
            <textarea id="ideaInput" placeholder="例如：AI如何改变工作方式"></textarea>
          </div>
          <button class="btn-secondary" id="completePresetBtn" type="button">
            ✓ 完成创意
          </button>
        </div>

        <div class="form-group">
          <label>主题</label>
          <textarea id="topicInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>目标读者</label>
          <textarea id="audienceInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>语气风格</label>
          <textarea id="toneInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>小节数</label>
          <input id="sectionsInput" type="number" min="1" max="8" placeholder="3-4">
        </div>

        <div class="form-group">
          <label>图片风格</label>
          <textarea id="styleInput" placeholder="自动填入"></textarea>
        </div>

        <button id="generateBtn" type="button" style="margin-top: 20px;">
          ▶️ 开始生成文章
        </button>
      </div>

      <!-- 右侧内容区 -->
      <div class="content-area">
        <!-- 进度卡片 -->
        <div class="card">
          <h2>📊 生成进度</h2>
          <div class="progress-steps">
            <div class="step active" id="step1">
              <div class="step-number">1</div>
              <div class="step-label">草稿</div>
            </div>
            <div class="step" id="step2">
              <div class="step-number">2</div>
              <div class="step-label">图片</div>
            </div>
            <div class="step" id="step3">
              <div class="step-number">3</div>
              <div class="step-label">输出</div>
            </div>
            <div class="step" id="step4">
              <div class="step-number">4</div>
              <div class="step-label">完成</div>
            </div>
          </div>

          <div class="metrics">
            <div class="metric">
              <div class="metric-label">任务ID</div>
              <div class="metric-value" id="jobIdMetric">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">状态</div>
              <div class="metric-value" id="statusMetric">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">标题</div>
              <div class="metric-value" id="titleMetric" style="font-size: 13px;">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">图片数</div>
              <div class="metric-value" id="imageCountMetric">-</div>
            </div>
          </div>

          <div id="actionButtons" style="display: none; display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn-secondary" onclick="openLink('#htmlLink')">📄 HTML</button>
            <button class="btn-secondary" onclick="openLink('#mdLink')">📝 Markdown</button>
            <button class="btn-secondary" onclick="openLink('#jsonLink')">📦 JSON</button>
          </div>

          <div id="emptyState" class="empty-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2v20M2 12h20M6 6l12 12M18 6L6 18"/>
            </svg>
            <p>等待生成...</p>
          </div>
        </div>

        <!-- 日志卡片 -->
        <div class="card">
          <h2>📋 运行日志</h2>
          <div class="log-box" id="logBox">
            <div class="log-line" style="color: #a0aec0;">等待开始...</div>
          </div>
        </div>

        <!-- 预览卡片 -->
        <div class="card" id="previewCard" style="display: none;">
          <h2>👁️ 页面预览</h2>
          <iframe id="previewFrame" class="preview-frame" title="article preview"></iframe>
        </div>
      </div>
    </main>
  </div>

  <!-- 预设选择模态弹窗 -->
  <div class="modal" id="presetsModal">
    <div class="modal-content">
      <div class="modal-header">
        <h2>🎨 选择灵感</h2>
        <button class="modal-close" onclick="closePresetsModal()">×</button>
      </div>

      <div id="presetsLoading" style="text-align: center; padding: 40px;">
        <div style="font-size: 14px;">
          加载中<span class="loading"><span class="loading"><span class="loading"></span></span></span>
        </div>
      </div>

      <div id="presetsContainer" style="display: none;">
        <div class="presets-grid" id="presetsGrid"></div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.1); text-align: right;">
          <button id="confirmPresetsBtn" type="button" style="width: auto; padding: 12px 40px;">
            确认选择
          </button>
        </div>
      </div>
    </div>
  </div>

  <script>
    // ===== 全局状态 =====
    const state = {
      presets: [],
      selectedPresetIndex: null,
      jobId: null,
      pollTimer: null
    };

    // ===== 初始化 =====
    async function init() {
      try {
        const res = await fetch('/api/presets');
        const data = await res.json();
        state.presets = data.presets || [];
        updatePresetSelect();
      } catch (err) {
        console.error('Failed to load presets:', err);
      }
    }

    function updatePresetSelect() {
      const select = document.getElementById('presetSelect');
      select.innerHTML = state.presets.map((p, i) => `
        <option value="${i}">${p.index || i + 1}. ${p.name}</option>
      `).join('');

      select.addEventListener('change', (e) => {
        const idx = parseInt(e.target.value);
        if (idx >= 0) applyPreset(state.presets[idx]);
      });

      if (state.presets.length > 0) {
        select.value = '0';
        applyPreset(state.presets[0]);
      }
    }

    // ===== 预设操作 =====
    function applyPreset(preset) {
      document.getElementById('topicInput').value = preset.topic || '';
      document.getElementById('audienceInput').value = preset.audience || '';
      document.getElementById('toneInput').value = preset.tone || '';
      document.getElementById('sectionsInput').value = preset.section_count || preset.sections || '';
      document.getElementById('styleInput').value = preset.image_style || '';
    }

    document.getElementById('generatePresetsBtn').addEventListener('click', async () => {
      const brief = prompt('输入创意简报:');
      if (!brief) return;

      updateStatus('生成灵感中...');
      document.getElementById('generatePresetsBtn').disabled = true;

      try {
        const res = await fetch('/api/presets/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ brief, count: 5 })
        });

        const data = await res.json();
        if (data.presets) {
          state.presets = data.presets;
          displayPresetsModal(data.presets);
        }
      } catch (err) {
        alert('生成失败: ' + err.message);
      } finally {
        document.getElementById('generatePresetsBtn').disabled = false;
        updateStatus('准备就绪');
      }
    });

    function displayPresetsModal(presets) {
      const grid = document.getElementById('presetsGrid');
      grid.innerHTML = presets.map((p, i) => `
        <div class="preset-card" data-index="${i}" onclick="selectPresetCard(${i})">
          <div class="preset-card-name">${p.name}</div>
          <div class="preset-card-info">
            <div><strong>主题:</strong><span>${p.topic}</span></div>
            <div><strong>读者:</strong><span>${p.audience}</span></div>
            <div><strong>语气:</strong><span>${p.tone}</span></div>
            <div><strong>小节:</strong><span>${p.section_count}</span></div>
            <div><strong>图片:</strong><span>${p.image_style?.substring(0, 30)}...</span></div>
          </div>
        </div>
      `).join('');

      document.getElementById('presetsLoading').style.display = 'none';
      document.getElementById('presetsContainer').style.display = 'block';
      document.getElementById('presetsModal').classList.add('active');
    }

    function selectPresetCard(index) {
      state.selectedPresetIndex = index;
      document.querySelectorAll('.preset-card').forEach((card, i) => {
        card.classList.toggle('selected', i === index);
      });
    }

    document.getElementById('confirmPresetsBtn').addEventListener('click', () => {
      if (state.selectedPresetIndex !== null) {
        applyPreset(state.presets[state.selectedPresetIndex]);
        closePresetsModal();
      }
    });

    function closePresetsModal() {
      document.getElementById('presetsModal').classList.remove('active');
    }

    document.getElementById('completePresetBtn').addEventListener('click', async () => {
      const idea = document.getElementById('ideaInput').value.trim();
      if (!idea) {
        alert('请输入创意描述');
        return;
      }

      updateStatus('完成创意中...');
      document.getElementById('completePresetBtn').disabled = true;

      try {
        const res = await fetch('/api/presets/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ idea })
        });

        const data = await res.json();
        if (data.preset) {
          applyPreset(data.preset);
          document.getElementById('ideaInput').value = '';
          alert('✓ 创意已自动补全');
        }
      } catch (err) {
        alert('完成失败: ' + err.message);
      } finally {
        document.getElementById('completePresetBtn').disabled = false;
        updateStatus('准备就绪');
      }
    });

    // ===== 文章生成 =====
    document.getElementById('generateBtn').addEventListener('click', async () => {
      const topic = document.getElementById('topicInput').value.trim();
      if (!topic) {
        alert('请输入主题');
        return;
      }

      state.jobId = null;
      updateStatus('生成中...');
      updateProgressSteps(0);
      clearLogs();
      logMessage('📌 任务已创建，开始生成...');

      document.getElementById('generateBtn').disabled = true;

      try {
        const payload = {
          topic,
          audience: document.getElementById('audienceInput').value,
          tone: document.getElementById('toneInput').value,
          sections: parseInt(document.getElementById('sectionsInput').value) || undefined,
          image_style: document.getElementById('styleInput').value,
          storage_mode: 'local'
        };

        const res = await fetch('/api/articles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const job = await res.json();
        if (job.job_id) {
          state.jobId = job.job_id;
          updateProgressSteps(1);
          logMessage(`✓ Job ID: ${job.job_id}`);
          pollStatus();
        } else {
          alert('创建任务失败');
        }
      } catch (err) {
        alert('生成失败: ' + err.message);
        updateStatus('准备就绪');
        document.getElementById('generateBtn').disabled = false;
      }
    });

    // ===== 轮询状态 =====
    function pollStatus() {
      if (!state.jobId) return;

      fetch(`/api/jobs/${state.jobId}`)
        .then(r => r.json())
        .then(job => {
          updateJobUI(job);

          if (job.status === 'succeeded') {
            updateStatus('✓ 完成');
            updateProgressSteps(4);
            document.getElementById('generateBtn').disabled = false;
            logMessage('✓ 生成完成！');
          } else if (job.status === 'failed') {
            updateStatus('✗ 失败');
            document.getElementById('generateBtn').disabled = false;
            logMessage('✗ 生成失败: ' + (job.error || '未知错误'));
          } else {
            state.pollTimer = setTimeout(pollStatus, 1000);
          }
        })
        .catch(err => {
          logMessage('❌ 轮询失败: ' + err.message);
          state.pollTimer = setTimeout(pollStatus, 2000);
        });
    }

    function updateJobUI(job) {
      document.getElementById('jobIdMetric').textContent = job.job_id?.substring(0, 20) + '...' || '-';
      document.getElementById('statusMetric').textContent = {
        'queued': '排队中',
        'running': '生成中',
        'succeeded': '✓ 成功',
        'failed': '✗ 失败'
      }[job.status] || job.status;

      if (job.result) {
        document.getElementById('titleMetric').textContent = job.result.title?.substring(0, 20) + '...' || '-';
        document.getElementById('imageCountMetric').textContent = job.result.image_count || '-';

        if (job.result.article_html) {
          document.getElementById('previewFrame').src = job.result.article_html;
          document.getElementById('previewCard').style.display = 'block';
        }

        const buttons = [];
        if (job.result.article_html) buttons.push(['HTML', job.result.article_html]);
        if (job.result.article_markdown) buttons.push(['Markdown', job.result.article_markdown]);
        if (job.result.article_json) buttons.push(['JSON', job.result.article_json]);

        if (buttons.length > 0) {
          const html = buttons.map(([name, url]) => `
            <button class="btn-secondary" onclick="window.open('${url}', '_blank')">
              ${name}
            </button>
          `).join('');
          document.getElementById('actionButtons').innerHTML = html;
          document.getElementById('actionButtons').style.display = 'flex';
          document.getElementById('emptyState').style.display = 'none';
        }
      }

      if (job.logs && job.logs.length > 0) {
        job.logs.forEach(log => logMessage(log));
      }
    }

    function updateStatus(text) {
      const badge = document.getElementById('statusBadge');
      badge.textContent = text;
      badge.classList.toggle('running', text.includes('中'));
      badge.classList.toggle('success', text.includes('✓'));
    }

    function updateProgressSteps(step) {
      for (let i = 1; i <= 4; i++) {
        const el = document.getElementById(`step${i}`);
        el.classList.toggle('active', i === step);
        el.classList.toggle('done', i < step);
      }
    }

    function clearLogs() {
      document.getElementById('logBox').innerHTML = '';
    }

    function logMessage(msg) {
      const box = document.getElementById('logBox');
      const line = document.createElement('div');
      line.className = 'log-line';
      line.textContent = msg;
      box.appendChild(line);
      box.scrollTop = box.scrollHeight;
    }

    function openLink(selector) {
      const link = document.querySelector(selector);
      if (link) window.open(link.href, '_blank');
    }

    // 关闭模态时退出
    document.getElementById('presetsModal').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closePresetsModal();
    });

    // 初始化
    init();
  </script>
</body>
</html>
"""
