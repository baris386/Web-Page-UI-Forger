# ⚡ AI UI Forge (Aesthetic Edition)

**AI UI Forge** is a full-stack, AI-driven interface generator and code refiner. It allows developers to upload an existing project codebase (ZIP), interact with a custom Gemini-powered assistant to request UI/UX modifications, and instantly download the refactored, production-ready source code.

### ✨ Key Features
* **AI-Powered Code Refactoring:** Integrates Google's **Gemini 2.5 Flash** model for context-aware code edits.
* **Full Project Workspace:** Upload a ZIP archive, let the system analyze the structure, and get full updated code blocks.
* **Serverless Backend:** Built with **FastAPI** and optimized for **Vercel Serverless Functions**.
* **Modern Aesthetic UI:** Glassmorphism UI with interactive dynamic backgrounds powered by **Tailwind CSS**.
* **One-Click Export:** Download the updated codebase directly as a ready-to-use `.zip` file.

### 🛠 Tech Stack
* **Frontend:** HTML5, Tailwind CSS, JavaScript (Fetch API, Marked.js)
* **Backend:** Python, FastAPI, Pydantic, Uvicorn / Vercel Serverless Runtime
* **AI Engine:** Google GenAI SDK (`gemini-2.5-flash`)
* **Deployment:** Vercel (Backend API) & GitHub Pages (Frontend UI)
