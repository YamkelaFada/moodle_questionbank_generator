# Grade 12 Moodle Quiz Generator

## Goal

Upload:

1. Grade 12 question paper PDF
2. Grade 12 memorandum PDF

The application extracts question items, matches memorandum content by question number, detects a likely Moodle question type, provides a review screen, and generates a Moodle XML quiz file.

## Current prototype

- Python + Streamlit
- PDF text extraction with PyMuPDF
- Question-number parsing (e.g. 1.1, 1.2, 2.3.1)
- Memorandum matching
- Basic question-type detection
- Human review/edit screen
- Moodle XML export
- Supports essay, short-answer, numerical, multiple-choice and true/false question types as output targets

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/app.py
```

Then open the local Streamlit URL shown in the terminal.

## Important limitation

This is the first working parser prototype, not the final production system.

For the ECDOE exam workflow, the production version should add:

- OCR fallback for scanned PDFs
- Layout-aware extraction of tables
- PDF page rendering and diagram cropping
- Shared diagram detection (one diagram referenced by several questions)
- Better memo/rubric parsing
- Safer numerical answer extraction
- Proper MCQ option extraction
- Question marks and section metadata
- Validation rules
- Question preview
- Moodle Web Services API publishing
- Secure Moodle token configuration
- Import/export logs
- Duplicate detection
- Audit trail

The system should never automatically publish an uncertain question without review.
