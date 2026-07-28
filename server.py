# server.py
import marimo
import uvicorn
import webbrowser

# Create an app that serves everything in the "./notebooks" folder
app = (
    marimo.create_asgi_app()
    .with_app(path="/", root="notebooks/index.py")
    .with_dynamic_directory(path="/", directory="./notebooks")
    .build()
)

PORT = 8017

if __name__ == "__main__":
    webbrowser.open(f"http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
