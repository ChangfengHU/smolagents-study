# Grok WeChat Article Studio UI 优化方案

## 目标
让用户能够**可视化看到整个流程**：预设生成 → Draft 预览 → 图片生成 → 最终成品

---

## 改造方案概览

### 现在的问题
```
用户操作：输入brief → 点击"开始生成" → 等待... → 看到最终结果
问题：
❌ 看不到预设是什么样的
❌ 看不到生成的draft文字
❌ 看不到整个流程的各个阶段
❌ 无法评估中间质量，只能全部重做
```

### 改造后的流程
```
用户体验：
1. 输入brief
2. 点击"换一批灵感" → 👀 预设对比面板弹出
   - 展示N个预设（名称、topic、audience、tone）
   - 用户选择最满意的
3. 点击"开始生成"
4. 👀 流程进度条显示：预设✓ → Draft✓ → 图片1/4 → 图片2/4...
5. 👀 Draft预览面板显示：
   - 标题、副标题
   - 摘要
   - 各section的内容（文字）
   - 用户评估："看起来不错"或"要改进"
6. 继续生成图片
7. 👀 最终结果：HTML预览 + 下载链接
```

---

## 具体改造内容

### 1. 顶部添加流程进度条

**位置**：在 `<header>` 后面、`<main>` 前面

```html
<div id="processFlow" class="process-flow" style="display:none;">
  <div class="flow-step">
    <div class="step-dot step-active">1</div>
    <div class="step-label">预设生成</div>
    <div class="step-time" id="step1Time"></div>
  </div>
  <div class="flow-connector"></div>

  <div class="flow-step">
    <div class="step-dot" id="step2Dot">2</div>
    <div class="step-label">文章草稿</div>
    <div class="step-time" id="step2Time"></div>
  </div>
  <div class="flow-connector"></div>

  <div class="flow-step">
    <div class="step-dot" id="step3Dot">3</div>
    <div class="step-label">图片生成</div>
    <div class="step-time" id="step3Time"></div>
  </div>
  <div class="flow-connector"></div>

  <div class="flow-step">
    <div class="step-dot" id="step4Dot">4</div>
    <div class="step-label">完成</div>
    <div class="step-time" id="step4Time"></div>
  </div>
</div>
```

**样式**：
```css
.process-flow {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px;
  background: var(--accent-soft);
  border-radius: 8px;
  margin-bottom: 24px;
}

.flow-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.step-dot {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #e3f0eb;
  border: 2px solid #0e7c66;
  color: #0e7c66;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 16px;
  transition: all 0.3s ease;
}

.step-dot.step-active {
  background: #0e7c66;
  color: white;
}

.step-label {
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  font-weight: 600;
}

.step-time {
  font-size: 11px;
  color: #888;
  margin-top: 4px;
}

.flow-connector {
  flex: 0.5;
  height: 2px;
  background: #d9e0dc;
  margin: 0 8px;
}
```

---

### 2. 添加预设对比面板

**位置**：在右侧任务结果区域，新增一个 tab 页

```html
<div id="presetsPanel" class="tab-panel" style="display:none;">
  <h3>生成的预设</h3>
  <div id="presetsList" class="presets-grid"></div>
  <div class="inline-actions">
    <button id="confirmPreset" class="primary" type="button">确认选中的预设</button>
  </div>
</div>
```

**样式**：
```css
.presets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.preset-card {
  border: 2px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--surface);
}

.preset-card:hover {
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(14, 124, 102, 0.1);
}

.preset-card.selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.preset-card h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--ink);
}

.preset-card .preset-meta {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.preset-card .preset-meta strong {
  color: var(--ink);
  font-weight: 600;
}
```

---

### 3. 添加 Draft 预览面板

**位置**：在右侧，预设对比下面或并列显示

```html
<div id="draftPanel" class="tab-panel" style="display:none;">
  <h3>文章草稿预览</h3>
  <div id="draftContent" class="draft-preview">
    <div class="draft-section">
      <h4 id="draftTitle">标题</h4>
      <p id="draftSubtitle" class="subtitle">副标题</p>
      <p id="draftSummary" class="summary">摘要</p>
    </div>

    <div id="draftSections" class="draft-sections"></div>

    <div class="draft-section">
      <h4 id="draftCTA">结尾</h4>
      <p id="draftCTAText"></p>
    </div>
  </div>

  <div class="draft-stats">
    <div class="stat-item">
      <span>字数</span>
      <strong id="draftWordCount">-</strong>
    </div>
    <div class="stat-item">
      <span>小节数</span>
      <strong id="draftSectionCount">-</strong>
    </div>
    <div class="stat-item">
      <span>生成耗时</span>
      <strong id="draftDuration">-</strong>
    </div>
  </div>
</div>
```

**样式**：
```css
.draft-preview {
  background: #fbfcfa;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
  max-height: 480px;
  overflow-y: auto;
  line-height: 1.8;
}

.draft-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}

.draft-section:last-child {
  border-bottom: none;
}

.draft-section h4 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
}

.draft-section p {
  margin: 8px 0;
  color: var(--ink);
}

.subtitle {
  color: var(--muted);
  font-size: 13px;
}

.summary {
  color: var(--muted);
  font-size: 12px;
  font-style: italic;
}

.draft-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 12px;
}

.stat-item {
  background: white;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  text-align: center;
}

.stat-item span {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
}

.stat-item strong {
  display: block;
  font-size: 16px;
  color: var(--accent);
}
```

---

### 4. JavaScript 更新

关键函数（在现有 JavaScript 基础上添加）：

```javascript
// 状态追踪
const processState = {
  startTime: null,
  stepTimings: {},
  currentStep: 1,
  presets: [],
  draft: null
};

// 显示预设对比
function showPresetsComparison(presets) {
  processState.presets = presets;
  const list = document.getElementById("presetsList");
  list.innerHTML = presets.map((preset, index) => `
    <div class="preset-card" data-index="${index}">
      <h4>${preset.name || `预设 ${index + 1}`}</h4>
      <div class="preset-meta">
        <div><strong>主题：</strong>${preset.topic}</div>
        <div><strong>读者：</strong>${preset.audience}</div>
        <div><strong>语气：</strong>${preset.tone}</div>
        <div><strong>小节：</strong>${preset.section_count}</div>
      </div>
    </div>
  `).join("");

  // 绑定选择事件
  list.querySelectorAll(".preset-card").forEach(card => {
    card.addEventListener("click", () => {
      list.querySelectorAll(".preset-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  document.getElementById("presetsPanel").style.display = "block";
}

// 显示 Draft 预览
function showDraftPreview(draft) {
  processState.draft = draft;
  document.getElementById("draftTitle").textContent = draft.title;
  document.getElementById("draftSubtitle").textContent = draft.subtitle;
  document.getElementById("draftSummary").textContent = draft.summary;

  // 显示各个 section
  const sectionsHtml = draft.sections.map(section => `
    <div class="draft-section">
      <h4>${section.heading}</h4>
      <p><strong>${section.hook}</strong></p>
      ${section.paragraphs.map(p => `<p>${p}</p>`).join("")}
      <ul>
        ${section.bullets.map(b => `<li>${b}</li>`).join("")}
      </ul>
      <p><em>💡 ${section.takeaway}</em></p>
    </div>
  `).join("");

  document.getElementById("draftSections").innerHTML = sectionsHtml;
  document.getElementById("draftCTAText").textContent = draft.call_to_action;

  // 统计信息
  const wordCount = (draft.intro_paragraphs.join("") + draft.sections.map(s => s.paragraphs.join("")).join("")).length;
  document.getElementById("draftWordCount").textContent = wordCount;
  document.getElementById("draftSectionCount").textContent = draft.sections.length;

  document.getElementById("draftPanel").style.display = "block";
}

// 更新流程进度
function updateProcessStep(step, duration = null) {
  processState.currentStep = step;
  const stepDot = document.getElementById(`step${step}Dot`);
  if (stepDot) {
    stepDot.classList.add("step-active");
  }

  if (duration) {
    document.getElementById(`step${step}Time`).textContent = `${duration.toFixed(1)}s`;
  }

  document.getElementById("processFlow").style.display = "flex";
}

// 轮询任务状态时，检查是否有 draft 可以预览
async function pollJobStatus(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  const job = await response.json();

  // 当 draft 准备好时
  if (job.draft && !processState.draft) {
    updateProcessStep(2, job.draft_duration);
    showDraftPreview(job.draft);
  }

  // 当图片在生成时
  if (job.status.includes("generating_images")) {
    updateProcessStep(3);
  }

  // 完成
  if (job.status === "succeeded") {
    updateProcessStep(4, job.total_duration);
  }
}
```

---

## 改造步骤

### 第一步：备份原文件
```bash
cp examples/grok_wechat_server.py examples/grok_wechat_server.py.backup
```

### 第二步：在 HTML 中添加新元素
在现有的 `<style>` 中加入上面的 `.process-flow`、`.presets-grid`、`.draft-preview` 样式。

在 `<header>` 后面添加流程条 HTML。

在 `<main>` 的右侧区域添加预设对比和 draft 预览面板。

### 第三步：更新 JavaScript
在现有脚本中添加新的函数，并在轮询任务时调用。

### 第四步：测试
```bash
.venv/bin/python examples/grok_wechat_server.py
# 访问 http://localhost:8765
```

---

## 预期效果

**改造前**：
- ❌ 用户点"开始生成"后只能干等
- ❌ 无法看到预设、draft的内容
- ❌ 如果不满意只能全部重做

**改造后**：
- ✅ 实时看到预设生成的结果
- ✅ 选择最满意的预设后再进行
- ✅ 在生成图片前先看draft文字
- ✅ 可以早期发现问题，避免浪费资源
- ✅ 完整的流程可视化

---

## 代码修改位置

| 部分 | 位置 | 改动 |
|-----|------|------|
| HTML 样式 | `<style>` | +150行，新增进度条、预设卡片、draft样式 |
| HTML 内容 | `<main>` 中 | +80行，新增流程条、预设面板、draft面板 |
| JavaScript | `<script>` 中 | +200行，新增进度更新、预览显示、轮询逻辑 |
| 后端 API | `/api/jobs/{job_id}` | 需要在返回值中包含 draft 信息 |

---

## 可选的后续改进

1. **拖拽编辑预设**：允许用户直接在UI中编辑预设字段
2. **Draft编辑**：生成draft后允许用户直接编辑文字
3. **多版本对比**：同时显示多个draft版本的差异
4. **成本估算**：显示每个步骤的API调用成本
5. **收藏模板**：保存喜欢的预设和draft组合，供下次使用

---

## 需要后端配合的改动

### 1. 返回 draft 信息

现在的 `/api/jobs/{job_id}` 返回：
```json
{
  "job_id": "...",
  "status": "...",
  "result": {...}  // 只有最终结果
}
```

改成：
```json
{
  "job_id": "...",
  "status": "...",
  "draft": {...},        // ← 新增：draft 信息
  "draft_duration": 5.2, // ← 新增：draft 生成耗时
  "image_progress": "2/4", // ← 新增：图片生成进度
  "result": {...}
}
```

### 2. 前端轮询时检查 draft

轮询逻辑中，当状态变为 "draft_ready" 时，直接返回 draft 供前端显示。

---

这样整个流程就**透明可见**了！用户能在每个阶段看到效果，提前决定是否继续或修改。
