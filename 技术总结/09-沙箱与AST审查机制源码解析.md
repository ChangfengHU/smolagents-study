# 深度解析：smolagents沙箱与AST审查机制源码

本次分析深入 `smolagents` 的源码，特别是 `local_python_executor.py` 文件，以揭示其默认沙箱的实现原理。其核心在于放弃了直接 `exec()`，转而采用一种“步步为营”的AST（抽象语法树）审查机制，从而在保证功能的同时提供了关键的安全性。

---

### 第一部分：沙箱的实现——一个安全的“舞台”

沙箱的核心是创建一个隔离的、受限的运行环境。`LocalPythonExecutor` 通过 `multiprocessing` 库实现这一点，但其安全性的精髓在于对代码的精细审查，而非简单的进程隔离。

#### 1. 源码执行流程

整个流程始于 `LocalPythonExecutor.__call__`，它调用 `evaluate_python_code` 函数，开启了安全执行的旅程。

**第一站：代码解析为语法树 - `evaluate_python_code`**

```python
def evaluate_python_code(code: str, ...):
    try:
        # 关键第一步：将代码字符串解析成AST
        expression = ast.parse(code)
    except SyntaxError as e:
        raise InterpreterError(...) 

    # 关键第二步：遍历AST的顶层节点，逐一送去审查
    for node in expression.body:
        result = evaluate_ast(node, ...)
```
- **`ast.parse(code)`**: 这是安全机制的基石。它将不透明的代码字符串，转化为一个结构化的、可审查的“抽象语法树”对象。
- **`for node in expression.body:`**: 这里体现了“步步为营”的思想。它逐一处理代码的每个语句（AST节点），而不是一次性执行所有代码。

**第二站：“首席审查官” - `evaluate_ast`**

此函数是沙箱的心脏，作为一个大型的调度器，它根据当前AST节点的类型（如 `ast.Import`, `ast.Call`），将其分发给相应的、专门的审查函数处理。

```python
@safer_eval
def evaluate_ast(expression: ast.AST, ...):
    # ...
    if isinstance(expression, (ast.Import, ast.ImportFrom)):
        return evaluate_import(expression, ...)
    elif isinstance(expression, ast.Call):
        return evaluate_call(expression, ...)
    # ... 更多的elif ...
```

#### 2. 核心安全机制的源码实现

**A. 危险模块黑名单 (`evaluate_import`)**

当 `evaluate_ast` 遇到 `import` 语句时，会调用 `evaluate_import`。此函数是防御危险模块导入的第一道关卡。

```python
def evaluate_import(expression, state, authorized_imports):
    # ...
    for alias in expression.names:
        # 核心安全检查！
        if check_import_authorized(alias.name, authorized_imports):
            # 如果在白名单内，才允许导入
            ...
        else:
            # 未授权，直接拒绝并抛出异常！
            raise InterpreterError(f"Import of {alias.name} is not allowed. ...")
```
- **`check_import_authorized`**: 此函数将要导入的模块与 `authorized_imports` **白名单**进行比对。像 `os`, `shutil` 等危险模块默认不在这个白名单内，因此任何 `import os` 的尝试都会在这一步被直接拦截，从而阻止了后续的恶意文件操作。

**B. 限制魔法方法 (`evaluate_attribute`)**

此函数负责处理所有属性访问（如 `my_object.my_attribute`），是防止沙箱逃逸的关键。

```python
def evaluate_attribute(expression: ast.Attribute, ...) -> Any:
    # 核心安全检查！
    if expression.attr.startswith("__") and expression.attr.endswith("__"):
        raise InterpreterError(f"Forbidden access to dunder attribute: {expression.attr}")
    # ...
```
- **规则简单有效**: 任何以 `__` 开头和结尾的“魔法方法”或属性的访问都会被直接禁止，这封堵了许多高级的攻击路径。

**C. 危险函数黑名单 (`evaluate_call`)**

此函数在处理函数调用时，会检查被调用的函数是否被明确授权。

```python
def evaluate_call(call: ast.Call, ...) -> Any:
    # ... (代码找到要调用的函数 `func`)

    # 检查是否是未被明确授权的内置函数
    if (inspect.getmodule(func) == builtins) and ... and (func not in static_tools.values()):
        raise InterpreterError(...)
```
- **逻辑**: 即使一个函数是Python内置的（如 `open`），但只要它没有被显式地放入 `static_tools` 这个“工具白名单”中，就一律禁止调用。

---

### 第二部分：沙箱与工具执行的必然联系

`LocalPythonExecutor` 这个“海关安检员”（沙箱），同时扮演了“剧务总管”（工具执行器）的角色。

当 `evaluate_ast` 遍历到一个 `ast.Call` 节点时，它的审查流程如下：
1.  **识别**: 这是一个函数调用。
2.  **安全检查**: 它不是一个已知的危险函数。
3.  **能力检查**: 它是不是一个我被授权使用的工具？
4.  **执行**: 它在 `state` 字典（包含了所有注入的工具）中找到了这个函数名，确认是合法工具，于是执行调用。

因此，它们的关系是：**沙箱通过AST遍历，实现了对代码的“逐句审查”。正是这种审查机制，让它既有机会拦截危险操作，又有机会识别并执行合法的工具调用。两者是在同一个流程中完成的，密不可分。**
