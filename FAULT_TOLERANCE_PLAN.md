# 🛡️ 容错 & 兜底方案

## 当前问题诊断

### 失败原因分析
```
错误1: JSON 解析失败（Grok模型）
  └─ "Extra data: line 1 column 4421"
  └─ 原因：响应数据在指定位置有多余内容
  └─ 现象：返回的 JSON 被截断或有垃圾数据

错误2: 连接中断（Vertex/Gemini模型）
  └─ "Connection aborted"
  └─ 原因：网络超时或服务不稳定
  └─ 现象：所有备选模型全部失败
```

### 为什么全部失败？
```
当前流程：
  模型1(Grok) → JSON解析失败 ❌
  模型2(Gemini) → 连接超时 ❌
  模型3(Grok-3) → 连接超时 ❌
  模型4(Grok-3-mini) → 连接超时 ❌
  模型5(Gemini-pro) → 连接超时 ❌

结果：全部失败，直接抛异常
```

---

## 改进方案（3层容错）

### 🔧 第1层：智能 JSON 修复

**问题：** Grok返回数据在4421字符处有畸形
**方案：** 尝试修复而不是直接失败

```python
def _decode_json_with_repair(response: requests.Response) -> dict[str, Any]:
    """Try to parse JSON; if fails, attempt repair and retry"""

    try:
        return response.json()
    except json.JSONDecodeError as exc:
        # 方案1: 尝试截断到最后一个完整对象
        text = response.text

        # 从后往前找最后的 }
        for i in range(len(text)-1, -1, -1):
            if text[i] == '}':
                try:
                    return json.loads(text[:i+1])
                except:
                    continue

        # 方案2: 尝试清理多余符号
        # ...

        # 最后才抛异常
        raise XAIAPIError(f"JSON repair failed: {exc}")
```

### ⚡ 第2层：智能重试（已有，但可增强）

**现状：** 每个模型有 `retry_attempts` 次机制
**改进：**
- 增加指数退避（延迟重试）
- JSON 失败立即重试（可能是临时错误）
- 连接失败等待后重试

```python
def _generate_via_gateway_candidate(...):
    for attempt in range(1, self.retry_attempts + 1):
        try:
            response = requests.post(...)
            data = _decode_json_with_repair(response)  # ✅ 新增修复
            return ...
        except json.JSONDecodeError as exc:
            if attempt < self.retry_attempts:
                # JSON 失败：立即重试
                time.sleep(0.5)
                continue
        except (ConnectionError, Timeout) as exc:
            if attempt < self.retry_attempts:
                # 网络失败：等待后重试
                time.sleep(2 ** attempt)
                continue
```

### 🔙 第3层：兜底方案（全部失败时）

**现状：** 全部失败 → 直接抛异常，任务失败
**改进：** 返回一个基础结构化文章 + 占位符

```python
def generate_article_draft(self, request: ArticleRequest) -> ArticleDraft:
    # ... 尝试所有后端 ...

    if all_failed:
        # 返回兜底方案而不是抛异常
        return self._generate_fallback_draft(request)

def _generate_fallback_draft(self, request: ArticleRequest) -> ArticleDraft:
    """Return a basic structured draft when all backends fail"""

    outline_items = request.outline.split('\n') if request.outline else []
    sections = []

    for i, item in enumerate(outline_items[:request.sections]):
        sections.append(ArticleSection(
            heading=item,
            hook=f"[Content placeholder for: {item}]",
            paragraphs=[
                f"This section covers: {item}",
                f"Key point: {request.key_points[i % len(request.key_points)] if request.key_points else 'TBD'}"
            ],
            bullets=[f"Point {j+1}" for j in range(3)],
            takeaway=f"Summary of {item}",
            image_prompt=f"Illustration for: {item}",
            image_alt=item,
            image_caption=item
        ))

    return ArticleDraft(
        title=request.topic,
        subtitle="[Fallback content - please review and edit]",
        ...
    )
```

---

## 实现优先级

### Priority 1（高）- 必须做
- ✅ JSON 修复（处理畸形数据）
- ✅ 智能重试（JSON失败立即重试）

### Priority 2（中）- 应该做
- ✅ 兜底方案（全部失败返回框架而不是异常）
- ✅ 改进错误日志（更清楚的失败原因）

### Priority 3（低）- 可以做
- [ ] 降级到更简单的模型
- [ ] 本地模板补充
- [ ] 缓存成功的文章结构

---

## 代码改造位置

### grok_wechat_article.py

1. **修改 `_decode_json()`** - 添加修复逻辑
   ```
   位置：第1520行附近
   改动：添加JSON修复逻辑
   ```

2. **修改 `_generate_via_gateway_candidate()`** - 增强重试
   ```
   位置：第740行附近
   改动：JSON失败时立即重试，网络失败时延迟重试
   ```

3. **新增 `_generate_fallback_draft()`** - 兜底方案
   ```
   位置：第738行后
   改动：当所有后端失败时调用
   ```

### 预期改进

| 场景 | 现在 | 改进后 |
|------|------|--------|
| JSON 畸形 | ❌ 失败 | ✅ 自动修复 |
| 临时网络错误 | ❌ 失败 | ✅ 自动重试 |
| 所有模型都挂 | ❌ 异常 | ✅ 返回框架 |
| 用户体验 | 任务失败 | 至少得到基础文章 |

---

## 测试场景

### 测试1：JSON 修复
```bash
# 模拟返回畸形JSON的模型
curl -X POST /api/articles -d '{...outline...}'
# 预期：自动修复并继续
```

### 测试2：网络失败+重试
```bash
# 模拟连接中断
# 预期：自动重试，成功
```

### 测试3：全部失败+兜底
```bash
# 模拟所有模型都失败
# 预期：返回基础框架，显示提示
```

---

## 建议的改动代码量

- `_decode_json()` 修复：**+20行**
- `_generate_via_gateway_candidate()` 增强重试：**+10行**
- `_generate_fallback_draft()` 新函数：**+30行**
- 测试更新：**+40行**

**总计：约100行代码，可显著提升可靠性**
