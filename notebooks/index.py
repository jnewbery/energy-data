import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def imports():
    import marimo as mo
    import pathlib
    return mo, pathlib


@app.cell
def show_index(mo, pathlib):
    # 1. Get the directory of the current notebook
    # __file__ works in marimo to get the current script path
    current_dir = pathlib.Path(__file__).parent

    # 2. Find all .py files (excluding this index file)
    notebooks = sorted([
        f for f in current_dir.glob("*.py") 
        if f.name != "index.py" and not f.name.startswith("_")
    ])

    # 3. Generate Markdown links
    # We assume the server maps "filename.py" -> "/filename"
    links = []
    for nb in notebooks:
        # Turn "gb_carbon_intensity.py" into "Gb Carbon Intensity"
        human_name = nb.stem.replace("_", " ").title()

        # Create the URL path (e.g., /gb_carbon_intensity)
        url = f"/{nb.stem}"

        links.append(f"[{human_name}]({url})")

    # 4. Display the dashboard
    mo.vstack([
        mo.md(
        """
        # ⚡️ Energy Data Dashboard
        Select a report below to view the latest data.

        ---
        """),
        mo.md("\n".join(f"- {s}" for s in links))
    ])
    return


if __name__ == "__main__":
    app.run()
