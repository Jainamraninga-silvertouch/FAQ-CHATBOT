# Doc FAQ — Document-Based FAQ Chatbot

A FAQ chatbot that answers questions from documents placed in the `/upload` folder. Supports PDF, Word, Excel, and text files. No frontend upload - documents are loaded automatically at server startup.

## Features

✅ **Auto-load documents** - Place files in `/upload` folder, restart server  
✅ **Multi-format support** - PDF, DOCX, TXT, XLSX  
✅ **Multi-document search** - Searches across ALL uploaded documents  
✅ **Smart answering** - Synthesizes information from multiple sections  
✅ **Suggested questions** - Get 3 related follow-up questions  
✅ **Source transparency** - See which documents were used  

## Quick Start

### 1. Setup

```cmd
# Run automated setup
setup.bat

# This creates virtual environment and installs dependencies
```

### 2. Configure API Key

Edit `.env` file:
```env
GROQ_API_KEY=your_actual_api_key_here
```

Get your free API key from: https://console.groq.com/keys

### 3. Add Documents

Place your documents in the `/upload` folder:

```
upload/
  ├── employee_handbook.pdf
  ├── company_policies.docx
  ├── faq_data.xlsx
  └── guidelines.txt
```

Supported formats: **PDF, DOCX, TXT, XLSX, XLS**

### 4. Start Server

```cmd
run.bat
```

The server will automatically:
- Load all documents from `/upload` folder
- Index them for searching
- Display loaded documents in the log

### 5. Use the Chatbot

Open: **http://localhost:8000**

Ask questions and the bot will search across all loaded documents to answer.

## How It Works

```
Server Startup
    ↓
Load files from /upload
    ↓
Extract text → Split into sections → Index in memory
    ↓
User asks question
    ↓
Search across ALL documents → Find relevant sections
    ↓
LLM generates answer from found sections
    ↓
Display answer + suggested questions + sources
```

## Usage

**Adding Documents:**
1. Place files in `/upload` folder
2. Restart server (`Ctrl+C` then `run.bat`)
3. Documents auto-load and display in sidebar

**Asking Questions:**
- Type question in chat
- Bot searches ALL documents
- Returns answer with sources
- Shows 3 suggested follow-up questions
- Click suggested questions to ask them

**Multi-Document Answers:**
The bot automatically searches across all uploaded documents and combines relevant information from multiple files if needed.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/documents` | List all loaded documents |
| POST | `/chat` | Ask a question |
| GET | `/api/health` | Health check |

API docs: **http://localhost:8000/docs**

## File Structure

```
faq-chatbot/
├── upload/              ← Place your documents here
│   ├── document1.pdf
│   ├── document2.xlsx
│   └── README.txt
├── main.py             ← Auto-loads documents at startup
├── app/
│   ├── services/
│   │   └── document_loader.py  ← Loads from /upload
│   └── ...
└── static/             ← Web interface (no upload UI)
```

## Example

```cmd
# 1. Add documents
copy employee_handbook.pdf upload/
copy policies.docx upload/

# 2. Start server
run.bat

# You'll see:
# ✓ Loaded 2 document(s) into memory
# Documents:
#   - employee_handbook.pdf (15 sections)
#   - policies.docx (8 sections)

# 3. Open browser and ask:
# "What is the leave policy?"
# Bot searches both documents and provides answer
```

## Notes

- Documents load at **startup only** - restart to reload
- Supports multiple documents simultaneously
- Searches across ALL documents for each question
- No file size limit per document (reasonable sizes)
- No persistence - restart clears memory
