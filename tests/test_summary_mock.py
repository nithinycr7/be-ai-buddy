
import asyncio
import os
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

# Mock Environment before imports
os.environ["MONGODB_URI"] = "mongodb://mock"
os.environ["AZURE_OPENAI_API_KEY"] = "mock"
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://mock.openai.azure.com"

# Import Code to Test
from app.services.summary_service import SummaryService

async def test_summary_logic():
    print("🧪 Starting Summary Service Test...")
    
    # 1. Mock DB Client
    mock_client = AsyncMock()
    mock_db_backend = AsyncMock()
    mock_db_transcripts = AsyncMock()
    
    # Configure client to return specific mocks for specific DB names
    def get_db(name):
        if name == "mymedha_dev": return mock_db_transcripts
        return mock_db_backend
    
    mock_client.__getitem__.side_effect = get_db
    
    # 2. Setup Mock Data
    service = SummaryService(mock_client)
    
    # Mock Transcript Trigger
    transcript_id = "trigger_123"
    mock_trigger_doc = {
        "_id": transcript_id,
        "schoolId": "school_1",
        "classId": "7",
        "subject": "Science",
        "timestamp": datetime.now().timestamp(),
        "transcript_text": "Today we are learning about light and reflection."
    }
    
    # Mock Related Transcripts Search
    service.transcripts_db.daily_transcripts.find_one.return_value = mock_trigger_doc
    
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        mock_trigger_doc, 
        {"_id": "other_1", "transcript_text": "Reflection is when light bounces back."}
    ]
    # IMPORTANT: find() is synchronous in Motor, returns an AsyncCursor. 
    # So we must use MagicMock, not AsyncMock, for find itself.
    service.transcripts_db.daily_transcripts.find = MagicMock(return_value=mock_cursor)
    
    # Mock LLM calls (Topic Identification & Summary Generation)
    # We need to mock the internal methods or the OpenAI client.
    # For unit testing logic flow, mocking internal helpers is easier if we don't want to spin up full OpenAI mock.
    
    service._identify_topic = AsyncMock(return_value={"chapter": "Light", "topic": "Reflection"})
    service._fetch_ncert_context = AsyncMock(return_value="NCERT Context: Light travels in straight lines.")
    service._generate_llm_summary = AsyncMock(return_value="**Class Summary**: The class covered Reflection of Light.")
    
    # 3. Run Test
    print(f"▶️ Triggering generation for {transcript_id}...")
    result = await service.generate_summary(transcript_id)
    
    # 4. Assertions
    if result:
        print("✅ SUCCESS: generate_summary returned True")
    else:
        print("❌ FAILURE: generate_summary returned False")
        
    # Verify Aggregation Query
    service.transcripts_db.daily_transcripts.find.assert_called()
    print("✅ Verified: Aggregated transcripts query executed")
    
    # Verify Save
    service.summary_collection.update_one.assert_called()
    print("✅ Verified: Summary saved to DB")
    
    print("Done.")

if __name__ == "__main__":
    asyncio.run(test_summary_logic())
