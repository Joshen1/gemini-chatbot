import os
import time
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# LangChain Imports
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Load environment variables
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError(f"Error: GEMINI_API_KEY not found. Checked {dotenv_path}")

# Initialize LLM & Embeddings using LangChain
# Note: LangChain automatically picks up GEMINI_API_KEY from environment variables
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=GEMINI_API_KEY,
)

# Paths for documents
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
    if RAG_DEFAULT_DOC.exists() and any(RAG_DEFAULT_DOC.glob("*.txt")):
        return RAG_DEFAULT_DOC
    if RAG_DEFAULT_FILE.exists():
        return RAG_DEFAULT_FILE
    return None

def load_and_chunk_documents(path: Path | None) -> list[Document]:
    if not path:
        print("No RAG document path configured. Continuing without vector store.")
        return []

    # Gather document paths
    paths = [path] if path.is_file() else []
    if path.is_dir():
        for ext in ["*.txt", "*.md"]:
            paths.extend(sorted(path.glob(ext)))

    if not paths:
        return []

    # Initialize LangChain's smart text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,       # Characters, not words (preferred for embeddings)
        chunk_overlap=200,
        length_function=len,
    )

    documents = []
    for doc_path in paths:
        try:
            content = doc_path.read_text(encoding="utf-8")
            # Create LangChain Document structures with metadata tracking
            chunks = text_splitter.split_text(content)
            for chunk in chunks:
                documents.append(Document(page_content=chunk, metadata={"source": doc_path.name}))
        except Exception as e:
            print(f"Unable to read document {doc_path}: {e}")

    print(f"Loaded and split into {len(documents)} context chunks.")
    return documents

# Initialize Vector Database (ChromaDB)
document_source_path = resolve_rag_path()
raw_docs = load_and_chunk_documents(document_source_path)

vector_store = None
if raw_docs:
    try:
        # Creates an in-memory Chroma instance. For persistence, add persist_directory="./chroma_db"
        vector_store = Chroma.from_documents(raw_docs, embeddings)
        print("ChromaDB Vector Store successfully built and indexed.")
    except Exception as exc:
        print(f"Warning: ChromaDB initialization failed: {exc}")
        vector_store = None

# FastAPI App Initialization
app = FastAPI(title="Clarilux Chatbot")

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

class ChatMessage(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

def build_rag_prompt(query: str, retrieved_docs: list[Document]) -> str:
    prompt_parts = [
        "You are a helpful assistant. Use the provided document context when it is relevant to answer the question.\n",
        "If the answer cannot be found in the context, use your general knowledge, but maintain historical accuracy.\n",
        "\nDocument context:\n"
    ]
    for i, doc in enumerate(retrieved_docs, start=1):
        source = doc.metadata.get("source", "Unknown")
        prompt_parts.append(f"Excerpt {i} ({source}):\n{doc.page_content}\n---\n")
    
    prompt_parts.append(f"\nUser Question: {query}\nAnswer:")
    return "".join(prompt_parts)

@app.get("/")
async def get_homepage():
    return FileResponse(static_dir / "index.html")

@app.post("/api/chat")
async def chat_endpoint(chat_msg: ChatMessage):
    if not chat_msg.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    try:
        # Step 1: Check vector store and retrieve relevant context semantically
        context_docs = []
        if vector_store:
            # Performs a mathematical Cosine/L2 Similarity search
            context_docs = vector_store.similarity_search(chat_msg.message, k=3)

        # Step 2: Formulate dynamic prompt based on presence of context
        if context_docs:
            final_prompt = build_rag_prompt(chat_msg.message, context_docs)
        else:
            final_prompt = chat_msg.message

        # Step 3: Invoke the LangChain LLM engine
        ai_message = llm.invoke(final_prompt)
        
        return ChatResponse(response=ai_message.content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing RAG Pipeline request: {str(e)}")

@app.post("/api/reset")
async def reset_chat():
    # LangChain ChatGoogleGenAI handles stateless invocation directly via its interface
    return {"status": "LangChain session state cleared"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)