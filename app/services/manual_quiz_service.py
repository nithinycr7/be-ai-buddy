
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.services.ai import get_client
from app.services.rag import search_cbse
from app.prompts.quiz_prompts import board_style_prompt, rag_quiz_prompt
from app.models.schemas import Quiz
from ..core.config import settings
from bson import ObjectId

class ManualQuizService:
    def __init__(self, db):
        self.db = db
        self.client = get_client()

    async def generate_custom_quiz(self, 
                                   class_no: int, 
                                   subject: str, 
                                   topic: str,
                                   board: str, 
                                   difficulty: str, 
                                   num_questions: int, 
                                   topics: List[str]) -> Dict[str, Any]:
        """
        Generates a quiz based on specific topics and board style.
        """
        
        system_prompt = board_style_prompt(board, class_no, subject)
        
        user_prompt = f"""
        Create a quiz with exactly {num_questions} questions.
        
        Topics to cover: {", ".join(topics)}
        Difficulty Level: {difficulty}
        
        Structure:
        - Mix of MCQ (Multiple Choice), FILL_BLANK (Fill in the blanks), and SHORT_ANSWER.
        - Ensure questions align with the {board} board style constraints defined in system prompt.
        
        Output JSON Schema:
        {{
            "questions": [
                {{
                    "qid": "q1",
                    "question": "...",
                    "question_type": "MCQ",
                    "difficulty": "{difficulty}",
                    "options": [{{"key": "a", "description": "..."}}],
                    "correct": ["a"],
                    "hint": "...",
                    "explanation": "..."
                }}
            ]
        }}
        """
        
        try:
            resp = self.client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            data = json.loads(resp.choices[0].message.content)
            questions = data.get("questions", [])
            return questions
        except Exception as e:
            print(f"Error generating custom quiz: {e}")
            raise e

    async def generate_textbook_quiz(self, 
                                     class_no: int, 
                                     subject: str, 
                                     chapter: str, 
                                     num_questions: int, 
                                     difficulty: str) -> Dict[str, Any]:
        """
        Generates a quiz using RAG from the textbook content.
        """
        # 1. Retrieve relevant chunks from Vector DB
        # Query for "exercises questions summary" to get relevant parts
        query = f"exercises questions summary key concepts"
        chunks = await search_cbse(query, class_no, subject, k=6, chapter=chapter)
        
        if not chunks:
            # Fallback if no specific chapter chunks found?
            # Or just proceed with empty context (LLM might hallucinate or fail)
            print(f"Warning: No chunks found for {chapter}")
            context = f"Chapter: {chapter}. Please generate questions based on general knowledge of this chapter."
        else:
            context = "\n\n".join([c["text"] for c in chunks])
            
        # 2. Generate Quiz
        prompt = rag_quiz_prompt(context, num_questions, difficulty)
        
        try:
            resp = self.client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": f"You are an expert teacher for Class {class_no} {subject}."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3, # Lower temperature for RAG to stay faithful to text
                response_format={"type": "json_object"}
            )
            
            data = json.loads(resp.choices[0].message.content)
            questions = data.get("questions", [])
            return questions
        except Exception as e:
            print(f"Error generating textbook quiz: {e}")
            raise e

    async def create_and_save_quiz(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Orchestrates generation and saving to DB.
        """
        source = payload.get("source", "custom")
        class_no = payload.get("class_no")
        subject = payload.get("subject")
        board = payload.get("board", "CBSE")
        difficulty = payload.get("difficulty", "medium")
        num_questions = payload.get("num_questions", 6)
        
        questions = []
        topic_label = ""
        
        if source == "custom":
            topics = payload.get("topics", [])
            topic_label = ", ".join(topics[:3]) + ("..." if len(topics)>3 else "")
            questions = await self.generate_custom_quiz(
                class_no, subject, topic_label, board, difficulty, num_questions, topics
            )
        elif source == "textbook":
            chapter = payload.get("chapter_title") or payload.get("chapter_id") # Depending on what FE sends, logic might need adjustment if using ID
            # FE sends chapter_title in payload based on my QuizConfigPanel implementation
            topic_label = f"{chapter} (Textbook)"
            questions = await self.generate_textbook_quiz(
                class_no, subject, chapter, num_questions, difficulty
            )
            
        # Create Quiz Document
        quiz_doc = {
            "subject": subject,
            "topic": topic_label,
            "class_no": class_no,
            "board": board,
            "source": source,
            "difficulty_level": difficulty,
            "questions": questions,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "auto_generated": False, # Generated by teacher
            "is_custom": True,      # Flag for custom/manual
            "teacher_id": payload.get("teacher_id"), # If avail (TODO: Pass from FE/Auth)
            "tenant": payload.get("tenant", "default"),
            "published": True # Auto-publish for now?
        }
        
        result = await self.db.quizzes.insert_one(quiz_doc)
        quiz_doc["_id"] = str(result.inserted_id)
        
        return quiz_doc
