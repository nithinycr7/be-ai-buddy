
def board_style_prompt(board, class_no, subject):
    """
    Returns system instruction based on the educational board.
    """
    board_upper = board.upper()
    
    base_prompt = f"You are an expert {board_upper} paper setter for Class {class_no} {subject}."
    
    styles = {
        "CBSE": """
        Style Guide:
        - Focus heavily on NCERT textbook concepts and keywords.
        - Questions should test 'Recall' and 'Understanding' Bloom's levels.
        - Use standard, direct language.
        - Avoid ambiguity.
        - Strictly follow the curriculum scope.
        """,
        "IB": """
        Style Guide:
        - Focus on inquiry-based learning and conceptual understanding.
        - Questions should test 'Analyze', 'Evaluate', and 'Create' Bloom's levels.
        - Use real-world contexts and cross-disciplinary references where possible.
        - Encourage critical thinking.
        """,
        "ICSE": """
        Style Guide:
        - Focus on detailed factual knowledge and comprehensive coverage.
        - Expect high rigor and precise definitions.
        - Questions can be more complex and detailed than standard level.
        """,
        "STATE": """
        Style Guide:
        - Focus on straightforward, textbook-aligned questions.
        - Keep language simple, direct, and accessible.
        - Focus on core fundamentals.
        """
    }
    
    return base_prompt + styles.get(board_upper, styles["CBSE"])

def rag_quiz_prompt(context, num_questions, difficulty):
    return f"""
    Create a quiz with {num_questions} questions based ONLY on the following textbook context.
    
    Context:
    {context}
    
    Requirements:
    - Questions must be directly answerable from the text provided.
    - Difficulty Level: {difficulty}
    - Question Types: Mix of MCQ, Fill in the Blanks, and Short Answer.
    - If the context contains exercises or questions, prioritize converting them into interactive quiz format.
    
    Output Format (JSON):
    {{
        "questions": [
            {{
                "qid": "q1",
                "question": "...",
                "question_type": "MCQ",
                "options": [{{"key": "a", "description": "..."}}],
                "correct": ["a"],
                "hint": "...",
                "explanation": "..."
            }}
        ]
    }}
    """
