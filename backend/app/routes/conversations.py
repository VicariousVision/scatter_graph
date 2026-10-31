from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["conversations"])


class NewConversation(BaseModel):
    title: Optional[str] = Field(None, max_length=120)


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.get("/conversations")
def list_conversations(request: Request) -> list[dict[str, Any]]:
    return request.app.state.chat.list_conversations()


@router.post("/conversations", status_code=201)
def create_conversation(request: Request, body: Optional[NewConversation] = None) -> dict[str, Any]:
    title = (body.title or "").strip() if body else ""
    return request.app.state.chat.create_conversation(title or None)


@router.get("/conversations/{conversation_id}")
def get_conversation(request: Request, conversation_id: str) -> dict[str, Any]:
    conversation = request.app.state.chat.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found.")
    return conversation


@router.post("/conversations/{conversation_id}/messages")
def send_message(request: Request, conversation_id: str, body: NewMessage) -> dict[str, Any]:
    """Answer a question from the knowledge graph, using the conversation as context."""
    question = body.content.strip()
    if not question:
        raise HTTPException(400, "The question is empty.")
    answer = request.app.state.chat.ask(conversation_id, question)
    if answer is None:
        raise HTTPException(404, "Conversation not found.")
    return answer
