import streamlit as st
from pypdf import PdfReader
import yaml, re, json
from io import BytesIO

st.set_page_config(page_title="Construct Health — Self-Control/Self-Regulation", layout="wide")
st.title("🧠 Construct Health — Self-Control / Self-Regulation (v2 core)")

# ---------- Load knowledge bases ----------
@st.cache_data
def load_kb():
    with open("kb_constructs.yaml", "r", encoding="utf-8") as f:
        kb_c = yaml.safe_load(f)
    with open("kb_measures.yaml", "r", encoding="utf-8") as f:
        kb_m = yaml.safe_load(f)
    return kb_c, kb_m

KB_CONS, KB_MEAS = load_kb()

# ---------- PDF text ----------
def extract_text(file) -> str:
    reader = PdfReader(file)
    out = []
    for p in reader.pages:
        try:
            t = p.extract_text()
            if t: out.append(t)
        except Exception:
            pass
    return "\n".join(out)

# ---------- Heuristics / Patterns ----------
RE_DEF = re.compile(r"\b(is defined as|we define|defined as|refers to)\b", re.I)
RE_BOUNDARY = re.compile(r"\b(distinct from|differs from|as opposed to|not merely|boundary|scope conditions?)\b", re.I)
RE_THEORY = re.compile(r"\b(model|theor(y|ies)|mechanism|process model|dual(-|\s)?systems?|expected value of control|valuation)\b", re.I)
RE_DESIGN = re.compile(r"\b(randomi[sz]ed|experiment|intervention|longitudinal|cross[- ]sectional|pre[- ]post|RCT)\b", re.I)

RE_REL = re.compile(r"\b(alpha|cronbach|omega|test[- ]?retest|ICC)\b", re.I)
RE_CFA = re.compile(r"\b(CFA|confirmatory factor analysis|RMSEA|CFI|TLI|SRMR)\b", re.I)
RE_INV = re.compile(r"\b(configural|metric|scalar|strict)\s+invariance\b|\bmeasurement invariance\b|\bDIF\b", re.I)
RE_VAL = re.compile(r"\b(convergent|discriminant|criterion|predictive|known[- ]groups|response[- ]process)\b", re.I)

def find_snips(text, pattern, n=5):
    out = []
    for m in pattern.finditer(text):
        s = max(0, m.start()-160); e = min(len(text), m.end()+160)
        out.append(text[s:e].replace("\n"," "))
        if len(out)>=n: break
    return out

# ---------- Domain-specific extraction ----------
def detect_constructs(text):
    hits = []
    for key, node in KB_CONS["constructs"].items():
        labels = node.get("canonical_labels", []) + node.get("near_neighbors", [])
        for lbl in labels:
            if re.search(rf"\b{re.escape(lbl)}\b", text, re.I):
                hits.append((key, lbl))
    # dedupe by canonical
    seen = {}
    for canon, lbl in hits:
        seen.setdefault(canon, set()).add(lbl)
    return {k: sorted(list(v)) for k,v in seen.items()}

def detect_measures(text):
    found = []
    for meas, node in KB_MEAS["measures"].items():
        for alias in node["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", text, re.I):
                found.append({
                    "measure": meas,
                    "alias": alias,
                    "type": node["type"],
                    "targets": node["targets"],
                })
                break
    return found

def map_measures_to_components(found_measures):
    # Flatten targets to "subcomponents"
    buckets = {}
    for item in found_measures:
        for t in item["targets"]:
            buckets.setdefault(t, []).append(item["measure"])
    return buckets

def jingle_jangle_warnings(text, constructs_found, measures_found):
    warns = []
    # Jingle: same label used with divergent operations (e.g., "self-control" with only "Grit-S")
    label_ops = set([m["measure"] for m in measures_found])
    if "self-control" in constructs_found and "GritS" in label_ops:
        warns.append("Jingle risk: ‘self-control’ label used while measuring ‘grit’ (Grit-S). Check construct boundaries.")
    # Jangle: different labels for overlapping ops
    if "self-control" in constructs_found and "self-regulation" in constructs_found:
        if not re.search(r"\b(distinct from|differs from|as opposed to|boundary)\b", text, re.I):
            warns.append("Jangle risk: ‘self-control’ and ‘self-regulation’ used without explicit differentiation.")
    # Mixed ops within one paper
    if any(m["type"]=="self-report" for m in measures_found) and any(m["type"]=="behavioral task" for m in measures_found):
        warns.append("Method mix: self-report and behavioral tasks both present—ensure theoretical mapping is explicit.")
    return warns

def axis_selfcontrol_checklist(text):
    # Theory & scope
    has_def = bool(RE_DEF.search(text))
    has_boundary = bool(RE_BOUNDARY.search(text))
    has_theory = bool(RE_THEORY.search(text))

    # Ops & design
    measures = detect_measures(text)
    constructs = detect_constructs(text)
    components = map_measures_to_components(measures)
    design_snips = find_snips(text, RE_DESIGN, 3)

    # Evidence signals
    rel = bool(RE_REL.search(text))
    cfa = bool(RE_CFA.search(text))
    inv = bool(RE_INV.search(text))
    val = bool(RE_VAL.search(text))

    # Jingle/Jangle
    jj = jingle_jangle_warnings(text, constructs, measures)

    checklist = {
        "theory_scope": {
            "definition_present": has_def,
            "boundary_conditions": has_boundary,
            "theory_or_mechanism_stated": has_theory,
            "definition_snippets": find_snips(text, RE_DEF, 3),
            "theory_snippets": find_snips(text, RE_THEORY, 3),
        },
        "operationalization": {
            "constructs_detected": constructs,              # canonical -> labels matched
            "measures_detected": measures,                  # list of dicts
            "component_map": components,                    # component -> measures
            "design_mentions": design_snips,
        },
        "measurement_evidence": {
            "reliability_signal": rel,
            "structure_fit_signal": cfa,
            "invariance_signal": inv,
            "validity_signal": val,
            "reliability_snips": find_snips(text, RE_REL, 3),
            "structure_snips": find_snips(text, RE_CFA, 3),
            "invariance_snips": find_snips(text, RE_INV, 3),
            "validity_snips": find_snips(text, RE_VAL, 3),
        },
        "jingle_jangle": {
            "warnings": jj
        }
    }
    return checklist

# ---------- UI ----------
uploaded = st.file_uploader("📄 Upload a PDF (Self-Control / Self-Regulation)", type=["pdf"])
if uploaded:
    with st.spinner("🔎 Reading & analyzing…"):
        text = extract_text(uploaded)
        rep = axis_selfcontrol_checklist(text)

    st.success("✅ Analysis complete")

    # --- Topline summary ---
    col1, col2, col3 = st.columns([1,1,1])
    with col1:
        st.metric("Definition present", "Yes" if rep["theory_scope"]["definition_present"] else "No")
        st.metric("Theory/mechanism", "Yes" if rep["theory_scope"]["theory_or_mechanism_stated"] else "No")
    with col2:
        st.metric("Reliability signal", "Yes" if rep["measurement_evidence"]["reliability_signal"] else "No")
        st.metric("Structure/fit signal", "Yes" if rep["measurement_evidence"]["structure_fit_signal"] else "No")
    with col3:
        st.metric("Invariance signal", "Yes" if rep["measurement_evidence"]["invariance_signal"] else "No")
        st.metric("Validity signal", "Yes" if rep["measurement_evidence"]["validity_signal"] else "No")

    # Tabs
    t1, t2, t3, t4, t5 = st.tabs(["Summary", "Theory & Scope", "Measures & Methods", "Jingle–Jangle", "Raw snippets"])

    with t1:
        st.subheader("Constructs detected")
        st.json(rep["operationalization"]["constructs_detected"])
        st.subheader("Component mapping (targets → measures)")
        st.json(rep["operationalization"]["component_map"])
        st.subheader("Study design cues")
        for sn in rep["operationalization"]["design_mentions"]:
            st.write("•", sn)

    with t2:
        st.subheader("Definition & boundaries")
        for sn in rep["theory_scope"]["definition_snippets"]:
            st.write("→", sn)
        st.markdown("**Boundary conditions mentioned?** " + ("Yes" if rep["theory_scope"]["boundary_conditions"] else "No"))
        st.subheader("Theory/mechanism snippets")
        for sn in rep["theory_scope"]["theory_snippets"]:
            st.write("→", sn)

    with t3:
        st.subheader("Measures detected")
        st.table([{k: v for k,v in m.items()} for m in rep["operationalization"]["measures_detected"]])
        st.subheader("Measurement evidence signals")
        for label, snips in [
            ("Reliability", rep["measurement_evidence"]["reliability_snips"]),
            ("Structure / CFA / IRT", rep["measurement_evidence"]["structure_snips"]),
            ("Invariance / DIF", rep["measurement_evidence"]["invariance_snips"]),
            ("Validity classes", rep["measurement_evidence"]["validity_snips"]),
        ]:
            if snips:
                with st.expander(label):
                    for s in snips: st.write("→", s)

    with t4:
        st.subheader("Jingle–Jangle / method-mix warnings")
        if rep["jingle_jangle"]["warnings"]:
            for w in rep["jingle_jangle"]["warnings"]:
                st.warning(w)
        else:
            st.info("No obvious jingle–jangle risks detected by heuristics.")

    with t5:
        st.subheader("Full checklist JSON")
        st.json(rep)
        # download
        st.download_button(
            label="⬇️ Download JSON",
            data=json.dumps(rep, indent=2).encode("utf-8"),
            file_name="construct_health_sc_srl.json",
            mime="application/json",
        )
