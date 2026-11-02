from fastapi import FastAPI

app = FastAPI(title="pairprogrammer")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
