from pathlib import Path

from vrsoft_extractor.gui import main


if __name__ == "__main__":
    raise SystemExit(main(["--project-dir", str(Path(__file__).resolve().parent)]))

