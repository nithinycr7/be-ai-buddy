
import asyncio
import logging
import time
import json
import base64
from azure.storage.queue import QueueClient, BinaryBase64DecodePolicy
from dotenv import load_dotenv

# App imports
from app.core.config import settings
from app.db.mongo import get_client as get_mongo_client
from app.services.summary_service import SummaryService

# ----------------------------------------------------------------------
# Setup Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [Summary-Worker] - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Worker Logic
# ----------------------------------------------------------------------
async def main():
    logger.info("Spinning up Summary Worker...")
    
    # 1. Connect to Dependencies
    mongo_client = get_mongo_client()
    
    try:
        queue_client = QueueClient.from_connection_string(
            conn_str=settings.AZURE_STORAGE_CONNECTION_STRING,
            queue_name=settings.SUMMARY_QUEUE_NAME,
            message_decode_policy=BinaryBase64DecodePolicy()
        )
    except Exception as e:
        logger.critical(f"Failed to connect to Azure Queue: {e}")
        return

    summary_service = SummaryService(mongo_client)
    
    logger.info(f"Listening to queue: {settings.SUMMARY_QUEUE_NAME}")
    
    while True:
        try:
            # Poll Messages
            messages = queue_client.receive_messages(messages_per_page=1, visibility_timeout=60)
            
            for msg in messages:
                try:
                    # 2. Parse Message
                    content = msg.content if isinstance(msg.content, str) else msg.content.decode("utf-8")
                    
                    data = {}
                    try: 
                        data = json.loads(content) 
                    except: 
                        # If raw string (legacy), assume it's the ID
                        data = {"transcript": content}

                    transcript_id = data.get("transcript")
                    
                    if msg.dequeue_count > 5:
                        logger.error(f"POISON QUEUE: Message {msg.id} exceeded dequeue limit ({msg.dequeue_count}). Moving to {settings.SUMMARY_POISON_QUEUE_NAME}.")
                        
                        # Move to Poison Queue
                        try:
                            poison_q = QueueClient.from_connection_string(
                                conn_str=settings.AZURE_STORAGE_CONNECTION_STRING,
                                queue_name=settings.SUMMARY_POISON_QUEUE_NAME
                            )
                            # Create if not exists (lazy create)
                            try: poison_q.create_queue() 
                            except: pass
                            
                            poison_q.send_message(content)
                            queue_client.delete_message(msg)
                        except Exception as e:
                            logger.critical(f"FAILED TO MOVE TO POISON QUEUE: {e}")
                        
                        continue

                    if not transcript_id:
                        logger.error(f"Invalid Message Content: {content}")
                        queue_client.delete_message(msg)
                        continue

                    logger.info(f"Processing Transcript ID: {transcript_id}")

                    # 3. Generate Summary
                    success = await summary_service.generate_summary(transcript_id)
                    
                    if success:
                        queue_client.delete_message(msg)
                        logger.info(f"✅ Summary generated & message deleted for {transcript_id}")
                    else:
                        logger.warning(f"Failed to generate summary for {transcript_id}. Retrying later.")
                        # Let visibility timeout handle retry
                
                except Exception as e:
                    logger.error(f"Error processing message {msg.id}: {e}", exc_info=True)
            
            # Sleep to prevent tight loop if empty
            time.sleep(1) # Or use adaptive backoff
            
        except Exception as e:
            logger.error(f"Worker Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
