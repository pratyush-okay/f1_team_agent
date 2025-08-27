from pydantic import BaseModel
from typing import List
from datetime import datetime

class NewsArticle(BaseModel):
    title: str
    description: str
    source: str
    published_at: datetime

class NewsFetchOutput(BaseModel):
    articles: List[NewsArticle]

class FinalNewsArticle(BaseModel):
    title: str
    news: str  # summary of the article
    source: str
    published_at: str

class F1NewsAnalysisOutput(BaseModel):
    articles: List[FinalNewsArticle]
    total_summary: str
