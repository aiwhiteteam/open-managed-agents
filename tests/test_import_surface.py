from fastapi import FastAPI


def test_open_managed_agents_exports_app_factory():
    from open_managed_agents import CurrentWorkspace, create_app

    app = create_app(auth_provider=_HostedAuthProvider())

    assert isinstance(app, FastAPI)
    assert CurrentWorkspace(id="ws_test").id == "ws_test"


def test_legacy_uvicorn_entrypoint_still_exposes_app():
    from app.main import app

    assert isinstance(app, FastAPI)


class _HostedAuthProvider:
    async def authenticate(self, request, credentials):
        from open_managed_agents import CurrentWorkspace

        return CurrentWorkspace(id="ws_test", slug="test", source="test")
