import uvicorn
from classctl.web.app import create_app

# Entry point: python -m classctl
uvicorn.run(create_app(), host="127.0.0.1", port=8000)
