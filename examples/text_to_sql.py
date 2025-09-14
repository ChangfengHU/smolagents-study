import os
import sys
from pathlib import Path

# Make local "src" importable without installing the package (useful for quick local runs / PyCharm)
#https://platform.openai.com/docs/pricing
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # type: ignore
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool
from smolagents.models import ChatMessageStreamDelta
from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    inspect,
    text,
)


engine = create_engine("sqlite:///:memory:")
metadata_obj = MetaData()

# create city SQL table
table_name = "receipts"
receipts = Table(
    table_name,
    metadata_obj,
    Column("receipt_id", Integer, primary_key=True),
    Column("customer_name", String(16), primary_key=True),
    Column("price", Float),
    Column("tip", Float),
)
metadata_obj.create_all(engine)

rows = [
    {"receipt_id": 1, "customer_name": "Alan Payne", "price": 12.06, "tip": 1.20},
    {"receipt_id": 2, "customer_name": "Alex Mason", "price": 23.86, "tip": 0.24},
    {"receipt_id": 3, "customer_name": "Woodrow Wilson", "price": 53.43, "tip": 5.43},
    {"receipt_id": 4, "customer_name": "Margaret James", "price": 21.11, "tip": 1.00},
]
for row in rows:
    stmt = insert(receipts).values(**row)
    with engine.begin() as connection:
        cursor = connection.execute(stmt)

inspector = inspect(engine)
columns_info = [(col["name"], col["type"]) for col in inspector.get_columns("receipts")]

table_description = "Columns:\n" + "\n".join([f"  - {name}: {col_type}" for name, col_type in columns_info])
print(table_description)

from smolagents import tool


@tool
def sql_engine(query: str) -> str:
    """
    # 允许您在表上执行 SQL 查询。返回结果的字符串表示。
    # 表名为'receipts'。其描述如下:
    #     列:
    #     - receipt_id: 整数
    #     - customer_name: 可变长度字符串(16)
    #     - price: 浮点数
    #     - tip: 浮点数

    Args:
        query: 要执行的查询。这应该是正确的 SQL。
    """
    output = ""
    with engine.connect() as con:
        rows = con.execute(text(query))
        for row in rows:
            output += "\n" + str(row)
    return output


from smolagents import CodeAgent, InferenceClientModel

# Load .env if present
load_dotenv()
# gpt-5-nano	$0.05
#  gpt-4.1-nano	$0.10
# gpt-4o-mini	$0.15
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4.1-nano")
# model_id = os.getenv("OPENAI_MODEL_ID", "gpt-3.5-turbo")
# model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
# model_id = os.getenv("OPENAI_MODEL_ID", "gpt-5-nano-2025-08-07")

# If OPENAI_API_KEY is missing, do a friendly dry-run instead of crashing


model = OpenAIServerModel(
    model_id=model_id,
    api_base=api_base,
    api_key=api_key,
)
agent = CodeAgent(
    tools=[sql_engine],
    # model=InferenceClientModel(model_id="HuggingFaceH4/zephyr-7b-beta"),
    model=model,
)
agent.run("Can you give me the name of the client who got the most expensive receipt?")
