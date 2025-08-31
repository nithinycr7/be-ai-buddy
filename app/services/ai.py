from openai import AzureOpenAI

from app.services.rag import search_cbse
from ..core.config import settings
from typing import List, Dict, Any

_client: AzureOpenAI | None = None

def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
          _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview"
        )
    return _client

async def summarize(text: str, chunks:str,class_no:int,subject:str) -> str:
    client = get_client()
    first_500_words = ' '.join(text.split()[:500])
    class_no = class_no
    subject = subject
    query = first_500_words
    chunks = search_cbse(query, class_no, subject, k=4)
    print(f"Found {len(chunks)} relevant chunks for summary.")
    if not chunks:
        return "No relevant chunks found for summary."
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a concise teaching assistant for kids aged 7–14. "
                    "Summarize the class discussion into 7–10 bullet points, "
                    "Without losing any important information. Use both the transcript and the reference chunks to make the summary accurate and complete.Give more preference to what is taught in the transcript"
                    "Your summary should take most of the important and concrete points from the transcript and the reference chunks which are part of the standard textbook, "
                )
            },
            {
                "role": "user",
                "content": f"Transcript:\n{first_500_words}\n\nRelevant Chunk:\n{chunks}"
            },
        ],
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
