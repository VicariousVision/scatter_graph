from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
class QuestionRequest(BaseModel):
    question: str
@app.post("/ask")
def ask_question(req: QuestionRequest):
    result = qa_chain.run(req.question)
    return {"answer": result}