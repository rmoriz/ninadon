# AGENTS.md

## Virtual Environment Setup
- **Create venv:** `python3 -m venv .venv`
- **Activate venv (Unix/macOS):** `source .venv/bin/activate`
- **Activate venv (Windows):** `.venv\Scripts\activate`
- **Install dependencies:** `pip install -r requirements.txt`

## Build, Lint, and Test Commands

## Running Tests
- **You must activate the .venv before running tests.**
- On Unix/macOS:
  - `source .venv/bin/activate`
- On Windows:
  - `.venv\Scripts\activate`
- Then run tests with:
  - `PYTHONPATH=. pytest tests/test_main.py`
- To run a single test function:
  - `PYTHONPATH=. pytest tests/test_main.py::test_func`
- **All tests must pass before committing and pushing any changes.**
- **Running the tests before every git commit or push is MANDATORY. This is a MUST, not a recommendation.**

- **Install dependencies:** `pip install -r requirements.txt`
- **Build Docker image:** `docker build .`
- **Run app:** `python src/main.py <video_url>`
- **Lint (recommended):** `ruff src/` or `flake8 src/` (add to requirements if needed)
- **Test:** No tests found. If using pytest: `pytest tests/test_main.py::test_func`

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
