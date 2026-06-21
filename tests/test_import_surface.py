from pathlib import Path

from fastapi import FastAPI


def test_open_managed_agents_exports_app_factory():
    from open_managed_agents import CurrentWorkspace, create_app

    app = create_app(auth_provider=_HostedAuthProvider())

    assert isinstance(app, FastAPI)
    assert CurrentWorkspace(id="ws_test").id == "ws_test"


def test_legacy_uvicorn_entrypoint_still_exposes_app():
    from app.main import app

    assert isinstance(app, FastAPI)


def test_core_does_not_import_anthropic_sdk():
    repo_root = Path(__file__).resolve().parents[1]
    offenders = []
    for package in ("app", "open_managed_agents"):
        for path in (repo_root / package).rglob("*.py"):
            text = path.read_text()
            if "import anthropic" in text or "from anthropic" in text:
                offenders.append(str(path.relative_to(repo_root)))

    assert offenders == []


class _HostedAuthProvider:
    async def authenticate(self, request, credentials):
        from open_managed_agents import CurrentWorkspace

        return CurrentWorkspace(id="ws_test", slug="test", source="test")
