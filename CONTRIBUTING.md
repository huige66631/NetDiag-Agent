# Contributing

This is a student project prototype. Keep changes focused on local network diagnosis
scenarios.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
pytest
```

## Notes

- Do not commit `.env.local` or API keys.
- Prefer structured probe results over ad-hoc text parsing in the UI.
- Keep LLM output grounded in collected network evidence.

