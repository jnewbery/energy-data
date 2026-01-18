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

if __name__ == "__main__":
    webbrowser.open("http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
