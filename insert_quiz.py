"""Quick script to insert quiz data into MongoDB"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb+srv://aibuddymongo:Team%40123@aibuddy.global.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"

async def insert_quiz():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["aibuddy-dev"]
    
    quiz = {
        "daily_id": "6926095ce13657d2ef0aa298",
        "subject": "Physics",
        "topic": "Newton's Laws of Motion",
        "class_no": 8,
        "section": "A",
        "tenant": "demo-school",
        "questions": [
            {
                "qid": "q1",
                "question": "What is Newton's First Law also known as?",
                "options": [
                    {"key": "option_a", "description": "Law of Gravity"},
                    {"key": "option_b", "description": "Law of Inertia"},
                    {"key": "option_c", "description": "Law of Force"},
                    {"key": "option_d", "description": "Law of Action-Reaction"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q2",
                "question": "Which property of an object resists changes in motion?",
                "options": [
                    {"key": "option_a", "description": "Velocity"},
                    {"key": "option_b", "description": "Acceleration"},
                    {"key": "option_c", "description": "Inertia"},
                    {"key": "option_d", "description": "Force"}
                ],
                "correct": ["option_c"]
            },
            {
                "qid": "q3",
                "question": "What is the net force on an object moving at constant velocity?",
                "options": [
                    {"key": "option_a", "description": "Zero"},
                    {"key": "option_b", "description": "Constant positive"},
                    {"key": "option_c", "description": "Increasing"},
                    {"key": "option_d", "description": "Decreasing"}
                ],
                "correct": ["option_a"]
            },
            {
                "qid": "q4",
                "question": "An object at rest will stay at rest unless acted upon by...",
                "options": [
                    {"key": "option_a", "description": "Friction"},
                    {"key": "option_b", "description": "Gravity"},
                    {"key": "option_c", "description": "An unbalanced force"},
                    {"key": "option_d", "description": "Inertia"}
                ],
                "correct": ["option_c"]
            }
        ],
        "created_at": "2025-11-26T00:00:00Z"
    }
    
    # Check if already exists
    existing = await db.quizzes.find_one({"daily_id": quiz["daily_id"]})
    if existing:
        print("Quiz already exists, updating...")
        await db.quizzes.replace_one({"_id": existing["_id"]}, quiz)
        print(f"✅ Updated quiz: {existing['_id']}")
    else:
        result = await db.quizzes.insert_one(quiz)
        print(f"✅ Inserted quiz: {result.inserted_id}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(insert_quiz())
