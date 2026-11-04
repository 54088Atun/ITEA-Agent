"""受控联网请求模型"""
from pydantic import BaseModel


class WebSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class WebFetchRequest(BaseModel):
    url: str
