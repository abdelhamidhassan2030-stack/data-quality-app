import re
import json
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="Data Quality App", layout="wide")

# ========= Branding / Style =========
st.markdown("""
<style>
html, body, [class*="css"] {
    direction: rtl;
    text-align: right;
}

.block-container {
    padding-top: 1rem;
    max-width: 1180px;
}

.main-title {
    color: #0F5A36;
    font-weight: 800;
    font-size: 2.0rem;
    margin-bottom: 0.15rem;
}
.sub-title {
    color: #5F6B6D;
    font-weight: 700;
    font-size: 1.05rem;
    margin-bottom: 0.1rem;
}
.org-title {
    color: #0F5A36;
    font-weight: 700;
    font-size: 1rem;
    margin-bottom: 1rem;
}

.card {
    background: #F7FAF8;
    border: 1px solid #DDE8E2;
    border-radius: 16px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.card-title {
    color: #0F5A36;
    font-weight: 800;
    font-size: 1rem;
    margin-bottom: 4px;
}
.card-desc {
    color: #4C5A5D;
    font-size: 0.92rem;
    line-height: 1.55;
}

.section-title {
    color: #0F5A36;
    font-weight: 800;
    font-size: 1.25rem;
    margin: 0.5rem 0 0.75rem 0;
}
.note-box {
    background: #F7FAF8;
    border-right: 4px solid #0F5A36;
    border-radius: 12px;
    padding: 12px 14px;
    color: #304144;
    line-height: 1.7;
    margin-bottom: 1rem;
}
.stButton > button {
    width: 100%;
    border-radius: 14px;
    border: none;
    font-weight: 700;
    min-height: 50px;
    background: #0F5A36;
    color: white;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 12px 12px 0 0;
    padding: 10px 16px;
}
.stMetric {
    background: #F7FAF8;
    border: 1px solid #DDE8E2;
    padding: 10px 14px;
    border-radius: 14px;
}
.small-muted {
    color: #66777A;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False

LOGO_URL = "https://upload.wikimedia.org/wikipedia/ar/0/0b/Egyptian_Food_Bank.jpg"

GENERAL_DIMENSIONS = [
    "Completeness",
    "Uniqueness",
    "Validity",
    "Accuracy",
    "Consistency",
    "Timeliness",
    "Range",
    "Format/Pattern",
]

AR_LABELS = {
    "Completeness": "الاكتمال",
    "Uniqueness": "التفرد",
    "Validity": "الصلاحية",
    "Accuracy": "الدقة",
    "Consistency": "الاتساق",
    "Timeliness": "الحداثة",
    "Range": "النطاق",
    "Format/Pattern": "النمط أو الصيغة",
}

DIM_DESCRIPTIONS = {
    "Completeness": "فحص القيم الناقصة والحقول الإلزامية.",
    "Uniqueness": "فحص التكرار في الأعمدة التي يفترض أن تكون فريدة.",
    "Validity": "فحص القيم المسموحة أو غير المتسقة في الأعمدة الفئوية.",
    "Accuracy": "فحص المطابقة المرجعية عند وجود قيم صحيحة محددة مسبقًا.",
    "Consistency": "فحص العلاقة المنطقية بين عمود وآخر.",
    "Timeliness": "فحص التسلسل الزمني وصحة البداية والنهاية.",
    "Range": "فحص النطاق المنطقي أو الإحصائي للقيم الرقمية.",
    "Format/Pattern": "فحص شكل القيمة مثل أرقام الهاتف أو البطاقات أو الأكواد.",
}

# ========= Helpers =========
def read_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    xls = pd.ExcelFile(uploaded_file)
    if len(xls.sheet_names) == 1:
        return pd.read_excel(uploaded_file)
    sheet = st.selectbox("اختر الشيت", xls.sheet_names)
    return pd.read_excel(uploaded_file, sheet_name=sheet)

def safe_text(series):
    return series.fillna("").astype(str).str.strip()

def to_digits(x):
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return re.sub(r"\D", "", s)

def normalize_phone(x):
    d = to_digits(x)
    if len(d) == 10 and d.startswith("1"):
        return "0" + d
    return d

def add_issue(issues, row, column, dimension, issue, value="", severity="Medium", source="Auto"):
    issues.append({
        "Row": row,
        "Column": column,
        "Dimension": dimension,
        "Issue": issue,
        "Value": value,
        "Severity": severity,
        "Source": source,
    })

def pct(pass_count, total_count):
    if total_count == 0:
        return None
    return round((pass_count / total_count) * 100, 2)

def is_identifier_name(col_name):
    c = str(col_name).lower()
    keys = ["id", "_id", "uuid", "_uuid", "code", "كود", "national", "رقم قومي", "card", "بطاقة"]
    return any(k in c for k in keys)

def col_matches(col_name, patterns):
    c = str(col_name).lower()
    return any(p in c for p in patterns)

def detect_groups(df):
    groups = {
        "phone": [],
        "national_id": [],
        "card_like": [],
        "start": [],
        "end": [],
        "id_like": [],
        "categorical": [],
        "numeric": [],
        "required_candidates": [],
        "age_like": [],
    }
    for col in df.columns:
        c = str(col).lower()
        s = df[col]

        if col_matches(c, ["phone", "mobile", "تليفون", "هاتف", "موبايل"]):
            groups["phone"].append(col)

        if col_matches(c, ["national id", "national_id", "nid", "رقم قومي", "الرقم القومي"]):
            groups["national_id"].append(col)

        if col_matches(c, ["card", "بطاقة"]):
            groups["card_like"].append(col)

        if c == "start" or "start" in c or "بداية" in c:
            groups["start"].append(col)

        if c == "end" or "end" in c or "نهاية" in c:
            groups["end"].append(col)

        if c in ["id", "_id", "uuid", "_uuid"] or "uuid" in c:
            groups["id_like"].append(col)

        if "age" in c or "عمر" in c:
            groups["age_like"].append(col)

        num = pd.to_numeric(s, errors="coerce")
        if num.notna().mean() > 0.8:
            groups["numeric"].append(col)

        non_null = safe_text(s)
        non_null = non_null[non_null != ""]
        nunique = non_null.nunique()
        ratio = nunique / max(len(non_null), 1)
        name_hint = any(k in c for k in ["gender", "status", "type", "category", "نوع", "حالة", "جنس", "فئة"])
        if (name_hint or (nunique <= 6 and ratio < 0.2)) and not is_identifier_name(col) and col not in groups["numeric"] and col not in groups["phone"]:
            groups["categorical"].append(col)

        if (
            col_matches(c, ["name", "اسم", "phone", "mobile", "gender", "status", "type", "start", "end", "تليفون", "رقم قومي", "بطاقة"])
            or (s.notna().mean() > 0.95 and non_null.nunique() > 1 and not is_identifier_name(col))
        ):
            groups["required_candidates"].append(col)

    for k in groups:
        groups[k] = list(dict.fromkeys(groups[k]))
    return groups

# ========= Auto =========
def auto_assess(df):
    groups = detect_groups(df)
    issues = []
    scores = {k: None for k in GENERAL_DIMENSIONS}

    # Completeness
    checks = passed = 0
    for col in groups["required_candidates"]:
        ok = df[col].notna() & (safe_text(df[col]) != "")
        checks += len(df)
        passed += int(ok.sum())
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Completeness", "Missing value in important column", str(df.at[idx, col]), "High", "Auto")
    scores["Completeness"] = pct(passed, checks)

    # Uniqueness
    sub_scores = []
    for col in groups["id_like"] + groups["national_id"] + groups["card_like"]:
        vals = df[col].apply(to_digits) if col in groups["national_id"] + groups["card_like"] else safe_text(df[col])
        dup = vals.duplicated(keep=False) & (vals != "") & (vals.str.lower() != "nan")
        sub_scores.append(round((~dup).mean() * 100, 2))
        for idx in df.index[dup]:
            add_issue(issues, int(idx)+2, col, "Uniqueness", "Duplicate value in identifier column", str(df.at[idx, col]), "High", "Auto")
    scores["Uniqueness"] = round(sum(sub_scores)/len(sub_scores), 2) if sub_scores else None

    # Validity
    sub_scores = []
    for col in groups["categorical"]:
        s = safe_text(df[col])
        s_nonempty = s[s != ""]
        if len(s_nonempty) < 5:
            continue
        freq = s_nonempty.value_counts()
        if len(freq) < 2:
            continue
        dominant_ratio = freq.iloc[0] / len(s_nonempty)
        rare_values = set(freq[freq == 1].index.tolist())
        if dominant_ratio >= 0.5 and rare_values:
            ok = ~s.isin(rare_values) | (s == "")
            sub_scores.append(round(ok.mean() * 100, 2))
            for idx in df.index[~ok]:
                add_issue(issues, int(idx)+2, col, "Validity", "Suspicious rare value in categorical column", str(df.at[idx, col]), "Medium", "Auto")
    scores["Validity"] = round(sum(sub_scores)/len(sub_scores), 2) if sub_scores else None

    # Accuracy reserved for manual/reference checks
    scores["Accuracy"] = None

    # Consistency
    cols = list(df.columns)
    comment_cols = [c for c in cols if col_matches(c, ["comment", "explain", "تعليق", "توضيح", "سبب آخر", "أخرى", "اخري"])]
    checks = passed = 0
    for comment_col in comment_cols:
        idx = cols.index(comment_col)
        parent = cols[idx-1] if idx > 0 else None
        if parent:
            comment_filled = df[comment_col].notna() & (safe_text(df[comment_col]) != "")
            parent_missing = df[parent].isna() | (safe_text(df[parent]) == "")
            ok = ~(comment_filled & parent_missing)
            checks += len(df)
            passed += int(ok.sum())
            for i in df.index[~ok]:
                add_issue(issues, int(i)+2, f"{parent} -> {comment_col}", "Consistency", "Comment filled while parent field is empty", f"{df.at[i, parent]} -> {df.at[i, comment_col]}", "Medium", "Auto")
    scores["Consistency"] = pct(passed, checks)

    # Timeliness
    sub_scores = []
    if groups["start"] and groups["end"]:
        s_col = groups["start"][0]
        e_col = groups["end"][0]
        s_dt = pd.to_datetime(df[s_col], errors="coerce")
        e_dt = pd.to_datetime(df[e_col], errors="coerce")
        ok = (e_dt >= s_dt) | s_dt.isna() | e_dt.isna()
        sub_scores.append(round(ok.mean() * 100, 2))
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, f"{s_col} -> {e_col}", "Timeliness", "End time is before start time", f"{df.at[idx, s_col]} -> {df.at[idx, e_col]}", "High", "Auto")
        duration = (e_dt - s_dt).dt.total_seconds() / 60
        for idx in df.index[(duration > 30).fillna(False)]:
            add_issue(issues, int(idx)+2, f"{s_col} -> {e_col}", "Timeliness", "Interview duration > 30 minutes", round(duration.loc[idx], 2), "Medium", "Auto")
    scores["Timeliness"] = round(sum(sub_scores)/len(sub_scores), 2) if sub_scores else None

    # Range
    sub_scores = []
    for col in groups["numeric"]:
        num = pd.to_numeric(df[col], errors="coerce")
        valid = num.dropna()
        if len(valid) < 5:
            continue
        if col in groups["age_like"]:
            ok = num.between(0, 120) | num.isna()
            sub_scores.append(round(ok.mean() * 100, 2))
            for idx in df.index[~ok]:
                add_issue(issues, int(idx)+2, col, "Range", "Age is outside logical range [0 - 120]", str(df.at[idx, col]), "High", "Auto")
            continue
        if is_identifier_name(col) or col in groups["phone"] or col in groups["national_id"] or col in groups["card_like"]:
            continue
        q1 = valid.quantile(0.25)
        q3 = valid.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        ok = num.between(low, high) | num.isna()
        sub_scores.append(round(ok.mean() * 100, 2))
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Range", f"Outlier outside estimated range [{round(low,2)} - {round(high,2)}]", str(df.at[idx, col]), "Medium", "Auto")
    scores["Range"] = round(sum(sub_scores)/len(sub_scores), 2) if sub_scores else None

    # Format
    sub_scores = []
    for col in groups["phone"]:
        norm = df[col].apply(normalize_phone)
        ok = norm.apply(lambda x: x == "" or (len(x) == 11 and x.startswith("0")))
        sub_scores.append(round(ok.mean() * 100, 2))
        for idx in df.index[~ok & (norm != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "Invalid phone format", str(df.at[idx, col]), "High", "Auto")
    for col in groups["national_id"] + groups["card_like"]:
        digits = df[col].apply(to_digits)
        ok = digits.apply(lambda x: x == "" or len(x) >= 8)
        sub_scores.append(round(ok.mean() * 100, 2))
        for idx in df.index[~ok & (digits != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "Invalid card/ID format", str(df.at[idx, col]), "High", "Auto")
    scores["Format/Pattern"] = round(sum(sub_scores)/len(sub_scores), 2) if sub_scores else None

    return scores, issues

# ========= Manual =========
def default_rules():
    return {
        "required_cols": [],
        "unique_cols": [],
        "validity_col": "",
        "allowed_values": "",
        "accuracy_col": "",
        "accuracy_reference_values": "",
        "cons_if_col": "",
        "cons_if_val": "",
        "cons_then_col": "",
        "cons_then_val": "",
        "time_start_col": "",
        "time_end_col": "",
        "range_col": "",
        "min_val": "",
        "max_val": "",
        "format_col": "",
        "regex_pattern": "",
    }

def manual_assess(df, rules):
    issues = []
    scores = {k: None for k in GENERAL_DIMENSIONS}

    vals = []
    for col in rules["required_cols"]:
        ok = df[col].notna() & (safe_text(df[col]) != "")
        vals.append(round(ok.mean() * 100, 2))
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Completeness", "Missing value", str(df.at[idx, col]), "High", "Manual")
    scores["Completeness"] = round(sum(vals)/len(vals), 2) if vals else None

    vals = []
    for col in rules["unique_cols"]:
        s = safe_text(df[col])
        dup = s.duplicated(keep=False) & (s != "") & (s.str.lower() != "nan")
        vals.append(round((~dup).mean() * 100, 2))
        for idx in df.index[dup]:
            add_issue(issues, int(idx)+2, col, "Uniqueness", "Duplicate value", str(df.at[idx, col]), "High", "Manual")
    scores["Uniqueness"] = round(sum(vals)/len(vals), 2) if vals else None

    col = rules["validity_col"]
    allowed = [x.strip() for x in str(rules["allowed_values"]).split(",") if x.strip()]
    if col and allowed:
        s = safe_text(df[col])
        ok = s.isin(allowed) | (s == "")
        scores["Validity"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Validity", f"Value not in allowed list: {allowed}", str(df.at[idx, col]), "Medium", "Manual")

    col = rules["accuracy_col"]
    refs = [x.strip() for x in str(rules["accuracy_reference_values"]).split(",") if x.strip()]
    if col and refs:
        s = safe_text(df[col])
        ok = s.isin(refs) | (s == "")
        scores["Accuracy"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Accuracy", f"Value not matching reference values: {refs}", str(df.at[idx, col]), "Medium", "Manual")

    if_col = rules["cons_if_col"]
    then_col = rules["cons_then_col"]
    if if_col and then_col:
        if_val = str(rules["cons_if_val"]).strip()
        then_val = str(rules["cons_then_val"]).strip()
        applicable = safe_text(df[if_col]) == if_val
        ok = (~applicable) | (safe_text(df[then_col]) == then_val)
        scores["Consistency"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, f"{if_col} -> {then_col}", "Consistency", f"If {if_col}={if_val}, then {then_col}={then_val}", f"{df.at[idx, if_col]} -> {df.at[idx, then_col]}", "Medium", "Manual")

    s_col = rules["time_start_col"]
    e_col = rules["time_end_col"]
    if s_col and e_col:
        s_dt = pd.to_datetime(df[s_col], errors="coerce")
        e_dt = pd.to_datetime(df[e_col], errors="coerce")
        ok = (e_dt >= s_dt) | s_dt.isna() | e_dt.isna()
        scores["Timeliness"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, f"{s_col} -> {e_col}", "Timeliness", "End time is before start time", f"{df.at[idx, s_col]} -> {df.at[idx, e_col]}", "High", "Manual")

    col = rules["range_col"]
    min_val = str(rules["min_val"]).strip()
    max_val = str(rules["max_val"]).strip()
    if col and (min_val or max_val):
        num = pd.to_numeric(df[col], errors="coerce")
        ok = pd.Series([True] * len(df), index=df.index)
        if min_val:
            ok &= (num >= float(min_val)) | num.isna()
        if max_val:
            ok &= (num <= float(max_val)) | num.isna()
        scores["Range"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Range", f"Value outside range [{min_val or '-∞'} - {max_val or '∞'}]", str(df.at[idx, col]), "High", "Manual")

    col = rules["format_col"]
    regex = str(rules["regex_pattern"]).strip()
    if col and regex:
        s = safe_text(df[col])
        ok = s.apply(lambda x: bool(re.fullmatch(regex, x)) if x != "" else True)
        scores["Format/Pattern"] = round(ok.mean() * 100, 2)
        for idx in df.index[~ok]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", f"Value does not match pattern: {regex}", str(df.at[idx, col]), "High", "Manual")

    return scores, issues

def merge_scores(auto_scores=None, manual_scores=None):
    merged = {k: None for k in GENERAL_DIMENSIONS}
    for k in GENERAL_DIMENSIONS:
        vals = []
        if auto_scores and auto_scores.get(k) is not None:
            vals.append(auto_scores[k])
        if manual_scores and manual_scores.get(k) is not None:
            vals.append(manual_scores[k])
        merged[k] = round(sum(vals)/len(vals), 2) if vals else None
    return merged

def scores_to_df(scores):
    rows = []
    for dim in GENERAL_DIMENSIONS:
        rows.append({
            "Code": dim,
            "المعيار": AR_LABELS[dim],
            "النسبة %": scores.get(dim)
        })
    return pd.DataFrame(rows)

def overall_score(scores):
    vals = [v for v in scores.values() if v is not None]
    return round(sum(vals)/len(vals), 2) if vals else None

def render_dashboard(scores_df, issues_df):
    active_scores = scores_df.dropna(subset=["النسبة %"]).copy()
    c1, c2, c3 = st.columns(3)
    c1.metric("Average Score", f'{round(active_scores["النسبة %"].mean(), 2) if not active_scores.empty else 0}%')
    c2.metric("Active Dimensions", int(len(active_scores)))
    c3.metric("Issues Count", int(len(issues_df)))

    if not active_scores.empty:
        fig1 = plt.figure(figsize=(8, 4))
        plt.bar(active_scores["Code"], active_scores["النسبة %"])
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("Score %")
        plt.title("Score by Dimension")
        st.pyplot(fig1)

    if not issues_df.empty:
        dim_counts = issues_df["Dimension"].value_counts()
        fig2 = plt.figure(figsize=(8, 4))
        plt.bar(dim_counts.index, dim_counts.values)
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("Issues Count")
        plt.title("Issues by Dimension")
        st.pyplot(fig2)

        sev_counts = issues_df["Severity"].value_counts()
        fig3 = plt.figure(figsize=(6, 4))
        plt.pie(sev_counts.values, labels=sev_counts.index, autopct="%1.1f%%")
        plt.title("Issues by Severity")
        st.pyplot(fig3)

# ========= Header =========
h1, h2 = st.columns([1, 6])
with h1:
    st.image(LOGO_URL, width=100)
with h2:
    st.markdown('<div class="main-title">تطبيق تقييم جودة البيانات</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">إدارة الرصد</div>', unsafe_allow_html=True)
    st.markdown('<div class="org-title">بنك الطعام المصري</div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader("📁 ارفع ملف Excel أو CSV", type=["csv", "xlsx"])

if uploaded_file:
    df = read_file(uploaded_file)
    cols = list(df.columns)

    if "rules_ui_final" not in st.session_state or st.session_state.get("cols_ui_final") != cols:
        st.session_state["rules_ui_final"] = default_rules()
        st.session_state["cols_ui_final"] = cols

    st.markdown('<div class="section-title">🔎 معاينة البيانات</div>', unsafe_allow_html=True)
    st.dataframe(df.head(20), use_container_width=True)

    st.markdown('<div class="section-title">📌 مستوى المعايير العامة</div>', unsafe_allow_html=True)
    cards = st.columns(4)
    for i, dim in enumerate(GENERAL_DIMENSIONS):
        with cards[i % 4]:
            st.markdown(
                f'<div class="card"><div class="card-title">{i+1}. {dim}</div><div class="card-desc">{AR_LABELS[dim]}<br>{DIM_DESCRIPTIONS[dim]}</div></div>',
                unsafe_allow_html=True
            )

    mode = st.radio("طريقة التقييم", ["تلقائي", "يدوي"], horizontal=True)

    if mode == "تلقائي":
        st.markdown('<div class="note-box">سيتم في التقييم التلقائي مراجعة أهم عناصر جودة البيانات بشكل آلي، مثل القيم الناقصة، وتكرار المعرفات، وصيغة أرقام الهاتف أو البطاقات، واتساق التوقيت بين البداية والنهاية، والنطاق المنطقي لبعض القيم الرقمية، مع التركيز على المشكلات الأساسية الأكثر شيوعًا.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="note-box">في التقييم اليدوي يمكنك تحديد قواعد الفحص بنفسك وفقًا للمعايير العامة، مثل الأعمدة الإلزامية، والقيم المسموحة، والتفرد، والنطاق، والنمط، والاتساق، وبذلك يصبح التقييم أكثر دقة وملاءمة لطبيعة الملف الذي تعمل عليه.</div>', unsafe_allow_html=True)

        rules = st.session_state["rules_ui_final"]
        left, right = st.columns(2)

        with left:
            rules["required_cols"] = st.multiselect("Completeness - الأعمدة الإلزامية", cols, default=rules["required_cols"])
            rules["unique_cols"] = st.multiselect("Uniqueness - أعمدة التفرد", cols, default=rules["unique_cols"])
            rules["validity_col"] = st.selectbox("Validity - عمود القيم المسموحة", [""] + cols, index=([""] + cols).index(rules["validity_col"]) if rules["validity_col"] in ([""] + cols) else 0)
            rules["allowed_values"] = st.text_input("Validity - القيم المسموحة", value=rules["allowed_values"])
            rules["accuracy_col"] = st.selectbox("Accuracy - العمود المرجعي", [""] + cols, index=([""] + cols).index(rules["accuracy_col"]) if rules["accuracy_col"] in ([""] + cols) else 0)
            rules["accuracy_reference_values"] = st.text_input("Accuracy - القيم المرجعية", value=rules["accuracy_reference_values"])

        with right:
            rules["cons_if_col"] = st.selectbox("Consistency - إذا كان العمود", [""] + cols, index=([""] + cols).index(rules["cons_if_col"]) if rules["cons_if_col"] in ([""] + cols) else 0)
            rules["cons_if_val"] = st.text_input("Consistency - يساوي", value=rules["cons_if_val"])
            rules["cons_then_col"] = st.selectbox("Consistency - فإن العمود", [""] + cols, index=([""] + cols).index(rules["cons_then_col"]) if rules["cons_then_col"] in ([""] + cols) else 0)
            rules["cons_then_val"] = st.text_input("Consistency - يجب أن يساوي", value=rules["cons_then_val"])

            rules["time_start_col"] = st.selectbox("Timeliness - عمود البداية", [""] + cols, index=([""] + cols).index(rules["time_start_col"]) if rules["time_start_col"] in ([""] + cols) else 0)
            rules["time_end_col"] = st.selectbox("Timeliness - عمود النهاية", [""] + cols, index=([""] + cols).index(rules["time_end_col"]) if rules["time_end_col"] in ([""] + cols) else 0)

            rules["range_col"] = st.selectbox("Range - العمود الرقمي", [""] + cols, index=([""] + cols).index(rules["range_col"]) if rules["range_col"] in ([""] + cols) else 0)
            rules["min_val"] = st.text_input("Range - أقل قيمة", value=rules["min_val"])
            rules["max_val"] = st.text_input("Range - أعلى قيمة", value=rules["max_val"])

        rules["format_col"] = st.selectbox("Format/Pattern - عمود النمط", [""] + cols, index=([""] + cols).index(rules["format_col"]) if rules["format_col"] in ([""] + cols) else 0)
        rules["regex_pattern"] = st.text_input("Format/Pattern - Regex", value=rules["regex_pattern"], placeholder=r"^\d{11}$")
        st.session_state["rules_ui_final"] = rules

    if st.button("🚀 تشغيل التقييم"):
        auto_scores = auto_issues = None
        manual_scores = manual_issues = None

        if mode == "تلقائي":
            auto_scores, auto_issues = auto_assess(df)
            merged = auto_scores
            issues_df = pd.DataFrame(auto_issues)
        else:
            manual_scores, manual_issues = manual_assess(df, st.session_state["rules_ui_final"])
            merged = manual_scores
            issues_df = pd.DataFrame(manual_issues)

        if not issues_df.empty:
            issues_df = issues_df.drop_duplicates()

        scores_df = scores_to_df(merged)
        ov = overall_score(merged)

        results_tab, charts_tab = st.tabs(["📋 النتائج", "📈 الرسوم البيانية لجودة البيانات"])

        with results_tab:
            st.markdown('<div class="section-title">📈 النتائج</div>', unsafe_allow_html=True)
            st.metric("النسبة الكلية لجودة البيانات", f"{ov}%" if ov is not None else "لا توجد قواعد مفعلة")
            st.dataframe(scores_df, use_container_width=True)

            st.markdown('<div class="section-title">⚠️ المشكلات المكتشفة</div>', unsafe_allow_html=True)
            if issues_df.empty:
                st.success("لم يتم اكتشاف مشكلات وفق القواعد الحالية.")
            else:
                st.dataframe(issues_df, use_container_width=True)
                st.download_button("⬇️ تحميل تقرير المشكلات CSV", issues_df.to_csv(index=False).encode("utf-8-sig"), "efb_dq_issues.csv", "text/csv")

            st.download_button("⬇️ تحميل نسب المعايير CSV", scores_df.to_csv(index=False).encode("utf-8-sig"), "efb_dq_scores.csv", "text/csv")

            if mode == "يدوي":
                st.download_button("⬇️ تحميل الإعدادات اليدوية JSON", json.dumps(st.session_state["rules_ui_final"], ensure_ascii=False, indent=2).encode("utf-8"), "efb_dq_rules.json", "application/json")

        with charts_tab:
            st.markdown('<div class="section-title">📈 الرسوم البيانية لجودة البيانات</div>', unsafe_allow_html=True)
            render_dashboard(scores_df, issues_df)
