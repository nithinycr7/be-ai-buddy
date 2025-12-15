
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def debug_ncert_data():
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DB_NAME", "mymedha_dev") # Defaulting to mymedha_dev based on previous context
    collection_name = os.getenv("NCERT_COLLECTION_NAME", "ncert_topics")

    print(f"Connecting to URI: {uri}")
    print(f"Database: {db_name}")
    print(f"Collection: {collection_name}")

    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    collection = db[collection_name]

    # 1. Count documents
    count = await collection.count_documents({})
    print(f"Total documents in {collection_name}: {count}")

    if count == 0:
        print("Collection is empty!")
        return

    # 2. Print sample documents
    print("\nSample Documents:")
    async for doc in collection.find().limit(3):
        print(doc)

    # 3. Check for distinct subjects
    print("\nDistinct Subjects:")
    subjects = await collection.distinct("subject")
    print(subjects)

    # 4. Check for Class 6 specific query
    print("\nChecking for Class 6 (string '6'):")
    count_str = await collection.count_documents({"class_no": "6"})
    print(f"Docs with class_no='6': {count_str}")

    print("\nChecking for Class 6 (int 6):")
    count_int = await collection.count_documents({"class_no": 6})
    print(f"Docs with class_no=6: {count_int}")
    
    # 5. Check distinct class_no
    distinct_classes = await collection.distinct("class_no")
    print(f"Distinct class_no values: {distinct_classes}")


if __name__ == "__main__":
    asyncio.run(debug_ncert_data())
