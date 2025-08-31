import os
import multiprocessing

# --- 准备工作 ---
# 1. 创建一个危险文件，我们不希望它被删除
DANGEROUS_FILE_PATH = "./do_not_delete_me.txt"
with open(DANGEROUS_FILE_PATH, "w") as f:
    f.write("This is a very important file.")

# 2. 模拟一个由AI生成的、意图删除文件的恶意代码字符串
MALICIOUS_CODE = f"import os; os.remove('{DANGEROUS_FILE_PATH}')"

# 3. 模拟一个安全的、只做计算的代码字符串
SAFE_CODE = "result = 10 + 5"

# --- 对比实验 ---

def run_code_unsafely(code_string):
    """【极度危险】直接在主进程中执行代码，没有沙箱。"""
    print("\n--- 正在无沙箱环境下执行代码... ---")
    try:
        # 直接使用 exec，这是非常危险的！
        exec(code_string)
        print(f"[不安全] 代码 '{code_string}' 执行成功。")
    except Exception as e:
        print(f"[不安全] 代码执行失败: {e}")

def execute_in_subprocess(code_string, queue):
    """这个函数将在一个安全的子进程（沙箱）中运行。"""
    try:
        # 在这个受限的环境中，我们可以更安全地执行代码
        # 注意：一个真正安全的沙箱会在这里做更多限制，比如限制导入等
        # 但核心思想是，它在一个独立的进程中
        exec(code_string)
        queue.put(("success", None)) # 通过队列返回成功状态
    except Exception as e:
        queue.put(("error", e)) # 通过队列返回错误信息

def run_code_safely_with_sandbox(code_string):
    """【安全】使用子进程作为沙箱来执行代码。"""
    print("\n--- 正在沙箱环境下执行代码... ---")
    # 使用队列在进程间安全地传递结果
    result_queue = multiprocessing.Queue()
    
    # 创建并启动一个子进程（我们的沙箱）
    process = multiprocessing.Process(
        target=execute_in_subprocess, 
        args=(code_string, result_queue)
    )
    process.start()
    process.join(timeout=5) # 等待子进程结束，设置5秒超时

    if process.is_alive():
        process.terminate()
        print("[安全] 代码执行超时，已终止。")
        return

    try:
        status, error = result_queue.get_nowait()
        if status == "success":
            print(f"[安全] 代码 '{code_string}' 在沙箱中执行成功。")
        else:
            print(f"[安全] 沙箱中代码执行失败: {error}")
    except multiprocessing.queues.Empty:
        print("[安全] 未能从沙箱获取执行结果。")


if __name__ == "__main__":
    print(f"实验开始前，检查危险文件是否存在: {os.path.exists(DANGEROUS_FILE_PATH)}")
    
    # 1. 在不安全的环境下执行安全代码 (没问题)
    # run_code_unsafely(SAFE_CODE)
    
    # 2. 在安全沙箱里执行恶意代码 (应该能阻止破坏)
    run_code_safely_with_sandbox(MALICIOUS_CODE)
    print(f"沙箱执行后，检查危险文件是否存在: {os.path.exists(DANGEROUS_FILE_PATH)}")

    # 3. 在不安全的环境下执行恶意代码 (将会删除文件！)
    # 为了安全，默认注释掉这一行。如果你想看效果，可以取消注释，但请注意它会删除文件。
    # run_code_unsafely(MALICIOUS_CODE)
    # print(f"不安全执行后，检查危险文件是否存在: {os.path.exists(DANGEROUS_FILE_PATH)}")

    # 清理
    if os.path.exists(DANGEROUS_FILE_PATH):
        os.remove(DANGEROUS_FILE_PATH)
