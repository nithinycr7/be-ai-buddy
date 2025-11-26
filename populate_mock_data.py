"""
Populate MongoDB with mock data for progress tracking system.
Run with: python populate_mock_data.py
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, date, timedelta

# MongoDB connection
MONGO_URI = "mongodb+srv://aibuddymongo:Team%40123@aibuddy.global.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"

async def populate_data():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["aibuddy-dev"]  # Match the database name from config.py
    
    print("🔗 Connected to MongoDB")
    
    # Get existing daily classes
    classes = await db.classes_daily.find({}).to_list(100)
    print(f"📚 Found {len(classes)} daily classes")
    
    # Create quizzes for each daily class
    quizzes_data = []
    
    for cls in classes:
        daily_id = str(cls["_id"])
        tenant = cls.get("tenant", "demo-school")
        subject = cls["subject"]
        topic = cls["topics"][0] if cls.get("topics") else "General Topic"
        
        # Generate quiz questions based on subject
        questions = generate_quiz_questions(subject, topic)
        
        quiz = {
            "daily_id": daily_id,
            "subject": subject,
            "topic": topic,
            "class_no": cls["class_no"],
            "section": cls["section"],
            "tenant": tenant,
            "questions": questions,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        quizzes_data.append(quiz)
    
    # Insert quizzes
    if quizzes_data:
        result = await db.quizzes.insert_many(quizzes_data)
        print(f"✅ Inserted {len(result.inserted_ids)} quizzes")
    
    # Create sample quiz responses and progress for students
    # Student 1: Hikmat (GreenValleyHigh)
    # Student 2: demo student (demo-school)
    
    students_data = [
        {"student_id": "1245372", "tenant": "GreenValleyHigh"},
        {"student_id": "demo_student_1", "tenant": "demo-school"}
    ]
    
    quiz_responses = []
    progress_records = []
    
    for student in students_data:
        student_id = student["student_id"]
        tenant = student["tenant"]
        
        # Get classes for this tenant
        tenant_classes = [c for c in classes if c.get("tenant") == tenant]
        
        # Create sample responses for last 3 classes
        for i, cls in enumerate(tenant_classes[:3]):
            daily_id = str(cls["_id"])
            
            # Get quiz for this class
            quiz = await db.quizzes.find_one({"daily_id": daily_id, "tenant": tenant})
            if not quiz:
                continue
            
            quiz_id = str(quiz["_id"])
            
            # Simulate quiz attempts (2 attempts, improving score)
            for attempt in [1, 2]:
                # First attempt: 50-75%, Second attempt: 75-100%
                correct_count = len(quiz["questions"]) // 2 if attempt == 1 else len(quiz["questions"])
                score = (correct_count / len(quiz["questions"])) * 100
                
                # Generate responses
                responses = {}
                correct_answers = {}
                
                for idx, q in enumerate(quiz["questions"]):
                    qid = q["qid"]
                    correct_opt = q["correct"][0]
                    
                    # First attempt: get some wrong, second attempt: all correct
                    if attempt == 1 and idx >= correct_count:
                        # Wrong answer
                        wrong_opts = [opt["key"] for opt in q["options"] if opt["key"] != correct_opt]
                        responses[qid] = [wrong_opts[0]] if wrong_opts else [correct_opt]
                    else:
                        # Correct answer
                        responses[qid] = [correct_opt]
                    
                    correct_answers[qid] = [correct_opt]
                
                quiz_response = {
                    "daily_id": daily_id,
                    "student_id": student_id,
                    "quiz_id": quiz_id,
                    "tenant": tenant,
                    "attempt_number": attempt,
                    "attempted_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=attempt*10)).isoformat() + "Z",
                    "responses": responses,
                    "correct_answers": correct_answers,
                    "score": score,
                    "correct_count": correct_count,
                    "total_questions": len(quiz["questions"]),
                    "time_taken_seconds": 120 + (attempt * 30)
                }
                
                quiz_responses.append(quiz_response)
            
            # Create progress record (after 2nd quiz attempt)
            summary_viewed = i <= 2  # View summary for first 3 classes
            story_generated = i <= 1  # Generate story for first 2 classes
            best_score = 100.0  # Best score from 2nd attempt
            
            completion = 0.0
            if summary_viewed:
                completion += 25.0
            if story_generated:
                completion += 25.0
            completion += (best_score / 100.0) * 50.0
            
            progress = {
                "student_id": student_id,
                "daily_id": daily_id,
                "tenant": tenant,
                "date": cls["date"],
                "class_no": cls["class_no"],
                "section": cls["section"],
                "subject": cls["subject"],
                "summary_viewed": summary_viewed,
                "summary_viewed_at": (datetime.utcnow() - timedelta(hours=4-i)).isoformat() + "Z" if summary_viewed else None,
                "story_generated": story_generated,
                "story_id": None,  # Would be set by actual story generation
                "story_generated_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=30)).isoformat() + "Z" if story_generated else None,
                "quiz_taken": True,
                "quiz_id": quiz_id,
                "quiz_attempts": 2,
                "quiz_best_score": best_score,
                "quiz_latest_score": best_score,
                "quiz_first_attempt_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=10)).isoformat() + "Z",
                "quiz_last_attempt_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=20)).isoformat() + "Z",
                "completion_percentage": completion,
                "is_completed": completion >= 75.0,
                "completed_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=20)).isoformat() + "Z" if completion >= 75.0 else None,
                "created_at": (datetime.utcnow() - timedelta(hours=4-i)).isoformat() + "Z",
                "updated_at": (datetime.utcnow() - timedelta(hours=3-i, minutes=20)).isoformat() + "Z"
            }
            
            progress_records.append(progress)
    
    # Insert quiz responses
    if quiz_responses:
        result = await db.quiz_responses.insert_many(quiz_responses)
        print(f"✅ Inserted {len(result.inserted_ids)} quiz responses")
    
    # Insert progress records
    if progress_records:
        result = await db.student_progress.insert_many(progress_records)
        print(f"✅ Inserted {len(result.inserted_ids)} progress records")
    
    print("✨ Mock data population complete!")
    
    client.close()

def generate_quiz_questions(subject, topic):
    """Generate quiz questions based on subject and topic."""
    
    # Physics - Newton's Laws
    if "Physics" in subject and "Newton" in topic:
        return [
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
        ]
    
    # Chemistry - Periodic Table
    elif "Chemistry" in subject:
        return [
            {
                "qid": "q1",
                "question": "Which element has the atomic number 1?",
                "options": [
                    {"key": "option_a", "description": "Helium"},
                    {"key": "option_b", "description": "Hydrogen"},
                    {"key": "option_c", "description": "Lithium"},
                    {"key": "option_d", "description": "Oxygen"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q2",
                "question": "Elements in the same column are called a...",
                "options": [
                    {"key": "option_a", "description": "Period"},
                    {"key": "option_b", "description": "Group"},
                    {"key": "option_c", "description": "Block"},
                    {"key": "option_d", "description": "Series"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q3",
                "question": "Which group contains the Noble Gases?",
                "options": [
                    {"key": "option_a", "description": "Group 1"},
                    {"key": "option_b", "description": "Group 17"},
                    {"key": "option_c", "description": "Group 18"},
                    {"key": "option_d", "description": "Group 2"}
                ],
                "correct": ["option_c"]
            },
            {
                "qid": "q4",
                "question": "What is the symbol for Sodium?",
                "options": [
                    {"key": "option_a", "description": "So"},
                    {"key": "option_b", "description": "Sd"},
                    {"key": "option_c", "description": "Na"},
                    {"key": "option_d", "description": "Ni"}
                ],
                "correct": ["option_c"]
            }
        ]
    
    # History - Mughal Empire
    elif "History" in subject:
        return [
            {
                "qid": "q1",
                "question": "Who founded the Mughal Empire?",
                "options": [
                    {"key": "option_a", "description": "Akbar"},
                    {"key": "option_b", "description": "Babur"},
                    {"key": "option_c", "description": "Humayun"},
                    {"key": "option_d", "description": "Aurangzeb"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q2",
                "question": "Which monument did Shah Jahan build?",
                "options": [
                    {"key": "option_a", "description": "Red Fort"},
                    {"key": "option_b", "description": "Qutub Minar"},
                    {"key": "option_c", "description": "Taj Mahal"},
                    {"key": "option_d", "description": "Fatehpur Sikri"}
                ],
                "correct": ["option_c"]
            },
            {
                "qid": "q3",
                "question": "Who was known as the 'Great' Mughal emperor?",
                "options": [
                    {"key": "option_a", "description": "Babur"},
                    {"key": "option_b", "description": "Akbar"},
                    {"key": "option_c", "description": "Jahangir"},
                    {"key": "option_d", "description": "Shah Jahan"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q4",
                "question": "In which year was the Battle of Panipat fought?",
                "options": [
                    {"key": "option_a", "description": "1526"},
                    {"key": "option_b", "description": "1556"},
                    {"key": "option_c", "description": "1761"},
                    {"key": "option_d", "description": "1857"}
                ],
                "correct": ["option_a"]
            }
        ]
    
    # Biology - Cell Structure
    elif "Biology" in subject:
        return [
            {
                "qid": "q1",
                "question": "What is the control center of the cell?",
                "options": [
                    {"key": "option_a", "description": "Mitochondria"},
                    {"key": "option_b", "description": "Nucleus"},
                    {"key": "option_c", "description": "Cell Membrane"},
                    {"key": "option_d", "description": "Chloroplast"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q2",
                "question": "Which organelle is called the powerhouse of the cell?",
                "options": [
                    {"key": "option_a", "description": "Nucleus"},
                    {"key": "option_b", "description": "Mitochondria"},
                    {"key": "option_c", "description": "Ribosome"},
                    {"key": "option_d", "description": "Lysosome"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q3",
                "question": "Which structure is unique to plant cells?",
                "options": [
                    {"key": "option_a", "description": "Cell Membrane"},
                    {"key": "option_b", "description": "Mitochondria"},
                    {"key": "option_c", "description": "Cell Wall"},
                    {"key": "option_d", "description": "Nucleus"}
                ],
                "correct": ["option_c"]
            },
            {
                "qid": "q4",
                "question": "What controls what enters and exits the cell?",
                "options": [
                    {"key": "option_a", "description": "Cell Wall"},
                    {"key": "option_b", "description": "Nucleus"},
                    {"key": "option_c", "description": "Cell Membrane"},
                    {"key": "option_d", "description": "Cytoplasm"}
                ],
                "correct": ["option_c"]
            }
        ]
    
    # Generic quiz for other subjects
    else:
        return [
            {
                "qid": "q1",
                "question": f"What is a key concept of {topic}?",
                "options": [
                    {"key": "option_a", "description": "Concept A"},
                    {"key": "option_b", "description": "Concept B"},
                    {"key": "option_c", "description": "Concept C"},
                    {"key": "option_d", "description": "Concept D"}
                ],
                "correct": ["option_a"]
            },
            {
                "qid": "q2",
                "question": "Which of the following is true?",
                "options": [
                    {"key": "option_a", "description": "Statement 1"},
                    {"key": "option_b", "description": "Statement 2"},
                    {"key": "option_c", "description": "Statement 3"},
                    {"key": "option_d", "description": "Statement 4"}
                ],
                "correct": ["option_b"]
            },
            {
                "qid": "q3",
                "question": "Who is associated with this topic?",
                "options": [
                    {"key": "option_a", "description": "Person X"},
                    {"key": "option_b", "description": "Person Y"},
                    {"key": "option_c", "description": "Person Z"},
                    {"key": "option_d", "description": "Person W"}
                ],
                "correct": ["option_c"]
            },
            {
                "qid": "q4",
                "question": "What is the main application?",
                "options": [
                    {"key": "option_a", "description": "App 1"},
                    {"key": "option_b", "description": "App 2"},
                    {"key": "option_c", "description": "App 3"},
                    {"key": "option_d", "description": "App 4"}
                ],
                "correct": ["option_d"]
            }
        ]

if __name__ == "__main__":
    print("🚀 Starting mock data population...")
    asyncio.run(populate_data())
