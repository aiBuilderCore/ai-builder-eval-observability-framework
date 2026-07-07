import uvicorn

from eeof_core.config import settings

from .app import app


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=settings.observability_svc_port)


if __name__ == "__main__":
    main()
