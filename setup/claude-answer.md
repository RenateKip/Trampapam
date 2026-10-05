# What `make test` does

`make test` runs the project's pytest suite. It's defined in the `Makefile` as:

```make
test: ## Palaiž testus
	python -m pytest -q
```

## What happens when you run it

1. **Environment variable.** At the top, the Makefile exports `OMD_API_TOKEN` with the placeholder value `macibu-tokens-tikai-imitacijai`. It's meant only for the mock and is set for every target, including `test`.
2. **pytest runs** in quiet mode (`-q`), so you get one dot per test and a short summary. The settings come from `pyproject.toml`:
   - `testpaths = ["tests"]`: tests are collected only from `tests/`.
   - `pythonpath = ["."]`: the repo root goes on the import path, so `from app...` works.
   - A `filterwarnings` entry hides the httpx/Starlette TestClient deprecation warning.
3. **Fixtures** from `tests/conftest.py` set up each test:
   - `client` resets the in-memory SQLite storage with `storage.reset(seed=False)`, so each test starts empty with no seed data. It then wraps the FastAPI app in a `TestClient`, which means no real server or port is needed.
   - `fake_omd` replaces the real OMD registry client through `app.dependency_overrides[get_omd]`. The tests never contact the OMD mock or a real registry, so you don't need to run `make mock` first. By default the fake treats only `32000000001` as `ACTIVE` and everything else as `NOT_ACTIVATED`. It also records every lookup in `.calls` so tests can check them.
   - `valid_payload` is a synthetic, valid submission body that tests can modify.

## What gets tested

The files in `tests/`:

- `test_submissions.py`: core submission API
- `test_cr0_topics.py`, `test_cr1_personal_code.py`, `test_cr2_reply_channel.py`, `test_cr3_list.py`: acceptance tests for the change requests (CR-0 to CR-3) in `tracker/`
- `test_audit.py`: audit logging
- `test_working_days.py`: working-day calculation

It's self-contained: nothing else needs to be running, and it doesn't format or lint anything. Formatting is `make fmt`, and the ruff, bandit and pip-audit scanners are `make check`.
