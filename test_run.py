from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "app"))

# This file is intentionally minimal. Use the Streamlit UI for the full workflow.
print("Run: streamlit run app/app.py")
