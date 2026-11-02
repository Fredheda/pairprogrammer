from ag_ui_claude_sdk import ClaudeAgentAdapter, add_claude_fastapi_endpoint
from fastapi import FastAPI

from pairprogrammer.agent import AGENT_PATH, make_adapter


def create_app(adapter: ClaudeAgentAdapter) -> FastAPI:
    app = FastAPI(title="pairprogrammer")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    add_claude_fastapi_endpoint(app, adapter, path=AGENT_PATH)
    return app


app = create_app(make_adapter())
