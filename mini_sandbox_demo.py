import multiprocessing
import io
import contextlib
import ast
import os # 增加os导入，用于最后的文件清理

# ====================================================================
# 核心沙箱实现 (已升级为可配置安全策略)
# ====================================================================

class SecurityError(Exception):
    """当代码包含不安全操作时抛出的自定义异常。"""
    pass

# AST“审查员”现在可以接收一个“白名单”
class SecurityVisitor(ast.NodeVisitor):
    """一个遍历AST并检查危险操作的访问者类。"""
    def __init__(self, allowed_functions: list = None):
        self.is_safe = True
        self.error_message = ""
        
        # 从一个基础的黑名单开始
        dangerous_funcs = {'open'}
        # 如果有函数被显式允许，就从黑名单中移除
        if allowed_functions:
            dangerous_funcs -= set(allowed_functions)
        
        self.DANGEROUS_FUNCTIONS = list(dangerous_funcs)
        self.DANGEROUS_MODULES = ['os', 'shutil', 'subprocess']

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in self.DANGEROUS_FUNCTIONS:
            self.is_safe = False
            self.error_message = f"SecurityError: Use of function '{node.func.id}' is forbidden by this sandbox's policy."
            return
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name in self.DANGEROUS_MODULES:
                self.is_safe = False
                self.error_message = f"SecurityError: Import of module '{alias.name}' is forbidden."
                return
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module and node.module in self.DANGEROUS_MODULES:
            self.is_safe = False
            self.error_message = f"SecurityError: Import from module '{node.module}' is forbidden."
            return
        self.generic_visit(node)

# 子进程执行函数现在需要接收并传递“白名单”
def _execute_in_sandbox(code_string: str, shared_state: dict, result_queue: multiprocessing.Queue, allowed_functions: list):
    try:
        tree = ast.parse(code_string)
        # 创建审查员时，传入“白名单”配置
        visitor = SecurityVisitor(allowed_functions=allowed_functions)
        visitor.visit(tree)

        if not visitor.is_safe:
            raise SecurityError(visitor.error_message)

        globals_for_exec = shared_state.copy()
        log_stream = io.StringIO()
        with contextlib.redirect_stdout(log_stream):
            exec(code_string, globals_for_exec)
        
        logs = log_stream.getvalue()
        output = globals_for_exec.get("_result", None)
        error = None

    except Exception as e:
        output = None
        logs = log_stream.getvalue() if 'log_stream' in locals() else ""
        error = e

    result_queue.put({"output": output, "logs": logs, "error": error})


class MiniSandbox:
    """一个迷你版的、用于演示的沙箱系统。"""

    # 初始化时可以接收一个“白名单”
    def __init__(self, allowed_functions: list = None):
        self._manager = multiprocessing.Manager()
        self._shared_state = self._manager.dict()
        self.allowed_functions = allowed_functions or []
        print(f"MiniSandbox 已初始化 (AST审查模式, 允许的函数: {self.allowed_functions})")

    def add_tool(self, tool_func: callable):
        tool_name = tool_func.__name__
        self._shared_state[tool_name] = tool_func
        print(f"  [工具已添加] -> {tool_name}")

    def add_variable(self, name: str, value):
        self._shared_state[name] = value
        print(f"  [变量已添加] -> {name} = {repr(value)}")

    def run(self, code_to_run: str):
        print(f'''
▶️ 准备在沙箱中执行代码:
--- CODE ---
{code_to_run}
----------
''')
        
        result_queue = multiprocessing.Queue()
        # 执行时，将“白名单”配置传递给子进程
        process = multiprocessing.Process(
            target=_execute_in_sandbox,
            args=(code_to_run, self._shared_state, result_queue, self.allowed_functions)
        )

        process.start()
        process.join(timeout=10)

        if process.is_alive():
            process.terminate()
            print("◀️ 结果: 执行超时！")
            return

        try:
            result = result_queue.get_nowait()
            print("◀️ 沙箱执行完毕，结果如下:")
            print(f"  - 输出 (Output): {repr(result['output'])}")
            print("  - 日志 (Logs):")
            logs_content = result['logs'] or '    (无日志输出)'
            print(logs_content.strip())
            if result['error']:
                print(f"  - 错误 (Error): {result['error']}")
        except multiprocessing.queues.Empty:
            print("◀️ 结果: 未能从沙箱获取任何结果。")

# ====================================================================
# 演示如何使用 MiniSandbox (可配置安全策略版)
# ====================================================================

def get_weather(city: str):
    print(f"[工具日志] 正在查询 {city} 的天气...")
    if city == "北京":
        return "晴朗, 25°C"
    elif city == "上海":
        return "多云, 28°C"
    else:
        return "未知"

if __name__ == "__main__":

    # --- 默认的、最严格的沙箱 ---
    strict_sandbox = MiniSandbox()
    strict_sandbox.add_tool(get_weather)
    strict_sandbox.add_variable("user_name", "小明")

    # --- 演示 1, 2, 3: 在严格沙箱中执行 ---
    print("\n--- 演示 1: 在严格沙箱中执行安全代码 ---")
    safe_code = '''print(f"你好, {user_name}!")
_result = get_weather("北京")'''
    strict_sandbox.run(safe_code)

    print("\n--- 演示 2: 在严格沙箱中尝试调用 open() ---")
    dangerous_code_open = '''f = open("secrets.txt", "w")'''
    strict_sandbox.run(dangerous_code_open)

    print("\n--- 演示 3: 在严格沙箱中尝试导入 os ---")
    dangerous_code_import = '''import os'''
    strict_sandbox.run(dangerous_code_import)

    # --- 演示 4: 创建一个配置不同的新沙箱，将 open 设为安全 ---
    print("\n\n======================================================")
    print("创建一个新的、配置不同的沙箱，允许使用 'open' 函数")
    print("======================================================")
    
    # 创建沙箱时，传入“白名单”
    permissive_sandbox = MiniSandbox(allowed_functions=['open'])
    
    print("\n--- 演示 4: 在宽松沙箱中执行 open() ---")
    code_to_run_in_permissive_sandbox = '''print("在一个配置不同的沙箱里，我将要打开一个文件...")
f = open("secrets.txt", "w")
f.write("pwned")
f.close()
print("文件已成功写入。")
_result = "File 'secrets.txt' created successfully."
'''
    permissive_sandbox.run(code_to_run_in_permissive_sandbox)

    # 验证文件是否真的被创建了
    if os.path.exists("secrets.txt"):
        print("\n[主程序验证] 文件 'secrets.txt' 已被沙箱成功创建。")
        # 清理创建的文件
        os.remove("secrets.txt")
        print("[主程序验证] 已清理创建的文件。")
    else:
        print("\n[主程序验证] 文件 'secrets.txt' 未被创建。")
