from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    provider: str = "auto"   # "auto" | "groq" | "ollama" | "rag_only"
    model: str = ""


class ComplaintLookupRequest(BaseModel):
    complaint_id: str = Field(..., min_length=1, max_length=64)


class ComplaintFileRequest(BaseModel):
    crime_type: str = Field(..., min_length=2, max_length=120)
    description: str = Field("", max_length=2000)
    location: str = Field("", max_length=200)
    complainant_name: str = Field("", max_length=120)
    contact: str = Field("", max_length=40)
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(..., ge=-1, le=1)
    comment: str = Field("", max_length=500)
