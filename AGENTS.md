# AGENTS.md

## Virtual Environment Setup
- **Create venv:** `python3 -m venv .venv`
- **Activate venv (Unix/macOS):** `source .venv/bin/activate`
- **Activate venv (Windows):** `.venv\Scripts\activate`
- **Install dependencies:** `pip install -r requirements.txt`
- **Install Deno (required for yt-dlp):** `curl -fsSL https://deno.land/install.sh | sh` (Unix/macOS) or download from https://deno.land/

## Build, Lint, and Test Commands

### Running Tests
- **You must activate the .venv before running tests.**
- On Unix/macOS:
  - `source .venv/bin/activate`
- On Windows:
  - `.venv\Scripts\activate`
- Then run tests with:
  - `PYTHONPATH=. pytest tests/` (run all tests - 202 tests total)
  - `PYTHONPATH=. pytest tests/test_main.py` (run specific test file)
  - `PYTHONPATH=. pytest tests/test_main.py::test_func` (run single test function)
  - `PYTHONPATH=. pytest tests/ -x` (stop on first failure)
  - `PYTHONPATH=. pytest tests/ --tb=short` (short traceback format)
- **All tests must pass before committing and pushing any changes.**
- **Running the tests before every git commit or push is MANDATORY. This is a MUST, not a recommendation.**

### Linting
- **Lint code:** `ruff check src/`
- **Fix linting issues:** `ruff check --fix src/`
- **Format code:** `ruff format src/`
- **Check specific file:** `ruff check src/main.py`

### Building and Running
- **Install dependencies:** `pip install -r requirements.txt`
- **Install Deno:** Ensure Deno is installed (required for future yt-dlp versions)
- **Build Docker image:** `docker build .`
- **Run app:** `python -m src.main <video_url>`
- **Run web interface:** `python -m src.main --web`

## Code Style Guidelines
- **Imports:** Standard library, then third-party, then local imports.
- **Formatting:** 4 spaces per indent, blank lines between functions.
- **Types:** Type hints not required but encouraged for new code.
- **Naming:**
  - Functions/variables: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`
  - Classes: `CamelCase`
- **Error Handling:** Use try/except; raise `RuntimeError` for critical errors (e.g., missing env vars).
- **Environment:** Use env vars for config (API keys, URLs, timeouts).
- **Logging:** Use `print()` for logs; consider `logging` for larger projects.
- **Entrypoint:** Guard main logic with `if __name__ == "__main__":`

_No Cursor or Copilot rules detected._
