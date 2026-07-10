import os

# Schema for structured output
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.utils.function_calling import convert_to_openai_function


class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Query that is optimized web search.")
    justification: str = Field(
        None, description="Why this query is relevant to the user's request."
    )

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-api-key-here")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

model = ChatOpenAI(
    base_url=DEEPSEEK_BASE_URL,
    model="deepseek-v4-pro",
    api_key=DEEPSEEK_API_KEY,
    temperature=0
)
# Use function calling instead of response_format for DeepSeek API compatibility
functions = [convert_to_openai_function(SearchQuery)]
structured_llm = model.bind(functions=functions)

# Invoke the LLM with function binding
output = structured_llm.invoke("How does Calcium CT score relate to high cholesterol?")
print(output)
print("*" * 20)

# Define a tool
def multiply(a: int, b: int) -> int:
    return a * b

# Augment the LLM with tools
llm_with_tools = model.bind_tools([multiply])

model.as_tool()

# Invoke the LLM with input that triggers the tool call
msg = llm_with_tools.invoke("What is 2 times 3?")
print(msg)
print("*" * 20)
# Get the tool call
msg.tool_calls
