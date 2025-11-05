import streamlit as st
import yaml, json, regex as re
from io import BytesIO

# Prefer PyMuPDF for cleaner text; fall back to pypdf
def extract_text(file) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file.read(), filetype="pdf")
        txt = []
        for page in doc:
            txt.append(page.get_text("text"))
        return "\n".join(txt)
    except Exception:
        file.seek(0)
        from pypdf import PdfReader
        txt = []
        r = PdfReader(file)
        for p in r.pages:
            try:
                t = p.extract_text()
                if t: txt.append(t)
            except: pass
        return "\n".join(txt)

# --- sentence split (simple, fast, robust for PDFs)
SPLIT = re.compile(r'(?<=\.)\s+(?=[A-Z\(])|(?<=[!?])\s+')
def sentences(text:str):
    raw = re.sub(r'\s+', ' ', text)
    return [s.strip() for s in SPLIT.split(raw) if s.strip()]

# --- sectionizer
SECTION_HEAD = re.compile(r'\b(Abstract|Introduction|Background|Theory|Method|Methods|Measures?|Participants?|Procedure|Results?|Discussion|Conclusion)s?\b', re.I)
def sectionize(text:str):
    secs = {}
    current = "Full Text"
    secs[current] = []
    for line in text.splitlines():
        if SECTION_HEAD.search(line.strip()):
            current = SECTION_HEAD.search(line.strip()).group(0).title()
            secs.setdefault(current, [])
        secs[current].append(line)
    return {k: "\n".join(v).strip() for k,v in secs.items()}

# --- KB loaders
import os, yaml
@st.cache_data
def load_kb():
    with open("kb_constructs.yaml", "r", encoding="utf-8") as f:
        kb_c = yaml.safe_load(f)
    with open("kb_measures.yaml", "r", encoding="utf-8") as f:
        kb_m = yaml.safe_load(f)
    return kb_c, kb_m
KB_CONS, KB_MEAS = load_kb()

# --- Patterns
RE_DEF      = re.compile(r'\b(is defined as|we define|defined as|refers to)\b', re.I)
RE_BOUNDARY = re.compile(r'\b(distinct from|differs from|as opposed to|not merely|boundary|scope conditions?)\b', re.I)
RE_THEORY   = re.compile(r'\b(model|mechanism|dual[\s-]?systems?|process model|expected value of control|valuation)\b', re.I)

RE_DESIGN   = re.compile(r'\b(randomi[sz]ed|experiment|intervention|longitudinal|cross[- ]sectional|pre[- ]post|RCT)\b', re.I)

RE_ALPHA    = re.compile(r'(?:cronbach[^a-zA-Z]*alpha|alpha)\s*(?:=|:)?\s*([0]\.\d{2,}|[1](?:\.0+)?)', re.I)
RE_OMEGA    = re.compile(r'(?:omega|ω)\s*(?:=|:)?\s*([0]\.\d{2,}|[1](?:\.0+)?)', re.I)
RE_TRT      = re.compile(r'(?:test[- ]?retest|ICC)\s*(?:=|:)?\s*([0]\.\d{2,}|[1](?:\.0+)?)', re.I)

RE_CFI      = re.compile(r'CFI\s*(?:=|:)\s*(0\.\d{2,})', re.I)
RE_TLI      = re.compile(r'TLI\s*(?:=|:)\s*(0\.\d{2,})', re.I)
RE_RMSEA    = re.compile(r'RMSEA\s*(?:=|:)\s*(0\.\d{2,})', re.I)
RE_SRMR     = re.compile(r'SRMR\s*(?:=|:)\s*(0\.\d{2,})', re.I)
RE_INVAR    = re.compile(r'\b(configural|metric|scalar|strict)\s+invariance\b|\bmeasurement invariance\b|\bDIF\b', re.I)

RE_VALIDITY = re.compile(r'\b(convergent|discriminant|criterion|predictive|known[- ]groups|response[- ]process)\b', re.I)

# --- helpers
def find_sents(blob, pattern, maxn=6):
    sents = sentences(blob)
    out = []
    for s in sents:
        if pattern.search(s):
            out.append(s)
        if len(out) >= maxn: break
    return out

def detect_constructs(text):
    hits = {}
    for key, node in KB_CONS["constructs"].items():
        labels = node.get("canonical_labels", []) + node.get("near_neighbors", [])
        for lbl in labels:
            if re.search(rf'\b{re.escape(lbl)}\b', text, re.I):
                hits.setdefault(key, set()).add(lbl)
    return {k: sorted(v) for k,v in hits.items()}

def detect_measures(text):
    found = []
    for meas, node in KB_MEAS["measures"].items():
        for alias in node["aliases"]:
            if re.search(rf'\b{re.escape(alias)}\b', text, re.I):
                found.append({"measure": meas, "alias": alias, "type": node["type"], "targets": node["targets"]})
                break
    return found

def map_measures_to_components(found):
    buckets = {}
    for item in found:
        for t in item["targets"]:
            buckets.setdefault(t, []).append(item["measure"])
    return {k: sorted(set(v)) for k,v in buckets.items()}

def extract_numbers(blob):
    nums = {}
    # reliability
    alpha = [float(x) for x in RE_ALPHA.findall(blob)]
    omega = [float(x) for x in RE_OMEGA.findall(blob)]
    trt   = [float(x) for x in RE_TRT.findall(blob)]
    # structure/fit
    cfi   = [float(x) for x in RE_CFI.findall(blob)]
    tli   = [float(x) for x in RE_TLI.findall(blob)]
    rmsea = [float(x) for x in RE_RMSEA.findall(blob)]
    srmr  = [float(x) for x in RE_SRMR.findall(blob)]
    inv   = bool(RE_INVAR.search(blob))
    nums["alpha"] = alpha
    nums["omega"] = omega
    nums["test_retest_or_ICC"] = trt
    nums["CFI"] = cfi
    nums["TLI"] = tli
    nums["RMSEA"] = rmsea
    nums["SRMR"] = srmr
    nums["invariance_signal"] = inv
    return nums

def threshold_comments(nums):
    comments = []
    def any_ge(vals, thr): return any(v >= thr for v in vals) if vals else False
    def any_le(vals, thr): return any(v <= thr for v in vals) if vals else False

    if nums["alpha"]:
        comments.append(f"α values: {nums['alpha']} ⇒ {'OK (≥ .70)' if any_ge(nums['alpha'], .70) else 'low'}")
    if nums["omega"]:
        comments.append(f"ω values: {nums['omega']} ⇒ {'OK (≥ .70)' if any_ge(nums['omega'], .70) else 'low'}")
    if nums["test_retest_or_ICC"]:
        comments.append(f"Test–retest/ICC: {nums['test_retest_or_ICC']} ⇒ {'OK (≥ .70 typical)' if any_ge(nums['test_retest_or_ICC'], .70) else 'low'}")
    if nums["CFI"]:
        comments.append(f"CFI: {nums['CFI']} ⇒ {'OK (≥ .95 good, ≥ .90 acceptable)' if any_ge(nums['CFI'], .90) else 'poor'}")
    if nums["TLI"]:
        comments.append(f"TLI: {nums['TLI']} ⇒ {'OK (≥ .95/.90)' if any_ge(nums['TLI'], .90) else 'poor'}")
    if nums["RMSEA"]:
        comments.append(f"RMSEA: {nums['RMSEA']} ⇒ {'OK (≤ .06 good, ≤ .08 acceptable)' if any_le(nums['RMSEA'], .08) else 'high'}")
    if nums["SRMR"]:
        comments.append(f"SRMR: {nums['SRMR']} ⇒ {'OK (≤ .08 typical)' if any_le(nums['SRMR'], .08) else 'high'}")
    if nums["invariance_signal"]:
        comments.append("Measurement invariance mentioned (check configural/metric/scalar).")
    return comments

def jingle_jangle(text, constructs_found, measures_found):
    warns = []
    ops = {m["measure"] for m in measures_found}
    if "self-control" in constructs_found and "GritS" in ops:
        warns.append("Jingle risk: paper labels ‘self-control’ but uses Grit-S (grit). Check boundaries.")
    if "self-control" in constructs_found and "self-regulation" in constructs_found:
        if not RE_BOUNDARY.search(text):
            warns.append("Jangle risk: both ‘self-control’ and ‘self-regulation’ are used with no explicit differentiation.")
    if any(m["type"]=="self-report" for m in measures_found) and any(m["type"]=="behavioral task" for m in measures_found):
        warns.append("Method mix: self-report and behavioral tasks both present — mapping to theory should be explicit.")
    return warns

st.set_page_config(page_title="Construct Health — SC/SRL", layout="wide")
st.title("🧠 Construct Health — Self-Control / Self-Regulation (v2.1)")

uploaded = st.file_uploader("📄 Upload a PDF", type=["pdf"])

if uploaded:
    with st.spinner("🔎 Parsing and analyzing…"):
        blob = extract_text(uploaded)
        secs = sectionize(blob)
        focus = " ".join([
            secs.get("Abstract",""),
            secs.get("Introduction",""),
            secs.get("Theory",""),
            secs.get("Method","") + " " + secs.get("Measures",""),
            secs.get("Results",""),
            secs.get("Discussion","")
        ])

        constructs = detect_constructs(focus)
        measures = detect_measures(focus)
        comp_map = map_measures_to_components(measures)

        nums = extract_numbers(focus)
        num_comments = threshold_comments(nums)

        defs = find_sents(focus, RE_DEF, 5)
        bounds = find_sents(focus, RE_BOUNDARY, 5)
        mech = find_sents(focus, RE_THEORY, 5)
        design = find_sents(focus, RE_DESIGN, 5)
        validity = find_sents(focus, RE_VALIDITY, 6)

        jj = jingle_jangle(focus, constructs, measures)

    st.success("✅ Analysis complete")

    c1,c2,c3 = st.columns(3)
    with c1:
        st.metric("Definition present", "Yes" if defs else "No")
        st.metric("Theory/mechanism", "Yes" if mech else "No")
    with c2:
        st.metric("Reliability reported", "Yes" if (nums["alpha"] or nums["omega"] or nums["test_retest_or_ICC"]) else "No")
        st.metric("Structure/fit indices", "Yes" if (nums["CFI"] or nums["TLI"] or nums["RMSEA"] or nums["SRMR"]) else "No")
    with c3:
        st.metric("Invariance signal", "Yes" if nums["invariance_signal"] else "No")
        st.metric("Validity mentions", f"{len(validity)} hits")

    t1, t2, t3, t4, t5 = st.tabs(["Summary", "Theory & Scope", "Measures & Methods", "Jingle–Jangle", "Raw / Export"])

    with t1:
        st.subheader("Constructs detected")
        st.json(constructs or {"note": "none detected by heuristics"})
        st.subheader("Component mapping (targets → measures)")
        st.json(comp_map or {"note": "no target mappings detected"})
        st.subheader("Fit & reliability comments")
        for c in (num_comments or ["No numeric indices detected."]):
            st.write("•", c)

    with t2:
        st.subheader("Definition sentences")
        for s in defs: st.write("→", s)
        st.subheader("Boundary / scope sentences")
        for s in bounds: st.write("→", s)
        st.subheader("Theory / mechanism sentences")
        for s in mech: st.write("→", s)

    with t3:
        st.subheader("Measures detected")
        st.table([{k:v for k,v in m.items()} for m in measures] or [{"note":"no measures detected"}])
        st.subheader("Study design cues")
        for s in design: st.write("•", s)
        st.subheader("Validity evidence sentences")
        for s in validity: st.write("→", s)

    with t4:
        st.subheader("Warnings")
        if jj:
            for w in jj: st.warning(w)
        else:
            st.info("No obvious jingle–jangle risks flagged.")

    with t5:
        report = {
            "constructs_detected": constructs,
            "measures_detected": measures,
            "component_map": comp_map,
            "definition_sents": defs,
            "boundary_sents": bounds,
            "theory_sents": mech,
            "design_sents": design,
            "validity_sents": validity,
            "numeric_indices": nums,
            "numeric_comments": num_comments,
            "warnings": jj
        }
        st.subheader("Checklist JSON")
        st.json(report)
        st.download_button(
            "⬇️ Download JSON",
            data=json.dumps(report, indent=2).encode("utf-8"),
            file_name="construct_health_sc_srl.json",
            mime="application/json"
        )
