# 📚 AI 文章生成系统 API 文档 - V1.0 Flow UI

## 概览

这是一个完整的三阶段 AI 文章生成系统，允许用户从灵感想法开始，通过 AI 自动补全参数，最终生成高质量的完整文章（包括配图）。

---

## 🌐 UI 访问

### 版本 1（三阶段 Flow UI）- **推荐使用** ⭐
```
http://localhost:8765/ui-flow
```
**特点：**
- 📝 阶段1：灵感输入 - 用户输入想法
- 🤖 阶段2：参数确认 - AI 自动生成并显示完整参数（可编辑）
- 🚀 阶段3：生成文章 - 后台生成，实时显示进度和日志

### 版本 0（经典 UI）
```
http://localhost:8765/ui
```

---

## 🔌 API 接口

### 1️⃣ POST `/api/presets/expand-idea`
**将用户灵感转换为完整的文章生成参数**

#### 请求示例
```bash
curl -X POST http://localhost:8765/api/presets/expand-idea \
  -H "Content-Type: application/json" \
  -d '{
    "idea": "我想写一篇关于如何学习 Python 的文章，特别是给初学者"
  }'
```

#### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `idea` | string | ✅ | 用户的灵感想法，越详细越好 |

#### 返回示例
```json
{
  "topic": "Python初学者完全指南：从零开始到项目实战",
  "audience": "零基础初学者，想快速上手编程",
  "tone": "温暖、鼓舞、实用导向",
  "sections": 4,
  "outline": "1. 为什么选Python 2. 环境搭建和第一个程序 3. 核心概念实战 4. 项目进阶",
  "key_points": [
    "从最简单的 print 开始建立信心",
    "通过做小项目来理解核心概念",
    "社区资源和文档是最好的老师"
  ],
  "story_type": "how-to",
  "use_web_search": false,
  "image_style": "clean code illustrations with Python snippets",
  "aspect_ratio": "16:9",
  "resolution": "2k"
}
```

#### 返回字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `topic` | string | 最终的文章主题 |
| `audience` | string | 目标受众描述 |
| `tone` | string | 文章风格和语调 |
| `sections` | integer | 章节数（1-8） |
| `outline` | string | 文章结构大纲 |
| `key_points` | array[string] | 核心要点列表（必须在文章中覆盖） |
| `story_type` | string | 文章类型：how-to / story / listicle / analysis / informative |
| `use_web_search` | boolean | 是否允许 AI 使用网络搜索 |
| `image_style` | string | 配图风格指导（英文） |
| `aspect_ratio` | string | 图片宽高比：16:9 / 1:1 / 3:4 |
| `resolution` | string | 图片分辨率：1k / 2k |

---

### 2️⃣ POST `/api/articles`
**创建文章生成任务（异步）**

#### 请求示例
```bash
curl -X POST http://localhost:8765/api/articles \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Python初学者完全指南：从零开始到项目实战",
    "audience": "零基础初学者",
    "tone": "温暖、鼓舞、实用导向",
    "sections": 4,
    "outline": "1. 为什么选Python 2. 环境搭建 3. 核心概念 4. 项目进阶",
    "key_points": ["建立信心", "通过项目学习", "利用社区资源"],
    "story_type": "how-to",
    "storage_mode": "local"
  }'
```

#### 请求参数（版本1新增字段）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `topic` | string | ✅ | 文章主题 |
| `audience` | string | ✓ | 目标受众 |
| `tone` | string | ✓ | 文章风格 |
| `sections` | integer | ✓ | 章节数（1-8）|
| `outline` | string | ✗ | **[新]** 文章大纲，指导内容结构 |
| `key_points` | array[string] | ✗ | **[新]** 核心要点列表，AI 必须覆盖 |
| `story_type` | string | ✗ | **[新]** 文章类型（默认：informative） |
| `use_web_search` | boolean | ✓ | 是否联网搜索 |
| `image_style` | string | ✓ | 配图风格 |
| `aspect_ratio` | string | ✓ | 图片宽高比 |
| `resolution` | string | ✓ | 图片分辨率 |
| `storage_mode` | string | ✓ | local / remote |

#### 返回示例
```json
{
  "job_id": "article-20260429-025417-ee14d1ba",
  "status": "queued",
  "request": {
    "topic": "...",
    "outline": "1. 为什么选Python 2. 环境搭建 3. 核心概念 4. 项目进阶",
    "key_points": ["建立信心", "通过项目学习", "利用社区资源"],
    "story_type": "how-to",
    ...
  }
}
```

---

### 3️⃣ GET `/api/jobs/{job_id}`
**查询任务状态和进度**

#### 请求
```bash
curl http://localhost:8765/api/jobs/article-20260429-025417-ee14d1ba
```

#### 返回示例
```json
{
  "job_id": "article-20260429-025417-ee14d1ba",
  "status": "processing",
  "created_at": "2026-04-29T02:54:17Z",
  "started_at": "2026-04-29T02:54:18Z",
  "logs": [
    {
      "at": "2026-04-29T02:54:18Z",
      "message": "Generating article draft..."
    },
    {
      "at": "2026-04-29T02:54:45Z",
      "message": "Generating cover image..."
    }
  ]
}
```

#### 状态说明

| 状态 | 说明 |
|------|------|
| `queued` | 任务已创建，等待处理 |
| `processing` | 任务正在处理中 |
| `succeeded` | ✅ 任务完成 |
| `failed` | ❌ 任务失败 |

---

### 4️⃣ GET `/api/jobs/{job_id}/result`
**获取最终生成结果（仅在任务成功时可用）**

#### 请求
```bash
curl http://localhost:8765/api/jobs/article-20260429-025417-ee14d1ba/result
```

#### 返回示例
```json
{
  "request": { ... },
  "draft": { ... },
  "cover_image": { ... },
  "section_images": [ ... ],
  "links": {
    "article_html": "/outputs/article-20260429-025417-ee14d1ba/article.html",
    "article_markdown": "/outputs/article-20260429-025417-ee14d1ba/article.md",
    "article_json": "/outputs/article-20260429-025417-ee14d1ba/article.json"
  }
}
```

---

## 💡 使用流程示例

### 场景1：使用三阶段 UI（推荐）
1. 打开 `http://localhost:8765/ui-flow`
2. 在阶段1输入灵感：*"我想写一篇关于AI时代职场机会的文章"*
3. 点击"生成参数" → AI 自动生成完整参数
4. 在阶段2审核和修改参数（如调整 outline、key_points）
5. 点击"生成文章" → 进入阶段3
6. 等待生成完成，查看最终文章

### 场景2：使用 API（编程集成）

```bash
# Step 1: 将灵感转换为参数
PARAMS=$(curl -s -X POST http://localhost:8765/api/presets/expand-idea \
  -H "Content-Type: application/json" \
  -d '{"idea": "我想写关于AI的文章"}')

# Step 2: 用参数生成文章
JOB=$(curl -s -X POST http://localhost:8765/api/articles \
  -H "Content-Type: application/json" \
  -d "$PARAMS")

JOB_ID=$(echo "$JOB" | jq -r '.job_id')

# Step 3: 轮询等待完成
while true; do
  STATUS=$(curl -s http://localhost:8765/api/jobs/$JOB_ID | jq -r '.status')
  if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  sleep 3
done

# Step 4: 获取结果
RESULT=$(curl -s http://localhost:8765/api/jobs/$JOB_ID/result)
echo "文章生成完成: $(echo $RESULT | jq -r '.links.article_html')"
```

---

## 🎯 版本1的关键改进

### 新增参数（内容可控性）

| 参数 | 功能 | 示例 |
|------|------|------|
| `outline` | **强制指导** 文章结构 | "1. 基础 2. 实践 3. 进阶 4. 总结" |
| `key_points` | **强制覆盖** 核心要点 | ["观点A", "观点B", "观点C"] |
| `story_type` | **指定** 文章类型 | "how-to" |

### 效果

用户输入灵感后，AI **自动生成这些参数**，无需手动指定。生成的文章将严格按照这些参数来组织内容。

---

## 📊 API Schema

### ArticleRequest 对象

```json
{
  "type": "object",
  "required": ["topic"],
  "properties": {
    "topic": {"type": "string", "description": "文章主题"},
    "audience": {"type": "string", "description": "目标受众"},
    "tone": {"type": "string", "description": "文章风格"},
    "sections": {"type": "integer", "minimum": 1, "maximum": 8},
    "outline": {"type": ["string", "null"], "description": "文章大纲（新）"},
    "key_points": {"type": ["array", "null"], "items": {"type": "string"}, "description": "关键要点（新）"},
    "story_type": {"type": "string", "enum": ["informative", "story", "how-to", "listicle", "analysis"], "description": "文章类型（新）"},
    "use_web_search": {"type": "boolean"},
    "image_style": {"type": "string", "description": "配图风格"},
    "aspect_ratio": {"type": "string", "enum": ["16:9", "1:1", "3:4", "4:3", "9:16"]},
    "resolution": {"type": "string", "enum": ["1k", "2k"]}
  }
}
```

---

## ✅ 测试命令

### 完整三阶段测试

```bash
# 1. 扩展灵感为完整参数
curl -X POST http://localhost:8765/api/presets/expand-idea \
  -H "Content-Type: application/json" \
  -d '{"idea": "如何学习Python的教程"}' | jq .

# 2. 使用参数生成文章
curl -X POST http://localhost:8765/api/articles \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Python初学者指南",
    "outline": "1. 基础 2. 实践 3. 进阶",
    "key_points": ["实践优先", "社区帮助"],
    "story_type": "how-to",
    "sections": 3
  }' | jq '.job_id'

# 3. 查询状态
curl http://localhost:8765/api/jobs/{job_id} | jq '.status'
```

---

## 📝 更新日志

### Version 1.0 (2026-04-29)
- ✨ **新增三阶段 Flow UI** - 更直观的用户体验
- ✨ **新增内容可控参数** - outline, key_points, story_type
- ✨ **新增 expand-idea 接口** - 一键将灵感转参数
- 🚀 **竞速模式** - 多个 AI 模型并发，选最快的
- 🎯 **参数验证** - 严格的类型检查和枚举校验

---

## 📞 支持

- 文档：http://localhost:8765/docs
- UI（Flow）：http://localhost:8765/ui-flow
- UI（经典）：http://localhost:8765/ui
