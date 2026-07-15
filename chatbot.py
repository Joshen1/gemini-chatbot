import os
import re
import base64
import hashlib
import shutil
import socket
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List

# LangChain Imports
import groq
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_core.messages import SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Load environment variables
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

GROQ_API_KEY = (
    os.getenv("GROQ_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("CHATBOT_API_KEY")
    or os.getenv("Chatbot Api Key")
)
if not GROQ_API_KEY:
    raise ValueError(f"Error: GROQ_API_KEY not found. Checked {dotenv_path}")

# Runtime tuning for RAG responses
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "700"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "7000"))
CHROMA_PERSIST_DIR = Path(__file__).resolve().parent / "chroma_db"
GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "compound-beta-mini")
GROQ_EMBEDDING_MODEL = os.getenv("GROQ_EMBEDDING_MODEL", "text-embedding-3-small")

os.environ["GROQ_API_KEY"] = GROQ_API_KEY

print("Groq runtime configuration:")
print("  GROQ_API_KEY loaded:", bool(GROQ_API_KEY))
print("  GROQ_MODEL:", GROQ_MODEL)
print("  GROQ_FALLBACK_MODEL:", GROQ_FALLBACK_MODEL)
print("  GROQ_EMBEDDING_MODEL:", GROQ_EMBEDDING_MODEL)

# Initialize Groq client and embeddings
class GroqEmbeddings(Embeddings):
    def __init__(self, client: groq.Groq, model: str = "text-embedding-3-small"):
        self.client = client
        self.model = model
        self.dimension = 256

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        candidate_models = []
        if self.model:
            candidate_models.append(self.model)
        candidate_models.extend([
            "text-embedding-3-small",
            "text-embedding-3-large",
            "nomic-embed-text-v1_5",
        ])

        last_exc = None
        for candidate_model in dict.fromkeys(candidate_models):
            try:
                response = self.client.embeddings.create(
                    input=texts,
                    model=candidate_model,
                    encoding_format="float",
                )
                return [self._normalize_embedding(item.embedding) for item in response.data]
            except Exception as exc:
                last_exc = exc
                error_text = str(exc).lower()
                print(f"Groq embedding call failed for model {candidate_model}: {exc}")

                if getattr(exc, 'status_code', None) == 401 or 'invalid_api_key' in error_text:
                    print("Detected invalid Groq API key during embedding. Falling back to local embeddings.")
                    break

                if 'does not exist' in error_text or 'model_not_found' in error_text:
                    continue

                if 'request entity too large' in error_text or 'request_too_large' in error_text:
                    print("Embedding request too large for Groq; using local embeddings.")
                    break

        print(f"Groq embedding call failed, using local fallback: {last_exc}")
        return [self._fallback_embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @staticmethod
    def _normalize_embedding(embedding):
        if isinstance(embedding, str):
            return [float(x) for x in embedding.split()]
        return list(embedding)

    def _fallback_embed_text(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        vector = [0.0] * self.dimension
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.dimension
            vector[index] += 1.0

        magnitude = sum(value * value for value in vector) ** 0.5
        if magnitude:
            vector = [value / magnitude for value in vector]
        return vector


def create_groq_client(api_key: str) -> groq.Groq:
    print(f"Initializing Groq client")
    return groq.Groq(api_key=api_key)


def create_groq_prompt(messages: list[dict]) -> str:
    return messages


groq_client = create_groq_client(GROQ_API_KEY)
embeddings = GroqEmbeddings(groq_client, model=GROQ_EMBEDDING_MODEL)

# Paths configuration
RAG_DOCUMENT_PATH = os.getenv("RAG_DOCUMENT_PATH", "")
RAG_DEFAULT_DOC = Path(__file__).resolve().parent / "docs"
RAG_DEFAULT_FILE = Path(__file__).resolve().parent / "document.txt"
IMAGE_ASSET_CANDIDATES = [
    Path(__file__).resolve().parent / "docs" / "screenshots",
    Path(__file__).resolve().parent / "docs" / "assets" / "screenshots",
    Path(__file__).resolve().parent / "assets" / "screenshots",
]
IMAGE_ASSETS_DIR = next((path for path in IMAGE_ASSET_CANDIDATES if path.exists()), IMAGE_ASSET_CANDIDATES[0])
IMAGE_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

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

def extract_image_references(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in [r"\[image:\s*([^\]]+)\]", r"!\[[^\]]*\]\(([^)]+)\)"]:
        refs.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return [ref.strip().strip('"\'') for ref in refs if ref]


def resolve_associated_image(image_reference: str, doc_path: Path) -> Path | None:
    if not image_reference:
        return None

    candidates = []
    raw_path = Path(image_reference)
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.extend([
            raw_path,
            doc_path.parent / raw_path,
            Path(__file__).resolve().parent / "docs" / raw_path,
            IMAGE_ASSETS_DIR / raw_path,
            IMAGE_ASSETS_DIR / raw_path.name,
        ])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_and_chunk_documents(path: Path | None) -> list[Document]:
    if not path:
        print("No RAG document path configured. Continuing without vector store.")
        return []

    paths = [path] if path.is_file() else []
    if path.is_dir():
        for ext in ["*.txt", "*.md"]:
            paths.extend(sorted(path.rglob(ext)))

    if not paths:
        return []

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=RAG_CHUNK_SIZE,
        chunk_overlap=RAG_CHUNK_OVERLAP,
        length_function=len,
    )

    documents = []

    for doc_path in paths:
        try:
            content = doc_path.read_text(encoding="utf-8")
            chunks = text_splitter.split_text(content)

            for chunk in chunks:
                image_refs = extract_image_references(chunk)
                image_file = None
                if image_refs:
                    resolved_image = resolve_associated_image(image_refs[0], doc_path)
                    if resolved_image:
                        image_file = resolved_image.name

                clean_content = re.sub(r"\[image:\s*([^\]]+)\]", "", chunk, flags=re.IGNORECASE)
                clean_content = re.sub(r"!\[[^\]]*\]\(([^)]+)\)", "", clean_content).strip()

                metadata = {"source": doc_path.name, "doc_path": str(doc_path)}
                if image_file:
                    metadata["associated_image"] = image_file

                documents.append(Document(page_content=clean_content, metadata=metadata))
        except Exception as e:
            print(f"Unable to read document {doc_path}: {e}")

    print(f"Loaded and split into {len(documents)} context chunks.")
    return documents


def initialize_vector_store(documents: list[Document]):
    if not documents:
        return None

    if CHROMA_PERSIST_DIR.exists():
        shutil.rmtree(CHROMA_PERSIST_DIR, ignore_errors=True)
    CHROMA_PERSIST_DIR.mkdir(exist_ok=True)

    try:
        store = Chroma.from_documents(
            documents,
            embeddings,
            persist_directory=str(CHROMA_PERSIST_DIR),
        )
        print("ChromaDB Vector Store successfully rebuilt and indexed.")
        return store
    except Exception as exc:
        print(f"Warning: ChromaDB initialization failed: {exc}")
        return None

# Initialize Vector Database (ChromaDB)
document_source_path = resolve_rag_path()
raw_docs = load_and_chunk_documents(document_source_path)
vector_store = initialize_vector_store(raw_docs)

# FastAPI App Initialization
app = FastAPI(title="Clarilux Multimodal Chatbot")

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Mount screenshot directory so your UI can load them natively via static URLs
app.mount("/screenshots", StaticFiles(directory=IMAGE_ASSETS_DIR), name="screenshots")

class ChatMessage(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    images: List[str]  # Returns URLs of images matching the steps

def get_image_base64_and_mime(image_path: Path) -> tuple[str, str]:
    """Helper to convert local images to multimodal payload formats."""
    ext = image_path.suffix.lower()
    mime_type = "image/png" if ext == ".png" else "image/jpeg"
    with open(image_path, "rb") as img_file:
        encoded_string = base64.b64encode(img_file.read()).decode("utf-8")
    return encoded_string, mime_type


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def build_chat_prompt(question: str, context_docs: list[Document]) -> tuple[list[dict], list[str]]:
    text_contexts = []
    ui_image_urls = []
    
    system_instruction_text = (
        "You are an assistant for the Clarilux platform. Answer the question using the retrieved context.\n"
        "CRITICAL: Be orderly. If the user asks about a specific step, focus your explanation on that step.\n"
        "If an associated screenshot is explicitly mentioned in the context, reference it naturally."
    )

    # Track unique images to prevent duplicates while maintaining retrieval rank order
    seen_images = set()

    for i, doc in enumerate(context_docs[: max(1, min(RAG_TOP_K, 6))], start=1):
        source = doc.metadata.get("source", "Unknown")
        content = doc.page_content.strip().replace("\n", " ")
        content = truncate_text(content, 900)
        
        image_name = doc.metadata.get("associated_image")
        image_log_str = ""
        
        # Pull image assets strictly mapped to high-relevance ranking contexts without bleeding duplicates
        if image_name and image_name not in seen_images:
            doc_path_str = doc.metadata.get("doc_path")
            doc_path = Path(doc_path_str) if doc_path_str else Path(doc.metadata.get("source", ""))
            full_image_path = resolve_associated_image(image_name, doc_path)
            
            if full_image_path and full_image_path.exists():
                img_url = f"/screenshots/{full_image_path.name}"
                ui_image_urls.append(img_url)
                seen_images.add(image_name)
                # Attach structural tracking text tags back into context to direct LLM narrative flow
                image_log_str = f" (Attached Screenshot: {full_image_path.name})"

        text_contexts.append(f"[{i}] From {source}:\n{content}{image_log_str}\n")

    combined_text_context = "\n".join(text_contexts).strip()
    prompt = f"Question: {question}\n\nRetrieved Context Documents:\n{combined_text_context}\n"
    
    if ui_image_urls:
        prompt += "\nAssociated screenshots available to show user:\n"
        prompt += "\n".join(ui_image_urls[:5])

    prompt = truncate_text(prompt, MAX_PROMPT_CHARS)
    messages = [
        {"role": "system", "content": system_instruction_text},
        {"role": "user", "content": prompt},
    ]
    
    return messages, ui_image_urls


def invoke_llm_with_fallback(messages: list[dict]):
    try:
        return call_groq_chat(messages, GROQ_MODEL)
    except Exception as exc:
        error_text = str(exc)
        print(f"LLM invocation failed: {error_text}")
        if GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL != GROQ_MODEL and (
            "RESOURCE_EXHAUSTED" in error_text.upper() or "quota" in error_text.lower() or "too large" in error_text.lower()
        ):
            print(f"Retrying with fallback Groq model: {GROQ_FALLBACK_MODEL}")
            return call_groq_chat(messages, GROQ_FALLBACK_MODEL)
        if getattr(exc, 'status_code', None) == 401 or 'invalid_api_key' in error_text.lower():
            print("Detected invalid Groq API key during chat completion.")
            return (
                "I’m unable to contact the Groq API because the configured API key is invalid. "
                "Please check your GROQ_API_KEY and try again."
            )
        raise


def call_groq_chat(messages: list[dict], model_name: str):
    response = groq_client.chat.completions.create(
        messages=messages,
        model=model_name,
        temperature=0.2,
        max_tokens=600,
    )
    if not getattr(response, 'choices', None):
        raise ValueError('Groq response contains no choices')
    choice = response.choices[0]
    content = getattr(choice.message, 'content', None)
    return content if content is not None else ''


@app.get("/")
async def get_homepage():
    return FileResponse(static_dir / "index.html")

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(chat_msg: ChatMessage):
    global vector_store

    if not chat_msg.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    try:
        context_docs = []

        if vector_store:
            try:
                context_docs = vector_store.similarity_search(chat_msg.message, k=RAG_TOP_K)
            except Exception as exc:
                print(f"Vector store query failed: {exc}")
                error_text = str(exc).lower()
                if "collection" in error_text and "does not exist" in error_text:
                    print("Detected missing Chroma collection. Rebuilding vector store...")
                    rebuilt_store = initialize_vector_store(raw_docs)
                    if rebuilt_store:
                        vector_store = rebuilt_store
                        try:
                            context_docs = vector_store.similarity_search(chat_msg.message, k=RAG_TOP_K)
                        except Exception as exc2:
                            print(f"Vector store query failed after rebuild: {exc2}")
                            context_docs = []
                    else:
                        print("Failed to rebuild vector store after missing collection.")
                        context_docs = []
                else:
                    raise

        messages, ui_image_urls = build_chat_prompt(chat_msg.message, context_docs)
        ai_content = invoke_llm_with_fallback(messages)

        return ChatResponse(
            response=ai_content,
            images=ui_image_urls  # Cleanly preserved in order of top RAG relevance score metrics
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing Multimodal RAG request: {str(e)}")

@app.post("/api/reset")
async def reset_chat():
    return {"status": "Multimodal session state cleared"}

if __name__ == "__main__":
    import uvicorn

    def is_port_available(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return True
            except OSError:
                return False

    host = "0.0.0.0"
    port = int(os.getenv("PORT", "8080"))

    if not is_port_available(host, port):
        print(f"Port {port} is already in use. Searching for a free port...")
        for candidate in range(port + 1, port + 11):
            if is_port_available(host, candidate):
                port = candidate
                print(f"Using fallback port {port}")
                break
        else:
            raise SystemExit(f"Unable to bind to any port from {port} to {port + 10}.")

    uvicorn.run(app, host=host, port=port)