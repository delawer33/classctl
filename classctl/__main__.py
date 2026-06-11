import uvicorn
from classctl.web.app import create_app


def main():
    """Запускает веб-сервер classctl на 127.0.0.1:8000."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
