# Clarilux Multimodal Chatbot

A FastAPI-based chatbot that combines Groq with a retrieval-augmented generation (RAG) pipeline, embeddings, and ChromaDB to answer questions from your documents and associated screenshots.

## What’s New

The current version includes:

- Embedding-based document retrieval with Groq embeddings
- ChromaDB persistence for vector search in the local `chroma_db` folder
- RAG chunking and similarity search over `.txt` and `.md` documents
- Multimodal responses that can return related screenshots from the docs folder
- Quota-aware fallback support for Groq model retries
- A simple web interface with REST API endpoints

## Features

- 🤖 Groq-powered chat responses
- 📚 RAG from your own documents and knowledge files
- 🧠 Vector search using embeddings and ChromaDB
- 🖼️ Image-aware answers when documents reference screenshots
- ⚡ FastAPI backend with a lightweight frontend
- 🔁 Fallback model support when Gemini quota limits are hit

## Installation

1. Clone the repository
   ```bash
   cd gemini-chatbot
   ```

2. Create and activate a virtual environment
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install Python dependencies
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root
   ```env
   GROQ_API_KEY=your_api_key_here
   GROQ_MODEL=compound-beta
   GROQ_FALLBACK_MODEL=compound-beta-mini
   GROQ_EMBEDDING_MODEL=nomic-embed-text-v1_5
   RAG_DOCUMENT_PATH=docs
   RAG_TOP_K=2
   RAG_CHUNK_SIZE=800
   RAG_CHUNK_OVERLAP=100
   PORT=8080
   ```

   Get your API key from [Google AI Studio](https://aistudio.google.com).

5. Add your own documents
   Place `.txt` or `.md` files in the project root, the `docs/` folder, or point `RAG_DOCUMENT_PATH` to another folder.

## Running the App

Start the server:
```bash
python chatbot.py
```

Then open:
```text
http://localhost:8080
```

If you changed the `PORT` variable, use that port instead.

## Project Structure

```text
gemini-chatbot/
├── chatbot.py           # FastAPI app, RAG pipeline, and Gemini integration
├── requirements.txt     # Python dependencies
├── .env                 # Local environment variables
├── chroma_db/           # Persisted Chroma vector database
├── docs/                # Knowledge documents and screenshots
├── static/              # Web UI assets
│   ├── index.html
│   ├── style.css
│   └── script.js
```

## API Endpoints

- `GET /` — serves the web interface
- `POST /api/chat` — sends a message and returns a chatbot response plus image URLs
  - Request body:
    ```json
    {"message": "Explain the setup steps"}
    ```
  - Response example:
    ```json
    {
      "response": "Here is the answer...",
      "images": ["/screenshots/example.png"]
    }
    ```
- `POST /api/reset` — resets the session state endpoint

## Configuration Notes

- `GEMINI_MODEL` controls the primary Gemini model used for generation.
- `GEMINI_FALLBACK_MODEL` is used if the main model hits a quota or rate-limit error.
- `RAG_TOP_K`, `RAG_CHUNK_SIZE`, and `RAG_CHUNK_OVERLAP` control retrieval quality and chunking behavior.
- If documents contain image references such as `![alt](image.png)` or `[image: image.png]`, the app will try to resolve them from the docs or screenshot folders.

## Docker

Build the image:
```bash
docker build -t gemini-chatbot .
```

Run it:
```bash
docker run -d --name gemini-chatbot -p 8080:8080 \
  -e GEMINI_API_KEY=your_api_key_here \
  gemini-chatbot
```

You can also mount your local `.env` file:
```bash
docker run -d --name gemini-chatbot -p 8080:8080 \
  --env-file .env \
  gemini-chatbot
```

## Troubleshooting

### API key error
Make sure your `.env` file is present and contains a valid `GEMINI_API_KEY`.

### Quota errors
If Gemini returns a quota or rate-limit error, the app will attempt to retry with the fallback model defined in `GEMINI_FALLBACK_MODEL`.

### Port already in use
Change the `PORT` variable in your `.env` file.

## License

MIT License
