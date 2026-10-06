import base64
import io
import re
from pathlib import Path

import fitz
import streamlit as st


# -----------------------------
# PDF extraction
# -----------------------------
def extract_pages(pdf_path: str):
    doc = fitz.open(pdf_path)
    pages = []
    for page_no, page in enumerate(doc, start=1):
        pages.append({
            "page": page_no,
            "text": page.get_text("text"),
            "image_count": len(page.get_images(full=True)),
        })
    return pages


def normalise_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# -----------------------------
# Question parsing
# -----------------------------
QUESTION_RE = re.compile(
    r"(?m)^\s*(\d+(?:\.\d+){1,3})\s+(.*?)(?=\n\s*\d+(?:\.\d+){1,3}\s+|\Z)",
    re.S,
)

def parse_question_paper(pages):
    full = "\n\n".join(
        f"[PAGE {p['page']}]\n{normalise_text(p['text'])}" for p in pages
    )

    # Start from the first numbered sub-question and avoid the instructions/table.
    start = re.search(r"(?m)^\s*1\.1\s+", full)
    if start:
        full = full[start.start():]

    matches = list(QUESTION_RE.finditer(full))
    questions = []

    for m in matches:
        qid = m.group(1)
        body = normalise_text(m.group(2))

        # Remove page headers/footers that can leak into extracted text.
        body = re.sub(r"Accounting/P1 \d+ DBE/November 2025", "", body)
        body = re.sub(r"NSC Confidential.*?Copyright reserved Please turn over", "", body, flags=re.S)
        body = normalise_text(body)

        marks = None
        mark_match = re.search(r"\((\d+)\)\s*$", body)
        if mark_match:
            marks = int(mark_match.group(1))
            body = normalise_text(body[:mark_match.start()])

        qtype = detect_type(body)

        questions.append({
            "id": qid,
            "text": body,
            "marks": marks,
            "type": qtype,
            "source_page": find_page_for_id(full, qid),
            "answer": "",
            "review_required": True,
        })

    # Remove accidental formula-sheet fragments and duplicates.
    seen = set()
    clean = []
    for q in questions:
        if q["id"] not in seen and len(q["text"]) > 5:
            seen.add(q["id"])
            clean.append(q)
    return clean


def find_page_for_id(full_text, qid):
    m = re.search(rf"(?m)^\s*{re.escape(qid)}\s+", full_text)
    if not m:
        return None
    prefix = full_text[:m.start()]
    pages = re.findall(r"\[PAGE (\d+)\]", prefix)
    return int(pages[-1]) if pages else None


def detect_type(text):
    low = text.lower()

    if re.search(r"\bchoose the correct word", low):
        return "shortanswer"

    if any(x in low for x in [
        "calculate", "ratio", "rate", "amount", "percentage", "per share",
        "value of", "closing stock"
    ]):
        return "numerical"

    if any(x in low for x in [
        "prepare the", "complete the", "statement of", "note", "show all workings"
    ]):
        return "essay"

    if any(x in low for x in [
        "give two", "give one", "explain", "comment", "advise", "state two",
        "provide two", "suggest two", "reason", "why"
    ]):
        return "essay"

    # Generic fallback.
    return "essay"


# -----------------------------
# Memorandum matching
# -----------------------------
def parse_memo(pages):
    full = "\n\n".join(
        f"[PAGE {p['page']}]\n{normalise_text(p['text'])}" for p in pages
    )

    start = re.search(r"(?m)^\s*QUESTION 1\b", full)
    if start:
        full = full[start.start():]

    # Match numbered memo sections. The memo sometimes has a heading between
    # the number and the actual answer, so capture until the next question ID.
    pattern = re.compile(
        r"(?ms)^\s*(\d+(?:\.\d+){1,3})\s+(.*?)(?=^\s*\d+(?:\.\d+){1,3}\s+|\Z)"
    )

    answers = {}
    for m in pattern.finditer(full):
        qid = m.group(1)
        body = normalise_text(m.group(2))
        body = re.sub(r"Accounting/P1 \d+ DBE/November 2025", "", body)
        body = normalise_text(body)
        if len(body) > 3:
            answers[qid] = body

    return answers


# -----------------------------
# Moodle XML generation
# -----------------------------
def xml_escape(s):
    return (
        str(s).replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def make_moodle_xml(questions, quiz_name):
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<quiz>'
    ]

    for q in questions:
        qtype = q["type"]
        if qtype == "numerical":
            # Numerical questions need a numeric answer. If the memo does not
            # contain a clean numeric answer, we intentionally create an essay
            # question instead so the generated quiz is not falsely auto-graded.
            answer = extract_numeric_answer(q.get("answer", ""))
            if answer is None:
                qtype = "essay"

        out.append(f'<question type="{qtype}">')
        out.append(f'<name><text>{xml_escape(q["id"])}</text></name>')
        out.append(f'<questiontext format="html"><text><![CDATA[{q["text"]}]]></text></questiontext>')
        out.append('<generalfeedback format="html"><text><![CDATA['
                   + q.get("answer", "") + ']]></text></generalfeedback>')

        if qtype == "numerical":
            answer = extract_numeric_answer(q.get("answer", ""))
            out.append(f'<answer fraction="100"><text>{xml_escape(answer)}</text></answer>')
        elif qtype == "shortanswer":
            answer = extract_first_answer(q.get("answer", ""))
            if answer:
                out.append(f'<answer fraction="100"><text>{xml_escape(answer)}</text></answer>')
            else:
                out.append('<answer fraction="0"><text></text></answer>')
        elif qtype == "truefalse":
            out.append('<answer fraction="100"><text>true</text></answer>')
        elif qtype == "multichoice":
            out.append('<single>true</single>')
            out.append('<shuffleanswers>true</shuffleanswers>')

        out.append('</question>')

    out.append('</quiz>')
    return "\n".join(out)


def extract_numeric_answer(text):
    # Prefer a final standalone number with optional comma/decimal.
    candidates = re.findall(r"(?<![\w])(?:R\s*)?\d[\d\s]*(?:[,.]\d+)?%?(?![\w])", text)
    if not candidates:
        return None
    cleaned = candidates[-1].replace("R", "").replace(" ", "").replace(",", ".").replace("%", "")
    # Avoid choosing a year/page number.
    if cleaned in {"2025", "2024", "150", "45", "35", "30", "10"}:
        return None
    return cleaned


def extract_first_answer(text):
    # Heuristic only. The review screen is mandatory before publishing.
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for line in lines:
        if re.match(r"^(?:•|-)\s*", line):
            return re.sub(r"^(?:•|-)\s*", "", line)
        if "✓" in line:
            return re.sub(r"[✓]+", "", line).strip()
    return lines[0] if lines else ""


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Grade 12 Moodle Quiz Generator", layout="wide")
st.title("Grade 12 Moodle Quiz Generator")
st.caption("Upload a question paper and memorandum → extract → review → generate Moodle XML.")

with st.sidebar:
    st.header("Quiz details")
    subject = st.text_input("Subject", "Accounting")
    year = st.text_input("Year", "2025")
    exam = st.text_input("Examination", "November")
    quiz_name = st.text_input("Quiz name", "Accounting P1 November 2025")

paper = st.file_uploader("Question Paper PDF", type=["pdf"], key="paper")
memo = st.file_uploader("Memorandum PDF", type=["pdf"], key="memo")

if st.button("Generate Quiz", type="primary", disabled=not (paper and memo)):
    tmp = Path("generated_temp")
    tmp.mkdir(exist_ok=True)
    paper_path = tmp / "question_paper.pdf"
    memo_path = tmp / "memorandum.pdf"
    paper_path.write_bytes(paper.getvalue())
    memo_path.write_bytes(memo.getvalue())

    paper_pages = extract_pages(str(paper_path))
    memo_pages = extract_pages(str(memo_path))

    questions = parse_question_paper(paper_pages)
    answers = parse_memo(memo_pages)

    for q in questions:
        q["answer"] = answers.get(q["id"], "")
        q["review_required"] = not bool(q["answer"])

    st.session_state["questions"] = questions
    st.session_state["quiz_name"] = quiz_name
    st.session_state["generated"] = True

if st.session_state.get("generated"):
    questions = st.session_state["questions"]

    st.subheader("Generated Quiz Review")
    st.write(f"**{len(questions)} question items detected.** Review every item before publishing.")

    for i, q in enumerate(questions):
        with st.expander(
            f"{'⚠️' if q['review_required'] else '✅'} {q['id']} — {q['type']} — "
            f"{q['marks'] or '?'} mark(s)"
        ):
            q["text"] = st.text_area("Question", q["text"], key=f"text_{i}", height=160)
            q["type"] = st.selectbox(
                "Moodle question type",
                ["essay", "shortanswer", "numerical", "multichoice", "truefalse"],
                index=["essay", "shortanswer", "numerical", "multichoice", "truefalse"].index(q["type"])
                if q["type"] in ["essay", "shortanswer", "numerical", "multichoice", "truefalse"] else 0,
                key=f"type_{i}"
            )
            q["answer"] = st.text_area(
                "Memorandum / marking guidance",
                q["answer"],
                key=f"answer_{i}",
                height=140
            )
            st.caption(f"Source page: {q['source_page'] or 'not detected'}")

    if st.button("Generate Moodle XML"):
        xml = make_moodle_xml(questions, st.session_state["quiz_name"])
        st.download_button(
            "Download Moodle XML",
            data=xml.encode("utf-8"),
            file_name=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', st.session_state['quiz_name'])}.xml",
            mime="application/xml",
        )
        st.success("Moodle XML generated. Import it into Moodle after reviewing the questions.")

st.divider()
st.info(
    "Important: this first version deliberately requires human review. "
    "Exam papers contain calculations, tables, diagrams and marking rubrics that cannot safely "
    "be auto-graded from PDF text alone. The next integration step is direct Moodle Web Services "
    "publishing and stronger diagram/image handling."
)
