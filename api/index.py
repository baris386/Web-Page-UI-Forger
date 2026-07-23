import io
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


load_dotenv()
api_key = os.getenv("Gemini_Api") or os.getenv("GEMINI_API_KEY")

if not api_key:
    print("XƏTA: Gemini_Api environment variable Vercel-də tapılmadı!")
else:
    client = genai.Client(api_key=api_key)

# Create Gemini client
client = genai.Client(api_key=api_key)

# Vercel serverless fayl yazmağa YALNIZ /tmp qovluğunda icazə verir!
BASE_TMP = Path(tempfile.gettempdir())
GENERATED_DIR = BASE_TMP / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

SESSIONS_DIR = BASE_TMP / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_INSTRUCTION = (
    "You are a senior full-stack engineer and expert code assistant. Your primary task is to analyze the source code of an existing web project provided as a ZIP file by the user, make necessary modifications based on the user's instructions (prompts), and return the updated files in a precise structure."

    "Project tech stack: Python, Streamlit, React, TypeScript, Tailwind CSS, and Shadcn UI components."

    "Rules and Constraints:"
    "1. Context Fidelity: Always adhere to the provided existing project structure and file names (e.g., app.py, requirements.txt, components). Do not break existing working logic."
    "2. Style and Design Rule: Preserve existing structures, layout, and Streamlit state management unless requested."
    "3. Code Completeness: Provide full modified versions of files, never partial diffs."
    "4. OUTPUT FORMAT (MANDATORY):\n"
    "For EVERY file you create or modify, wrap it EXACTLY like this:\n"
    "===FILE: relative/path/to/file.ext===\n"
    "<full complete content, NO markdown fences like ```>\n"
    "===END===\n\n"
    "5. CHAT SUMMARY RULE (STRICT):\n"
    "After all ===FILE=== blocks, write a VERY SHORT plain-text summary of changes.\n"
    "DO NOT INCLUDE ANY CODE OR CODE BLOCKS (```) IN THE SUMMARY TEXT."
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEXT_EXTENSIONS = ('.ts', '.tsx', '.js', '.jsx', '.py', '.json', '.css', '.html')

FILE_BLOCK_RE = re.compile(
    r"===FILE:\s*(.+?)\s*===\s*\r?\n(.*?)\r?\n===END==",
    re.DOTALL,
)


def extract_zip_to_session(zip_path: Path, session_project_dir: Path):
    if session_project_dir.exists():
        shutil.rmtree(session_project_dir)
    session_project_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(session_project_dir)


def get_session_code_contents(session_project_dir: Path) -> dict:
    code_contents = {}
    if not session_project_dir.exists():
        return code_contents

    for root, _, files in os.walk(session_project_dir):
        for file in files:
            file_path = Path(root) / file
            rel_path = file_path.relative_to(session_project_dir).as_posix()
            if rel_path.endswith(TEXT_EXTENSIONS):
                try:
                    content = file_path.read_text(encoding="utf-8")
                    code_contents[rel_path] = content
                except Exception:
                    pass
    return code_contents


def save_updated_files_to_session(session_project_dir: Path, updated_files: dict):
    for rel_path, content in updated_files.items():
        file_path = session_project_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


def create_zip_from_session(session_project_dir: Path) -> str:
    download_id = uuid.uuid4().hex
    output_path = GENERATED_DIR / f"{download_id}.zip"

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
        for root, _, files in os.walk(session_project_dir):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(session_project_dir).as_posix()
                new_zip.write(file_path, arcname=rel_path)

    return download_id


def parse_file_blocks(ai_text: str):
    files = {}
    for match in FILE_BLOCK_RE.finditer(ai_text):
        path = match.group(1).strip().replace("\\", "/")
        content = match.group(2)
        content = re.sub(r"^```[a-zA-Z]*\r?\n", "", content)
        content = re.sub(r"\r?\n```$", "", content)
        files[path] = content
    return files


@app.post("/api/chat")
async def handle_chat(
    message: str = Form(...),
    session_id: str = Form(None),
    project_file: UploadFile = File(None)
):
    try:
        if not session_id or session_id == "null" or session_id == "undefined":
            session_id = uuid.uuid4().hex

        session_project_dir = SESSIONS_DIR / session_id / "project"
        session_project_dir.mkdir(parents=True, exist_ok=True)

        if project_file:
            temp_zip = SESSIONS_DIR / session_id / f"upload_{project_file.filename}"
            with open(temp_zip, "wb") as buffer:
                shutil.copyfileobj(project_file.file, buffer)
            extract_zip_to_session(temp_zip, session_project_dir)
            if temp_zip.exists():
                os.remove(temp_zip)

        code_contents = get_session_code_contents(session_project_dir)

        code_context = ""
        if code_contents:
            code_context = "\n\n---PROJECT CODE---\n"
            for file_path, content in code_contents.items():
                code_context += f"\n### File: {file_path}\n"
                code_context += f"```\n{content}\n```\n"

        full_prompt = f"{message}{code_context}"

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=f"{SYSTEM_INSTRUCTION}\n\n{full_prompt}"
        )

        ai_response = response.text or ""
        updated_files = parse_file_blocks(ai_response)

        download_id = None
        if updated_files:
            save_updated_files_to_session(session_project_dir, updated_files)
            download_id = create_zip_from_session(session_project_dir)
        elif session_project_dir.exists() and any(session_project_dir.iterdir()):
            download_id = create_zip_from_session(session_project_dir)

        display_text = FILE_BLOCK_RE.sub("", ai_response)
        display_text = re.sub(r"===FILE:.*?===", "", display_text)
        display_text = re.sub(r"===END===", "", display_text)
        display_text = re.sub(r"```[\s\S]*?```", "", display_text)
        display_text = display_text.strip()

        if not display_text:
            display_text = f"Dəyişikliklər tətbiq olundu ({len(updated_files)} fayl yeniləndi)." if updated_files else "Tələb yerinə yetirildi."

        return {
            "status": "success",
            "reply": display_text,
            "session_id": session_id,
            "download_id": download_id,
            "updated_file_count": len(updated_files),
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "reply": f"Error processing request: {str(e)}"}


@app.get("/api/download/{download_id}")
async def download_updated_zip(download_id: str):
    safe_id = re.sub(r"[^a-f0-9]", "", download_id)
    zip_path = GENERATED_DIR / f"{safe_id}.zip"
    if not zip_path.exists():
        return {"status": "error", "reply": "Fayl tapılmadı və ya vaxtı keçib."}
    return FileResponse(
        path=str(zip_path),
        filename="updated_project.zip",
        media_type="application/zip",
    )
