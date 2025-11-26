# MyMedha LXP - Backend API

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python)](https://www.python.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-CosmosDB-47A248?logo=mongodb)](https://www.mongodb.com/)

FastAPI backend service providing AI-powered educational APIs for the MyMedha Learning Experience Platform.

## 🎯 Overview

This backend provides RESTful APIs for:
- **Daily Classes**: Manage class schedules and content
- **Progress Tracking**: Student learning progress and completion
- **Quiz System**: Quiz delivery, submission, and scoring
- **AI Story Generation**: Personalized learning stories via OpenAI
- **Multi-tenancy**: Isolated data per school/organization

## 🚀 Features

### Core APIs
- ✅ **Classes API**: CRUD operations for daily classes
- ✅ **Quiz API**: Quiz retrieval, submission, best score tracking
- ✅ **Progress API**: Activity tracking, completion calculation
- ✅ **AI Integration**: OpenAI-powered story generation
- ✅ **Multi-tenancy**: Tenant isolation via headers

### Technical Features
- ✅ **FastAPI**: High-performance async framework
- ✅ **MongoDB**: CosmosDB with MongoDB API
- ✅ **Pydantic**: Data validation and serialization
- ✅ **CORS**: Configured for frontend integration
- ✅ **API Key Auth**: Simple authentication
- ✅ **OpenAPI Docs**: Auto-generated at `/docs`

## 📦 Tech Stack

- **Framework**: FastAPI 0.115.0
- **Database**: MongoDB (Azure CosmosDB)
- **ODM**: Motor (async MongoDB driver)
- **Validation**: Pydantic v2
- **AI**: OpenAI GPT-4
- **Server**: Uvicorn (ASGI server)

## 🏗️ Project Structure

```
ed-ai-backend/
├── app/
│   ├── core/
│   │   ├── config.py          # Configuration & settings
│   │   ├── database.py        # MongoDB connection
│   │   └── security.py        # Authentication & tenant handling
│   ├── models/
│   │   └── schemas.py         # Pydantic models
│   ├── routers/
│   │   ├── classes.py         # Classes API endpoints
│   │   ├── quiz.py            # Quiz API endpoints
│   │   ├── progress.py        # Progress tracking endpoints
│   │   └── ai.py              # AI story generation
│   └── main.py                # FastAPI application
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- MongoDB or Azure CosmosDB account
- OpenAI API key (for AI features)

### Installation

```bash
# Clone repository
git clone https://dev.azure.com/nithinyakateela0185/MyMedhaAI/_git/mymedha-lxp-be
cd mymedha-lxp-be/ed-ai-backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your configuration

# Run server
uvicorn app.main:app --reload
```

### Environment Variables

Create `.env` file:

```env
# MongoDB
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB=aibuddy-dev

# For Azure CosmosDB:
# MONGODB_URI=mongodb://your-cosmos:...@your-cosmos.mongo.cosmos.azure.com:10255/?ssl=true

# Security
API_KEY_VALUE=dev-local-key

# AI Services
OPENAI_API_KEY=sk-...

# Server
HOST=0.0.0.0
PORT=8000
```

## 📚 API Documentation

### Interactive Docs

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Quick API Overview

#### Classes
```http
GET    /api/classes/daily?date={YYYY-MM-DD}    # List classes
GET    /api/classes/daily/{id}                  # Get single class
POST   /api/classes/daily                       # Create class
```

#### Quiz
```http
GET    /api/quiz/{daily_id}                     # Get quiz
POST   /api/quiz/submit                         # Submit answers
GET    /api/quiz/responses/{daily_id}           # Get attempts
```

#### Progress
```http
POST   /api/progress/track                      # Track activity
GET    /api/progress                            # Get progress
GET    /api/progress/weekly                     # Weekly summary
```

#### AI
```http
POST   /api/ai/story?daily_id={id}&student_id={id}  # Generate story
```

### Authentication

All requests require headers:

```http
x-api-key: dev-local-key
X-Tenant-ID: demo-school
```

## 🗄️ Database Schema

### Collections

1. **classes_daily**: Daily class records
2. **quizzes**: Quiz questions
3. **quiz_responses**: Student quiz attempts
4. **student_progress**: Progress tracking
5. **stories**: Generated AI stories
6. **students**: Student profiles

### Key Models

**DailyClass**:
```python
{
  "_id": ObjectId,
  "date": datetime,
  "class_no": int,
  "section": str,
  "subject": str,
  "topic": str,
  "summary": str,
  "tenant": str
}
```

**Quiz**:
```python
{
  "daily_id": str,
  "questions": [
    {
      "question_text": str,
      "options": [{"key": str, "description": str}],
      "correct_answer": str
    }
  ],
  "tenant": str
}
```

**StudentProgress**:
```python
{
  "student_id": str,
  "daily_id": str,
  "date": datetime,
  "summary_viewed": bool,
  "story_generated": bool,
  "quiz_best_score": float,
  "quiz_attempts": int,
  "completion_percentage": float,
  "is_completed": bool
}
```

## 🔧 Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest
```

### Code Style

```bash
# Install formatting tools
pip install black isort

# Format code
black app/
isort app/
```

### Database Setup

```bash
# For local MongoDB
mongod --dbpath ./data

# Import sample data
python populate_mock_data.py
```

## 📊 Progress Tracking Logic

**Completion Calculation**:

```python
completion_percentage = min(100, 
  (25 if summary_viewed else 0) +
  (25 if story_generated else 0) +
  (quiz_best_score * 0.5)
)

is_completed = completion_percentage >= 75
```

**Weights**:
- Summary Viewed: 25%
- Story Generated: 25%
- Quiz Performance: 50% (best score)
- **Threshold**: 75% for completion

## 🚢 Deployment

### Azure App Service

```bash
# Login to Azure
az login

# Deploy
az webapp up \
  --resource-group mymedha-ai-prod \
  --name mymedha-lxp-backend \
  --runtime "PYTHON:3.11"

# Set environment variables
az webapp config appsettings set \
  --resource-group mymedha-ai-prod \
  --name mymedha-lxp-backend \
  --settings \
    MONGODB_URI="..." \
    API_KEY_VALUE="..." \
    OPENAI_API_KEY="..."
```

**Production URL**: https://aibuddy-be-awb3eqfyftc7cbe6.canadacentral-01.azurewebsites.net

## 🐛 Troubleshooting

### Common Issues

**MongoDB Connection Failed**:
```bash
# Check connection string
# For CosmosDB, ensure you're using the MongoDB API connection string
# Include ?ssl=true for CosmosDB
```

**CORS Errors**:
```python
# Update app/main.py CORS settings
allow_origins=["https://your-frontend-url.com"]
```

**API Key Invalid**:
```bash
# Check x-api-key header matches API_KEY_VALUE in .env
```

## 📈 Performance

- **Async/Await**: All database operations are async
- **Connection Pooling**: Motor handles connection pooling
- **Response Caching**: Implement for read-heavy endpoints
- **Indexes**: Add MongoDB indexes for frequently queried fields

## 🔐 Security

- **API Key**: Simple authentication (replace with OAuth for production)
- **Tenant Isolation**: All queries filtered by tenant ID
- **Input Validation**: Pydantic validates all inputs
- **CORS**: Configured for specific origins
- **Environment Vars**: Secrets in environment variables

## 📝 API Examples

### Create a Class

```python
import requests

response = requests.post(
    "http://localhost:8000/api/classes/daily",
    headers={
        "x-api-key": "dev-local-key",
        "X-Tenant-ID": "demo-school"
    },
    json={
        "date": "2025-11-26",
        "class_no": 10,
        "section": "A",
        "subject": "Physics",
        "topic": "Newton's Laws",
        "summary": "Introduction to Newton's three laws..."
    }
)
```

### Submit Quiz

```python
response = requests.post(
    "http://localhost:8000/api/quiz/submit",
    headers={"x-api-key": "dev-local-key"},
    json={
        "student_id": "1245372",
        "daily_id": "507f1f77bcf86cd799439011",
        "responses": [
            {"question_index": 0, "selected_answer": "A"},
            {"question_index": 1, "selected_answer": "B"}
        ]
    }
)

print(f"Score: {response.json()['score']}%")
```

## 🔄 Future Enhancements

- [ ] WebSocket support for real-time updates
- [ ] Redis caching for improved performance
- [ ] Rate limiting per tenant
- [ ] OAuth2/JWT authentication
- [ ] GraphQL API option
- [ ] Automated testing suite
- [ ] API versioning (v1, v2)
- [ ] Comprehensive logging

## 📞 Support

- **Issues**: Create in Azure DevOps
- **Docs**: `/docs` endpoint for API reference
- **Contact**: dev@mymedha.ai

---

**Version**: 1.0.0  
**Last Updated**: November 2025  
**License**: Proprietary - MyMedha Education Technology
