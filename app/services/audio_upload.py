"""
Audio Upload Service for MyMedha LXP Backend

Handles uploading audio files to Azure Blob Storage and queuing them
for transcription processing.
"""

from azure.storage.blob import BlobServiceClient, BlobClient
from azure.storage.queue import QueueClient, TextBase64EncodePolicy
from fastapi import HTTPException
import json
import random
from datetime import datetime
from ..core.config import settings


class AudioUploadService:
    """Service for uploading audio files to Azure Blob Storage and queuing for processing"""
    
    def __init__(self):
        self.connection_string = None
        self.blob_service_client = None
        self.container_client = None
        self.queue_client = None
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize Azure Blob and Queue clients with optimized settings"""
        try:
            self.connection_string = settings.AZURE_STORAGE_CONNECTION_STRING
            
            if not self.connection_string:
                print("[AudioUpload] Warning: AZURE_STORAGE_CONNECTION_STRING not configured")
                return
            
            # Blob Service - optimized for large files and distant regions
            self.blob_service_client = BlobServiceClient.from_connection_string(
                self.connection_string,
                connection_timeout=120,  # 2 minutes connection timeout
                read_timeout=600,        # 10 minutes read timeout for large streams
                retry_total=5,           # Retry up to 5 times
                retry_backoff_factor=2   # Exponential backoff
            )
            
            # Get or create container
            container_name = settings.AUDIO_CONTAINER_NAME
            self.container_client = self.blob_service_client.get_container_client(container_name)
            
            if not self.container_client.exists():
                self.container_client.create_container()
                print(f"[AudioUpload] Created container: {container_name}")
            
            # Queue Service - with Base64 encoding for Azure Functions/Logic Apps
            queue_name = settings.AUDIO_QUEUE_NAME
            self.queue_client = QueueClient.from_connection_string(
                self.connection_string,
                queue_name,
                message_encode_policy=TextBase64EncodePolicy()
            )
            
            try:
                self.queue_client.create_queue()
                print(f"[AudioUpload] Created queue: {queue_name}")
            except Exception:
                # Queue likely already exists
                pass
                
            print(f"[AudioUpload] Initialized successfully")
            
        except Exception as e:
            print(f"[AudioUpload] Error initializing Azure services: {e}")
            self.blob_service_client = None
            self.container_client = None
            self.queue_client = None
    
    def _construct_filename(self, metadata: dict) -> tuple[str, str]:
        """
        Construct filename from metadata
        
        Returns:
            tuple: (filename, blob_path)
            
        Format: {Class}{Section}_{Subject}_{Topic}_{Timestamp}.webm
        Example: 10A_Math_Topic_1234567890.webm
        Path: SCH-123/10A_Math_Topic_1234567890.webm
        """
        # Extract metadata with defaults
        school_id = metadata.get('schoolId', 'SCH-123')
        selected_class = metadata.get('selectedClass', '10').replace(" ", "")
        selected_section = metadata.get('selectedSection', 'A').replace(" ", "")
        subject = metadata.get('selectedSubject', 'Subject').replace(" ", "")
        
        # Handle Topic: Accept both selectedTopic and selectedChapter for compatibility
        topic = metadata.get('selectedTopic') or metadata.get('selectedChapter', '')
        timestamp = int(datetime.now().timestamp())
        random_id = random.randint(1, 100)
        
        if not topic:
            topic_suffix = "_topic"
        else:
            topic_suffix = f"_{topic.replace(' ', '')}"
        
        # Construct filename
        filename = f"{selected_class}{selected_section}_{subject}{topic_suffix}_{timestamp}_{random_id}.webm"
        
        # Construct blob path (inside school folder)
        blob_path = f"{school_id}/{filename}"
        
        return filename, blob_path
    
    async def upload_audio(self, file_content: bytes, metadata: dict) -> dict:
        """
        Upload audio file to Azure Blob Storage and queue for processing
        
        Args:
            file_content: Audio file bytes
            metadata: Dictionary containing upload metadata
            
        Returns:
            dict: Upload result with success, url, and filename
            
        Raises:
            HTTPException: If upload or queue operation fails
        """
        if not self.blob_service_client or not self.container_client or not self.queue_client:
            raise HTTPException(
                status_code=500,
                detail="Audio upload service not configured. Check AZURE_STORAGE_CONNECTION_STRING."
            )
        
        try:
            # Construct filename and path
            filename, blob_path = self._construct_filename(metadata)
            
            # Upload to Azure Blob
            blob_client = self.container_client.get_blob_client(blob_path)
            blob_client.upload_blob(file_content, overwrite=True)
            
            blob_url = blob_client.url
            
            # Queue for transcription processing
            message = json.dumps({"url": blob_url})
            self.queue_client.send_message(message)
            
            print(f"[AudioUpload] Uploaded: {blob_path}")
            print(f"[AudioUpload] Queued: {message}")
            
            return {
                "success": True,
                "url": blob_url,
                "filename": blob_path
            }
            
        except Exception as e:
            print(f"[AudioUpload] Upload/Queue failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Audio upload failed: {str(e)}"
            )


# Singleton instance
audio_upload_service = AudioUploadService()
