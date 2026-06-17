import os
import time
import google.genai as genai
from google.genai import errors as genai_errors
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

# Load environment variables from .env file in the project root
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

# Configure the Gemini API from the key in the .env file
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    print(f"Error: GEMINI_API_KEY not found. Checked {dotenv_path}")
    exit(1)

try:
    client = genai.Client(api_key=gemini_api_key)
except Exception as e:
    print(f"Error creating Gemini client: {e}")
    exit(1)

# Creating a chat session with no chat or history
chat = client.chats.create(model="gemini-3-flash-preview")

# Optional RAG support: load documents from disk and use them as context for answers
RAG_DOCUMENT_PATH = os.getenv("RAG_DOCUMENT_PATH", "")
RAG_DEFAULT_DOC = Path(__file__).resolve().parent / "docs"
RAG_DEFAULT_FILE = Path(__file__).resolve().parent / "document.txt"


def resolve_rag_path() -> Path | None:
    if RAG_DOCUMENT_PATH:
        path = Path(RAG_DOCUMENT_PATH).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if path.exists():
            return path
        print(f"RAG_DOCUMENT_PATH does not exist: {path}")
    if RAG_DEFAULT_DOC.exists() and any(RAG_DEFAULT_DOC.glob("*.txt")):
        return RAG_DEFAULT_DOC
    if RAG_DEFAULT_FILE.exists():
        return RAG_DEFAULT_FILE
    return None


def read_document_text(path: Path) -> str:
    # Support plain text and PDF extraction (requires PyPDF2)
    if path.suffix.lower() == ".pdf":
        try:
            import PyPDF2
        except Exception:
            print("PyPDF2 not installed; install with 'pip install PyPDF2' to enable PDF support.")
            return ""
        try:
            text_parts: list[str] = []
            with path.open("rb") as fh:
                reader = PyPDF2.PdfReader(fh)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        except Exception as e:
            print(f"Failed to extract text from PDF {path}: {e}")
            return ""

    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Unable to read document {path}: {e}")
        return ""


def list_document_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        files: list[Path] = []
        for ext in ["*.txt", "*.md", "*.pdf"]:
            files.extend(sorted(path.glob(ext)))
        return files
    return []


def chunk_document_text(text: str, chunk_size: int = 250, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def load_document_chunks(path: Path | None) -> list[tuple[str, str]]:
    if path is None:
        print("No RAG document path configured. Continuing without document retrieval.")
        return []

    paths = list_document_paths(path)
    if not paths:
        print(f"No documents found at {path}. Continuing without document retrieval.")
        return []

    chunks: list[tuple[str, str]] = []
    for document_path in paths:
        content = read_document_text(document_path)
        for chunk in chunk_document_text(content):
            chunks.append((document_path.name, chunk))

    print(f"Loaded {len(chunks)} document chunks from {path}")
    return chunks


def score_chunk(query: str, chunk_text: str) -> int:
    query_words = set(query.lower().split())
    chunk_words = set(chunk_text.lower().split())
    return len(query_words & chunk_words)


def retrieve_relevant_chunks(query: str, chunks: list[tuple[str, str]], top_k: int = 3) -> list[tuple[str, str]]:
    scored = [
        (score_chunk(query, chunk_text), source_name, chunk_text)
        for source_name, chunk_text in chunks
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        (source_name, chunk_text)
        for score, source_name, chunk_text in scored
        if score > 0
    ][:top_k]


def build_rag_prompt(query: str, context_chunks: list[tuple[str, str]]) -> str:
    prompt_parts = [
        "You are a helpful assistant. Use the provided document context when it is relevant to answer the question. ",
        "If the answer is outside the scope of the document, answer based on general knowledge rather than inventing facts.",
        "\n\nDocument excerpts:\n"
    ]
    for i, (source_name, chunk) in enumerate(context_chunks, start=1):
        prompt_parts.append(f"Excerpt {i} ({source_name}): {chunk}\n")
    prompt_parts.append(f"\nQuestion: {query}\nAnswer:")
    return "".join(prompt_parts)


def is_rag_fallback_response(text: str) -> bool:
    if not text:
        return False
    normalized = text.lower()
    return (
        "does not contain any information" in normalized
        or "not contained in the document" in normalized
        or "i don't know" in normalized
        or "no information regarding" in normalized
        or "cannot find" in normalized
        or "unable to answer" in normalized
    )


# Load document chunks if a document is configured
document_source_path = resolve_rag_path()
document_chunks = load_document_chunks(document_source_path)

# FastAPI app initialization
app = FastAPI(title="Clarilux Chatbot")

# Mount static files directory
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Request and Response models
class ChatMessage(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str


def format_chat_response(response) -> str:
    """Convert Gemini response content into plain text."""
    if not response or not response.candidates:
        return ""
    content = response.candidates[0].content
    if not content or not getattr(content, "parts", None):
        return ""

    text_parts = []
    for part in content.parts:
        part_text = getattr(part, "text", None)
        if part_text:
            text_parts.append(part_text)
    return "".join(text_parts)


def send_chat_message_with_retries(message: str, max_retries: int = 3, backoff_seconds: int = 2):
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return chat.send_message(message)
        except genai_errors.APIError as e:
            last_exception = e
            if e.code == 503 and attempt < max_retries:
                time.sleep(backoff_seconds * attempt)
                continue
            raise
        except genai_errors.ServerError as e:
            last_exception = e
            if attempt < max_retries:
                time.sleep(backoff_seconds * attempt)
                continue
            raise
    if last_exception:
        raise last_exception

@app.get("/")
async def get_homepage():
    """Serve the homepage"""
    return FileResponse(static_dir / "index.html")

@app.post("/api/chat")
async def chat_endpoint(chat_msg: ChatMessage):
    """Chat endpoint that receives user message and returns chatbot response"""
    if not chat_msg.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    try:
        if document_chunks:
            relevant_chunks = retrieve_relevant_chunks(chat_msg.message, document_chunks)
            if relevant_chunks:
                rag_prompt = build_rag_prompt(chat_msg.message, relevant_chunks)
                response = send_chat_message_with_retries(rag_prompt)
                full_response = format_chat_response(response)
                if is_rag_fallback_response(full_response):
                    response = send_chat_message_with_retries(chat_msg.message)
                else:
                    return ChatResponse(response=full_response)
            else:
                response = send_chat_message_with_retries(chat_msg.message)
        else:
            response = send_chat_message_with_retries(chat_msg.message)

        full_response = format_chat_response(response)
        return ChatResponse(response=full_response)
    except genai_errors.APIError as e:
        if e.code == 503:
            raise HTTPException(
                status_code=503,
                detail="Gemini model is experiencing high demand. Please try again in a few seconds.",
            )
        raise HTTPException(status_code=500, detail=f"Gemini API error: {e}")
    except genai_errors.ServerError:
        raise HTTPException(
            status_code=503,
            detail="The Gemini service is temporarily unavailable. Please retry shortly.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error occurred: {str(e)}")

@app.post("/api/reset")
async def reset_chat():
    """Reset the chat session"""
    global chat
    chat = client.chats.create(model="gemini-3-flash-preview")
    return {"status": "Chat session reset"}

# CLI mode for backward compatibility
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        # Run in CLI mode (original behavior)
        print("Gemini chatbot is ready! We are using Gemini 3 Flash Preview model, type 'exit' to quit.")
        print("="*50)
        
        while True:
            user_input = input("You: ")
            
            if not user_input.strip():
                print("Please enter a message.")
                continue
            
            if user_input.lower() == "exit":
                print("Goodbye thank you for chatting with Gemini 3 Flash Preview!")
                break
            
            try:
                response = chat.send_message(user_input)
                print("Gemini:", format_chat_response(response))
            except Exception as e:
                print(f"Gemini has an error occur while getting a response: {e}\n")
    else:
        # Run FastAPI server
        import uvicorn
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run(app, host="0.0.0.0", port=port)
    