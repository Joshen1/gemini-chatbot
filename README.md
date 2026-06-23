# Gemini Chatbot with FastAPI Web Interface

A modern web-based chatbot powered by Google's Gemini 3 Flash Preview model, built with FastAPI and featuring a beautiful chat interface.

## Features

- 🚀 **Web Interface**: Modern, responsive chat UI
- ⚡ **FastAPI Backend**: High-performance REST API
- 💬 **Real-time Chat**: Stream responses from Gemini
- 🔄 **Session Management**: Reset chat history anytime
- 📱 **Responsive Design**: Works on desktop and mobile devices
- 💾 **Backward Compatible**: Can still run in CLI mode

## Installation

1. **Clone the repository**
   ```bash
   cd chatbot_joshen
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Create a `.env` file in the project root:
   ```
   GEMINI_API_KEY=your_api_key_here
   ```
   Get your API key from [Google AI Studio](https://aistudio.google.com)

5. **Add your own document**
   Place your `.txt` or `.md` document in the project root or in `docs/`.
   If you prefer a custom path, add this to `.env`:
   ```
   RAG_DOCUMENT_PATH=document.txt
   ```
   The chatbot will load the file and use it as context when answering questions.

## Usage

### Web Interface (Default)

Start the FastAPI server:
```bash
python chatbot.py
```

Then open your browser and navigate to:
```
http://localhost:8000
```
If you changed the `PORT` environment variable, use that port instead.

### Docker

Build the Docker image:
```bash
docker build -t chatbot_joshen .
```

Run the container:
```bash
docker run -d --name chatbot_joshen -p 8000:8000 \
  -e GEMINI_API_KEY=your_api_key_here \
  chatbot_joshen
```

Then open:
```
http://localhost:8000
```

If you want to mount a local `.env` file instead of passing the key directly:
```bash
docker run -d --name chatbot_joshen -p 8000:8000 \
  --env-file .env \
  chatbot_joshen
```

### CLI Mode (Legacy)

Run in command-line mode:
```bash
python chatbot.py --cli
```

## API Endpoints

- **GET `/`** - Serves the web interface
- **POST `/api/chat`** - Send a message and get a response
  - Request: `{"message": "your message here"}`
  - Response: `{"response": "chatbot response"}`
- **POST `/api/reset`** - Reset the chat session
  - Response: `{"status": "Chat session reset"}`

## Project Structure

```
chatbot_joshen/
├── chatbot.py           # Main FastAPI application
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (create this)
├── venv/               # Virtual environment
└── static/
    ├── index.html      # Web interface HTML
    ├── style.css       # Styling
    └── script.js       # Frontend JavaScript
```

## Technologies Used

- **Backend**: FastAPI, Python
- **Frontend**: HTML5, CSS3, JavaScript
- **AI Model**: Google Gemini 3 Flash Preview
- **Server**: Uvicorn

## Troubleshooting

### API Key Error
Make sure your `.env` file is in the project root directory with the correct API key.

### Port Already in Use
If port 8000 is already in use, you can change it by modifying the `uvicorn.run()` call in `chatbot.py`:
```python
uvicorn.run(app, host="0.0.0.0", port=8080)
```

### Dependencies Not Installing
Try upgrading pip:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## License

MIT License
