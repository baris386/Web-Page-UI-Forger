import io
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


load_dotenv()
api_key = os.getenv("Gemini_Api")

# Create Gemini client
client = genai.Client(api_key=api_key)

# Where generated zip files are stored so they can be downloaded later
GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

SYSTEM_INSTRUCTION = (
    "You are a senior full-stack engineer and expert code assistant. Your primary task is to analyze the source code of an existing web project provided as a ZIP file by the user, make necessary modifications based on the user's instructions (prompts), and return the updated files in a precise structure."

    "Project tech stack: React, TypeScript, Tailwind CSS, and Shadcn UI components."

    "Rules and Constraints:"
    "1. Context Fidelity: Always adhere to the provided existing project structure and file names. Do not break existing working logic."
    "2. Style and Design Rule: Unless the user explicitly requests a design/style change, preserve existing Tailwind classes and Shadcn UI component structures. Style and design adjustments will be executed separately in the final stage of the project, so avoid drastic and unwarranted visual changes."
    "3. Code Completeness: Do not leave incomplete code snippets (e.g., // implement here) when responding. Provide the full modified version of the file, never a partial diff or a snippet."
    "4. Cleanliness: Pay attention to TypeScript types while writing code and avoid syntax errors that could cause bugs."
    "5. OUTPUT FORMAT (MANDATORY): For every file you create or modify, you MUST wrap it EXACTLY like this, with nothing else on the marker lines:\n"
    "===FILE: relative/path/to/file.ext===\n"
    "<the full, complete content of the file, with no markdown code fences>\n"
    "===END===\n"
    "You may output multiple such blocks, one per file. After all ===FILE=== / ===END=== blocks, you may add a short plain-text summary of what changed for the human reader. "
    "Never omit the ===FILE=== / ===END=== markers when you are providing modified code. If the user is only asking a question and no code needs to change, do not include any ===FILE=== blocks at all."
)

app = FastAPI()

# Frontend-dən gələn sorğulara icazə vermək üçün CORS ayarı
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


TEXT_EXTENSIONS = ('.ts', '.tsx', '.js', '.jsx', '.py', '.json', '.css', '.html')

FILE_BLOCK_RE = re.compile(
    r"===FILE:\s*(.+?)\s*===\r?\n(.*?)\r?\n===END===",
    re.DOTALL,
)


def extract_zip_contents(file_path):
    """Extract zip file and read code contents (text files only)."""
    code_contents = {}
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            for file_info in zip_ref.filelist:
                if file_info.filename.endswith(TEXT_EXTENSIONS):
                    try:
                        content = zip_ref.read(file_info.filename).decode('utf-8')
                        code_contents[file_info.filename] = content
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error extracting zip: {e}")

    return code_contents


def parse_file_blocks(ai_text: str):
    """Pull out {path: content} pairs from the model's ===FILE===/===END=== blocks."""
    files = {}
    for match in FILE_BLOCK_RE.finditer(ai_text):
        path = match.group(1).strip()
        content = match.group(2)
        # Strip a stray leading/trailing markdown fence if the model added one anyway
        content = re.sub(r"^```[a-zA-Z]*\r?\n", "", content)
        content = re.sub(r"\r?\n```$", "", content)
        files[path] = content
    return files


def build_updated_zip(original_zip_path: str, updated_files: dict) -> str:
    """Take the original zip, overwrite/add the changed files, write a new zip
    to GENERATED_DIR, and return its download id (filename without extension)."""
    download_id = uuid.uuid4().hex
    output_path = GENERATED_DIR / f"{download_id}.zip"

    with zipfile.ZipFile(original_zip_path, 'r') as original_zip:
        original_names = original_zip.namelist()
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
            # Copy every original file, substituting updated content where present
            for name in original_names:
                if name in updated_files:
                    new_zip.writestr(name, updated_files[name])
                else:
                    new_zip.writestr(name, original_zip.read(name))
            # Add any brand-new files the AI created that weren't in the original zip
            for name, content in updated_files.items():
                if name not in original_names:
                    new_zip.writestr(name, content)

    return download_id


@app.post("/api/chat")
async def handle_chat(
    message: str = Form(...),
    project_file: UploadFile = File(None)
):
    temp_file_path = None
    try:
        print(f"Incoming message: {message}")

        code_context = ""

        # Handle uploaded zip file
        if project_file:
            temp_file_path = f"temp_{project_file.filename}"
            with open(temp_file_path, "wb") as buffer:
                shutil.copyfileobj(project_file.file, buffer)
            print(f"File saved: {temp_file_path}")

            # Extract zip contents
            code_contents = extract_zip_contents(temp_file_path)

            # Build code context
            if code_contents:
                code_context = "\n\n---PROJECT CODE---\n"
                for file_path, content in code_contents.items():
                    code_context += f"\n### File: {file_path}\n"
                    code_context += f"```\n{content}\n```\n"

        # Build the full prompt
        full_prompt = f"{message}"
        if code_context:
            full_prompt += code_context

        # Call Gemini API
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=f"{SYSTEM_INSTRUCTION}\n\n{full_prompt}"
        )

        ai_response = response.text

        # Try to pull out real file changes from the model's response
        updated_files = parse_file_blocks(ai_response)

        download_id = None
        if updated_files and temp_file_path and os.path.exists(temp_file_path):
            download_id = build_updated_zip(temp_file_path, updated_files)

        # A cleaner chat message: hide the raw ===FILE=== blocks from the bubble,
        # show only the human-readable part (or a short note if it was all code).
        display_text = FILE_BLOCK_RE.sub("", ai_response).strip()
        if not display_text:
            display_text = f"{len(updated_files)} fayl yeniləndi. Nəticəni yükləmək üçün 'Download AI File' düyməsinə basın." if updated_files else ai_response

        return {
            "status": "success",
            "reply": display_text,
            "download_id": download_id,
            "updated_file_count": len(updated_files),
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "reply": f"Error processing request: {str(e)}"}

    finally:
        # Clean up temp upload — the zip is rebuilt into GENERATED_DIR before this runs
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@app.get("/api/download/{download_id}")
async def download_updated_zip(download_id: str):
    # Guard against path traversal / arbitrary file access
    safe_id = re.sub(r"[^a-f0-9]", "", download_id)
    zip_path = GENERATED_DIR / f"{safe_id}.zip"
    if not zip_path.exists():
        return {"status": "error", "reply": "Fayl tapılmadı və ya vaxtı keçib."}
    return FileResponse(
        path=str(zip_path),
        filename="updated_project.zip",
        media_type="application/zip",
    )
