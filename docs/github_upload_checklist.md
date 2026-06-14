# GitHub Upload Checklist

- Commit source files, docs, tests, `pyproject.toml`, `.env.example`, and `README.md`.
- Do not commit `.env.local`.
- Do not commit `.venv/`.
- Do not commit generated reports under `reports/`.
- Do not commit Streamlit logs.
- Revoke and regenerate any API key that has been pasted into chat before public upload.

Before pushing:

```powershell
pytest
git status
rg "sk-" . -g "!.env.local"
```
