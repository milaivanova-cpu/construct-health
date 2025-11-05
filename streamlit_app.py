import streamlit as st
from pypdf import PdfReader
import re

st.set_page_config(page_title="Construct Health MVP", layout="wide")
st.title("🧠 Construct Health Assessment (MVP)")
st.write("Upload a PDF containing a psychological construct study to generate a preliminary assessment.")

uploaded_file = st.file_uploader("📄 Upload PDF", type=["pdf"])

# --- Regex patterns for detection ---
RE_DEF = re.compile(r"\b(is defined as|we define|defined as|refers to)\b", re.I)
RE_RELIABILITY = re.compile(r"\b(alpha|omega|test[- ]?retest|ICC)\b", re.I)
RE_CFA = re.compile(r"\b(CFA|confirmatory factor analysis|RMSEA|CFI|TLI|SRMR)\b", re.I)
RE_INVARIANCE = re.compile(r"\b(configural|metric|scalar|strict)\s+invariance\b|\bDIF\b", re.I)
RE_VALIDITY = re.compile(r"\b(convergent|discriminant|criterion|predictive|known[- ]groups)\b", re.I)
RE_FAIRNESS = re.compile(r"\b(bias|fairness|harm|misuse|ethical)\b", re.I)

def extract_text(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        try:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        except:
            pass
    return text

def score_feature(text, pattern):
    matches = pattern.findall(text)
    score = min(len(matches), 3)
    return score, matches[:3]  # show up to 3 snippets

if uploaded_file:
    with st.spinner("🔍 Analyzing PDF..."):
        text = extract_text(uploaded_file)

        # Score features
        definition_score, def_snips = score_feature(text, RE_DEF)
        reliability_score, rel_snips = score_feature(text, RE_RELIABILITY)
        cfa_score, cfa_snips = score_feature(text, RE_CFA)
        inv_score, inv_snips = score_feature(text, RE_INVARIANCE)
        val_score, val_snips = score_feature(text, RE_VALIDITY)
        fair_score, fair_snips = score_feature(text, RE_FAIRNESS)

    st.success("✅ Analysis complete!")

    st.subheader("Results")
    results = {
        "Definition clarity": definition_score,
        "Reliability evidence": reliability_score,
        "Factor structure (CFA/fit)": cfa_score,
        "Measurement invariance": inv_score,
        "Validity evidence": val_score,
        "Fairness / harm": fair_score,
    }

    for item, score in results.items():
        st.write(f"**{item}:** {score}/3")

    st.subheader("Evidence snippets")
    snippet_groups = [
        ("Definitions", def_snips),
        ("Reliability", rel_snips),
        ("CFA / Fit Indices", cfa_snips),
        ("Invariance / DIF", inv_snips),
        ("Validity", val_snips),
        ("Fairness / Ethics", fair_snips),
    ]

    for label, snips in snippet_groups:
        if snips:
            with st.expander(label):
                for snip in snips:
                    st.write("→", snip.strip())
