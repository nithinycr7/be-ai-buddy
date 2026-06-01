from __future__ import annotations
from openai import AzureOpenAI

from app.services.rag import search_cbse
from ..core.config import settings
from typing import List, Dict, Any, Optional

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


_chat_client = None

def get_chat_client():
    """
    OpenAI-compatible client backed by Gemini, used for SUMMARY + ASSESSMENT
    generation (model = settings.GEMINI_CHAT_MODEL, e.g. gemini-2.5-flash).
    Lets the existing client.chat.completions.create(...) calls work unchanged.
    Falls back to the Azure client if no Google key is configured.
    """
    global _chat_client
    if _chat_client is None:
        if settings.GOOGLE_API_KEY:
            from openai import OpenAI
            _chat_client = OpenAI(
                api_key=settings.GOOGLE_API_KEY,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
        else:
            _chat_client = get_client()
    return _chat_client


_gemini_client = None

def get_gemini_client():
    """Lazy singleton for the Google GenAI client. Returns None if no key is configured."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if not settings.GOOGLE_API_KEY:
        return None
    from google import genai
    _gemini_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _gemini_client

async def summarize(text: str, chunks:str,class_no:int,subject:str) -> str:
    client = get_chat_client()
    first_500_words = ' '.join(text.split()[:500])
    class_no = class_no
    subject = subject
    query = first_500_words
    chunks = search_cbse(query, class_no, subject, k=4)
    print(f"Found {len(chunks)} relevant chunks for summary.")
    if not chunks:
        return "No relevant chunks found for summary."
    system_prompt = """You are an expert teacher's assistant creating visual, structured class summaries for students aged 8-15.

STRICT RULES:
- Use ONLY facts from the provided transcript and textbook reference. Do NOT add external information.
- Give more preference to what is taught in the transcript.
- ALWAYS include at least one Mermaid diagram — this is MANDATORY.

OUTPUT FORMAT (Markdown):

## 📌 Key Concept
One-line summary of what was taught today.

## 🔑 Key Terms
| Term | Meaning |
|------|---------|
| ... | ... |

## 📖 What We Learned
2-4 short paragraphs explaining the topic simply. Use bullet points where helpful.

## 📊 Diagram
A Mermaid diagram that visually explains the concept. Wrap in ```mermaid code block.

Choose the BEST diagram type for the subject:
- Science (biology/chemistry): flowchart showing processes (e.g., photosynthesis flow, chemical reactions)
- Science (physics): flowchart showing cause-effect or force diagrams
- Math: flowchart showing step-by-step problem solving approach or concept relationships
- History/Social Studies: timeline using graph LR with dates and events
- Geography: flowchart showing relationships (e.g., climate → vegetation → wildlife)
- English/Language: flowchart showing grammar rules or story structure
- General: mindmap or flowchart showing concept hierarchy

DIAGRAM RULES:
- Use graph TD (top-down) for processes, graph LR (left-right) for timelines
- Keep max 8-10 nodes so it stays readable
- Use DESCRIPTIVE labels (e.g. "Sunlight provides energy" NOT just "Sunlight")
- Use subgraphs to group related concepts with clear titles
- Add emojis in labels for visual appeal (e.g. "🌞 Sunlight" → "🌿 Leaf")
- Connect nodes with labeled arrows explaining the relationship (e.g. -->|absorbs|)

## 💡 Remember This
One memorable analogy or memory trick that connects to real life."""

    resp = client.chat.completions.create(
        model=settings.GEMINI_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Transcript:\n{first_500_words}\n\nTextbook Reference:\n{chunks}\n\nGenerate the structured visual summary."
            },
        ],
    )
    return resp.choices[0].message.content.strip()

async def generate_story(topic: str, persona: str | None) -> tuple[str, int]:
    client = get_chat_client()
    prompt = f"Create a short motivational story (<=200 words) that teaches the concept: {topic}. "
    if persona:
        prompt += f"Style for a child who likes: {persona}."
    resp = client.chat.completions.create(
        model=settings.GEMINI_CHAT_MODEL,
        messages=[
            {"role":"system","content":"You create engaging, child-friendly educational stories."},
            {"role":"user","content":prompt},
        ],
        temperature=0.7,
    )
    text = resp.choices[0].message.content.strip()
    usage = resp.usage.total_tokens if resp.usage else 0
    return text, usage

async def generate_quiz(summary: str, n_questions: int = 5) -> List[Dict[str, Any]]:
    client = get_chat_client()
    schema = """Return JSON with a 'questions' array of objects:
    { "qid": "q1", "question": "...", "options":[{"key":"a","description":"..."},...], "correct":["a"] }"""
    resp = client.chat.completions.create(
        model=settings.GEMINI_CHAT_MODEL,
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

# ============================================
# Daily Quiz Generation Functions
# ============================================

async def extract_transcript_metadata(transcript: str, class_no: int, subject: str) -> Dict[str, Any]:
    """
    Extract metadata from transcript for quiz generation
    Returns: {topic, subtopics, keywords, confidence, difficulty_level}
    """
    client = get_chat_client()
    
    prompt = f"""Analyze this classroom transcript and extract:
1. Main topic (1-3 words)
2. Subtopics (list of 2-5 key concepts)
3. Keywords (5-10 important terms)
4. Confidence score (0.0-1.0) - how clear and complete is the transcript
5. Suggested difficulty level for grade {class_no}

Transcript:
{transcript[:1000]}  # First 1000 chars

Return JSON format:
{{
  "topic": "...",
  "subtopics": ["...", "..."],
  "keywords": ["...", "..."],
  "confidence": 0.85,
  "difficulty_level": "medium"
}}
"""
    
    try:
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": f"You are an expert at analyzing educational content for grade {class_no} {subject}."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        import json
        metadata = json.loads(resp.choices[0].message.content)
        return metadata
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return {
            "topic": subject,
            "subtopics": [],
            "keywords": [],
            "confidence": 0.3,
            "difficulty_level": "medium"
        }


async def generate_daily_quiz(
    transcript: str, 
    metadata: Dict[str, Any], 
    class_no: int,
    subject: str
) -> List[Dict[str, Any]]:
    """
    Generate exactly 6 questions in specific order:
    Q1: MCQ (easy) - basic recall
    Q2: Fill-in-the-blank (easy)
    Q3: MCQ with reasoning (medium)
    Q4: Solve problem (medium) - numerical/text answer
    Q5: HOTS/Application (medium-hard)
    Q6: Story-based (medium) - fun/engaging
    """
    client = get_chat_client()
    
    topic = metadata.get("topic", subject)
    keywords = ", ".join(metadata.get("keywords", []))
    
    prompt = f"""Create exactly 6 quiz questions for grade {class_no} students about: {topic}

Use this transcript and keywords: {keywords}

Transcript excerpt:
{transcript[:800]}

STRICT REQUIREMENTS - Generate in this EXACT order:

1. MCQ (easy) - Basic recall/definition question
2. FILL_BLANK (easy) - Complete the sentence with a key term
3. MCQ (medium) - Conceptual understanding with reasoning
4. SOLVE (medium) - Problem-solving question requiring numerical or short text answer
5. HOTS (medium-hard) - Application/real-world scenario question
6. STORY_BASED (medium) - Fun, engaging story-based question to maintain interest

For each question provide:
- qid: "q1", "q2", etc.
- question: the question text
- question_type: "MCQ", "FILL_BLANK", "SOLVE", "HOTS", or "STORY_BASED"
- difficulty: "easy", "medium", or "hard"
- options: array of {{"key": "a", "description": "..."}} (for MCQ/HOTS/STORY_BASED, empty for others)
- correct: array of correct answer keys (e.g., ["a"]) or the answer text for FILL_BLANK/SOLVE
- hint: REQUIRED. Provide a helpful hint that guides the student without giving away the answer directly. MUST NOT be empty.
- explanation: brief explanation of the correct answer

Return JSON:
{{
  "questions": [...]
}}
"""
    
    try:
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": f"You are an expert quiz creator for grade {class_no} {subject}. Create engaging, age-appropriate questions that test understanding at different cognitive levels."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            response_format={"type": "json_object"}
        )
        
        import json
        data = json.loads(resp.choices[0].message.content)
        questions = data.get("questions", [])
        
        # Ensure we have exactly 6 questions
        if len(questions) != 6:
            print(f"Warning: Generated {len(questions)} questions instead of 6")
        
        # Validate and normalize each question
        validated_questions = []
        for i, q in enumerate(questions[:6]):
            validated_q = validate_and_normalize_question(q, i + 1)
            validated_questions.append(validated_q)
        
        return validated_questions
        
    except Exception as e:
        print(f"Error generating daily quiz: {e}")
        return []


def validate_and_normalize_question(question: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Validate and normalize AI-generated question to ensure consistent structure
    """
    # Ensure required fields exist
    normalized = {
        "qid": question.get("qid", f"q{index}"),
        "question": question.get("question", f"Question {index}"),
        "question_type": question.get("question_type", "MCQ"),
        "difficulty": question.get("difficulty", "medium"),
        "options": question.get("options", []),
        "correct": question.get("correct", []),
        "hint": question.get("hint", ""),
        "explanation": question.get("explanation", "")
    }
    
    # Normalize correct answer based on question type
    question_type = normalized["question_type"]
    correct = normalized["correct"]
    
    if question_type in ["FILL_BLANK", "SOLVE"]:
        # These should be strings, not lists
        if isinstance(correct, list):
            normalized["correct"] = correct[0] if correct else ""
        elif not isinstance(correct, str):
            normalized["correct"] = str(correct)
    else:
        # MCQ, HOTS, STORY_BASED should be lists
        if isinstance(correct, str):
            normalized["correct"] = [correct]
        elif not isinstance(correct, list):
            normalized["correct"] = [str(correct)]
    
    # Ensure options is a list of dicts with 'key' and 'description'
    if not isinstance(normalized["options"], list):
        normalized["options"] = []
    
    # Validate each option
    validated_options = []
    for opt in normalized["options"]:
        if isinstance(opt, dict) and "key" in opt and "description" in opt:
            validated_options.append(opt)
        elif isinstance(opt, dict):
            # Try to fix malformed option
            validated_options.append({
                "key": opt.get("key", opt.get("id", "a")),
                "description": opt.get("description", opt.get("text", ""))
            })
    
    normalized["options"] = validated_options
    
    return normalized


async def generate_revision_quiz(
    subject: str, 
    class_no: int, 
    last_topics: List[str]
) -> List[Dict[str, Any]]:
    """
    Fallback quiz when transcript confidence is low
    Generates revision quiz from previously covered topics
    """
    client = get_chat_client()
    
    topics_str = ", ".join(last_topics) if last_topics else f"general {subject} concepts"
    
    prompt = f"""Create a revision quiz with 6 questions for grade {class_no} {subject}.
Topics to cover: {topics_str}

Generate the same 6-question structure:
1. MCQ (easy)
2. FILL_BLANK (easy)
3. MCQ (medium)
4. SOLVE (medium)
5. HOTS (medium-hard)
6. STORY_BASED (medium)

Each question should include: qid, question, question_type, difficulty, options (if applicable), correct, hint (REQUIRED, must not be empty), explanation.

Return JSON:
{{
  "questions": [...]
}}
"""
    
    try:
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"You create revision quizzes for grade {class_no} students."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            response_format={"type": "json_object"}
        )
        
        import json
        data = json.loads(resp.choices[0].message.content)
        raw_questions = data.get("questions", [])
        
        # Validate and normalize
        validated_questions = []
        for i, q in enumerate(raw_questions[:6]):
            validated_questions.append(validate_and_normalize_question(q, i + 1))
            
        return validated_questions
        
    except Exception as e:
        print(f"Error generating revision quiz: {e}")
        return []
