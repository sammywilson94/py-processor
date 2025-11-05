
---

## ⚙️ `rules.md`

```markdown
# Cursor Rules for Building PDF Processor Bridge

## Coding Standards
- Use **Flask 3.x** with Blueprints.
- Always use `type hints` in all function definitions.
- Format code with **Black**.
- Add docstrings for all functions.

## Architecture Rules
1. Keep all PDF logic inside `services/pdf_service.py`.
2. The main Flask app (`app.py`) should only initialize app, register blueprints, and run server.
3. Routes should be defined under `routes/pdf_routes.py`.
4. Utilities (like response formatters) go under `utils/`.

## API Rules
- Every route should return a **consistent JSON** with keys:
  - `status`: "success" | "error"
  - `data` (optional): extracted text or structured info
  - `message`: optional message string
- Use appropriate HTTP codes (200, 400, 500).

## Error Handling
- Use a centralized error handler for all unhandled exceptions.
- Return readable messages (no stack traces).

## Logging
- Use Python’s `logging` module instead of print.
- Logs should include timestamps and log levels.

## Dependencies
Install using: pip install flask docling python-dotenv pytest or working commands
