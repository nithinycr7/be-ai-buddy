from openai import AzureOpenAI
from ..core.config import settings
from typing import List, Dict, Any

_client: AzureOpenAI | None = None

def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-08-01-preview"
        )
    return _client

async def summarize(text: str) -> str:
    client = get_client()
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role":"system","content":"You are a concise teaching assistant. Summarize the content in 5-7 bullet points."},
            {"role":"user","content":text},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()

async def generate_story(topic: str, persona: str | None) -> str:
    client = get_client()
    prompt = f"Create a short motivational story (<=200 words) that teaches the concept: {topic}. "
    if persona:
        prompt += f"Style for a child who likes: {persona}."
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role":"system","content":"You create engaging, child-friendly educational stories."},
            {"role":"user","content":prompt},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

async def generate_quiz(summary: str, n_questions: int = 5) -> List[Dict[str, Any]]:
    client = get_client()
    schema = """Return JSON with a 'questions' array of objects:
    { "qid": "q1", "question": "...", "options":[{"key":"a","description":"..."},...], "correct":["a"] }"""
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role":"system","content":"Generate objective MCQs for grade-school learners. 1 correct answer only unless topic needs multiple."},
            {"role":"user","content":f"Create {n_questions} MCQs from this summary:\n{summary}\n{schema}"},
        ],
        temperature=0.2,
        response_format={"type":"json_object"}
    )
    data = resp.choices[0].message.content
    import json
    try:
        parsed = json.loads(data)
        return parsed.get("questions", [])
    except Exception:
        return []
