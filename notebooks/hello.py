import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    print("hello notebook")
    return


if __name__ == "__main__":
    app.run()
