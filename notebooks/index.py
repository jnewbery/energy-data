import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def imports():
    import ast
    import marimo as mo
    import pathlib
    return ast, mo, pathlib


@app.cell
def show_index(ast, mo, pathlib):
    # 1. Get the directory of the current notebook
    # __file__ works in marimo to get the current script path
    current_dir = pathlib.Path(__file__).parent

    # 2. Find all .py files (excluding this index file)
    notebooks = sorted([
        f for f in current_dir.glob("*.py") 
        if f.name != "index.py" and not f.name.startswith("_")
    ])

    def parse_metadata(notebook_path):
        docstring = ast.get_docstring(ast.parse(notebook_path.read_text()))
        title = None
        description = None
        if docstring:
            for line in docstring.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("title:"):
                    title = stripped.split(":", 1)[1].strip()
                if stripped.lower().startswith("description:"):
                    description = stripped.split(":", 1)[1].strip()
        return title, description

    # 3. Generate Markdown table rows
    # We assume the server maps "filename.py" -> "/filename"
    rows = []
    for nb in notebooks:
        title, description = parse_metadata(nb)
        # Turn "gb_carbon_intensity.py" into "Gb Carbon Intensity"
        human_name = title or nb.stem.replace("_", " ").title()

        # Create the URL path (e.g., /gb_carbon_intensity)
        url = f"/{nb.stem}"

        rows.append((f"[{human_name}]({url})", description or ""))

    # 4. Display the dashboard
    table_rows = "\n".join(f"| {title} | {description} |" for title, description in rows)
    table = "\n".join(
        [
            "| Report | Description |",
            "|:--- |:--- |",
            table_rows,
        ]
    )
    mo.vstack([
        mo.md(
        """
        # ⚡️ Energy Data Dashboards
        Select a report below to view the latest data.

        ---
        """),
        mo.md(table)
    ])
    return


if __name__ == "__main__":
    app.run()
