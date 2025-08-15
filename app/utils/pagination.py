from fastapi import Query
from typing import Optional

def pagination_params(skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    return {"skip": skip, "limit": limit}
