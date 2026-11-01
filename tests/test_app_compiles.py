"""app.py se ne uvozi u testovima (Streamlit), ali mora bar da se kompajlira — sintaksna greška bi srušila cijelu aplikaciju."""
import pathlib
import py_compile


def test_app_py_compiles(tmp_path):
    src = pathlib.Path(__file__).resolve().parents[1] / "app.py"
    py_compile.compile(str(src), cfile=str(tmp_path / "app.pyc"), doraise=True)
