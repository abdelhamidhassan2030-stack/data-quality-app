
import re
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="Data Quality Assessment App v3", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] {
    direction: rtl;
    text-align: right;
}
.block-container {padding-top: 1rem;}
</style>
""", unsafe_allow_html=True)

st.title("📊 تطبيق تقييم جودة البيانات - نسخة محسنة")
st.caption("فحص تلقائي ذكي + داش بورد + تقليل الإنذارات الخاطئة")

def read_file(uploaded_file):
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    xls = pd.ExcelFile(uploaded_file)
    if len(xls.sheet_names) == 1:
        return pd.read_excel(uploaded_file)
    sheet = st.selectbox("اختر الشيت", xls.sheet_names)
    return pd.read_excel(uploaded_file, sheet_name=sheet)

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

def is_valid_phone(x):
    d = to_digits(x)
    return d == "" or (len(d) == 11 and d.startswith("0")) or (len(d) == 10 and d.startswith("1"))

def col_matches(col_name, patterns):
    col = str(col_name).strip().lower()
    return any(p in col for p in patterns)

def add_issue(issues, row, column, dimension, issue, value, severity="Medium"):
    issues.append({
        "Row": row,
        "Column": column,
        "Dimension": dimension,
        "Issue": issue,
        "Value": value,
        "Severity": severity
    })

def detect_column_groups(df):
    groups = {
        "phone": [],
        "national_id": [],
        "start": [],
        "end": [],
        "uuid": [],
        "categorical": [],
        "numeric": [],
        "required_candidates": []
    }
    n = len(df)

    for col in df.columns:
        c = str(col).lower()

        if col_matches(c, ["تليفون", "هاتف", "موبايل", "phone", "mobile"]):
            groups["phone"].append(col)
        if col_matches(c, ["رقم قومي", "الرقم القومي", "national id", "national_id", "nid"]):
            groups["national_id"].append(col)
        if c == "start" or "start" in c or "بداية" in c:
            groups["start"].append(col)
        if c == "end" or "end" in c or "نهاية" in c:
            groups["end"].append(col)
        if "_uuid" in c or c == "uuid" or c == "_id" or c == "id":
            groups["uuid"].append(col)

        s = df[col]
        non_null = s.dropna()
        nunique = non_null.astype(str).nunique()

        if non_null.shape[0] > 0:
            if nunique <= 10:
                groups["categorical"].append(col)

            num = pd.to_numeric(s, errors="coerce")
            if num.notna().mean() > 0.8:
                groups["numeric"].append(col)

            # candidate required fields: meaningful coverage, common business identifiers, key labels
            if (
                col_matches(c, ["name", "اسم", "تليفون", "هاتف", "موبايل", "phone", "mobile",
                                 "رقم قومي", "national", "gender", "type", "status", "start", "end"])
                or (s.notna().mean() > 0.9 and nunique > 1)
            ):
                groups["required_candidates"].append(col)

    # deduplicate lists preserving order
    for k in groups:
        groups[k] = list(dict.fromkeys(groups[k]))
    return groups

def auto_assess(df):
    issues = []
    scores = {}
    groups = detect_column_groups(df)
    total_rows = len(df)

    # 1) Completeness on likely mandatory columns
    completeness_checks = 0
    completeness_pass = 0
    for col in groups["required_candidates"]:
        s = df[col]
        non_empty = s.notna() & (s.astype(str).str.strip() != "")
        completeness_checks += len(df)
        completeness_pass += int(non_empty.sum())
        for idx in df.index[~non_empty]:
            add_issue(issues, int(idx)+2, col, "Completeness", "قيمة ناقصة في عمود أساسي", "" if pd.isna(df.at[idx, col]) else str(df.at[idx, col]), "High")
    scores["Completeness"] = round((completeness_pass / completeness_checks) * 100, 2) if completeness_checks else 100.0

    # 2) Uniqueness on explicit identifier-like columns
    uniq_scores = []
    for col in groups["uuid"] + groups["national_id"]:
        series = df[col].astype(str).str.strip() if col in groups["uuid"] else df[col].apply(to_digits)
        dup_mask = series.duplicated(keep=False) & (series != "") & (series.str.lower() != "nan")
        uniq_scores.append(round((~dup_mask).mean() * 100, 2))
        for idx in df.index[dup_mask]:
            add_issue(issues, int(idx)+2, col, "Uniqueness", "قيمة مكررة في عمود معرف", str(df.at[idx, col]), "High")

    # also check columns literally named ID even if not caught above
    scores["Uniqueness"] = round(sum(uniq_scores) / len(uniq_scores), 2) if uniq_scores else 100.0

    # 3) Validity on low-cardinality categorical columns
    validity_scores = []
    for col in groups["categorical"]:
        s = df[col].dropna().astype(str).str.strip()
        if len(s) < 5:
            continue
        freq = s.value_counts(dropna=True)
        if len(freq) < 2:
            continue
        # Rare-category heuristic: values with frequency 1 in a low-cardinality field are suspicious
        if len(freq) <= 6:
            rare_values = set(freq[freq == 1].index.tolist())
            if rare_values:
                full = df[col].astype(str).str.strip()
                valid_mask = ~full.isin(rare_values) | df[col].isna() | (full == "")
                validity_scores.append(round(valid_mask.mean() * 100, 2))
                for idx in df.index[~valid_mask]:
                    add_issue(issues, int(idx)+2, col, "Validity", "قيمة نادرة أو غير متسقة محتملة في عمود فئوي", str(df.at[idx, col]), "Medium")
    scores["Validity"] = round(sum(validity_scores) / len(validity_scores), 2) if validity_scores else 100.0

    # 4) Format/Pattern
    format_scores = []

    # Phones: accept with or without leading zero; do not flag as error if missing zero
    for col in groups["phone"]:
        norm = df[col].apply(normalize_phone)
        valid = norm.apply(lambda x: x == "" or (len(x) == 11 and x.startswith("0")))
        format_scores.append(round(valid.mean() * 100, 2))
        for idx in df.index[~valid & (norm != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "رقم تليفون غير صحيح", str(df.at[idx, col]), "High")

    for col in groups["national_id"]:
        digits = df[col].apply(to_digits)
        valid = digits.apply(lambda x: x == "" or len(x) == 14)
        format_scores.append(round(valid.mean() * 100, 2))
        for idx in df.index[~valid & (digits != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "الرقم القومي لا يتكون من 14 رقمًا", str(df.at[idx, col]), "High")

    scores["Format/Pattern"] = round(sum(format_scores) / len(format_scores), 2) if format_scores else 100.0

    # 5) Timeliness / chronology
    time_scores = []
    if groups["start"] and groups["end"]:
        start_col = groups["start"][0]
        end_col = groups["end"][0]
        start_dt = pd.to_datetime(df[start_col], errors="coerce")
        end_dt = pd.to_datetime(df[end_col], errors="coerce")
        valid = ((end_dt >= start_dt) | start_dt.isna() | end_dt.isna())
        time_scores.append(round(valid.mean() * 100, 2))
        for idx in df.index[~valid]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "وقت النهاية أقدم من وقت البداية", f"{df.at[idx, start_col]} -> {df.at[idx, end_col]}", "High")

        duration_min = (end_dt - start_dt).dt.total_seconds() / 60
        over_30 = duration_min > 30
        over_60 = duration_min > 60
        for idx in df.index[over_30.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة طويلة تحتاج مراجعة (>30 دقيقة)", round(duration_min.loc[idx], 2), "Medium")
        for idx in df.index[over_60.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة شاذة قوية (>60 دقيقة)", round(duration_min.loc[idx], 2), "High")
    scores["Timeliness"] = round(sum(time_scores) / len(time_scores), 2) if time_scores else 100.0

    # 6) Range on numeric columns
    range_scores = []
    for col in groups["numeric"]:
        num = pd.to_numeric(df[col], errors="coerce")
        valid = num.dropna()
        if len(valid) < 5:
            continue

        # Business-friendly rule for common age-like columns
        cname = str(col).lower()
        if "age" in cname or "عمر" in cname:
            mask = num.between(0, 120) | num.isna()
            range_scores.append(round(mask.mean() * 100, 2))
            for idx in df.index[~mask]:
                add_issue(issues, int(idx)+2, col, "Range", "قيمة العمر خارج النطاق المنطقي [0 - 120]", str(df.at[idx, col]), "High")
            continue

        q1 = valid.quantile(0.25)
        q3 = valid.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        mask = num.between(low, high) | num.isna()
        range_scores.append(round(mask.mean() * 100, 2))
        for idx in df.index[~mask]:
            add_issue(issues, int(idx)+2, col, "Range", f"قيمة شاذة خارج النطاق الإحصائي التقريبي [{round(low,2)} - {round(high,2)}]", str(df.at[idx, col]), "Medium")
    scores["Range"] = round(sum(range_scores) / len(range_scores), 2) if range_scores else 100.0

    # 7) Consistency heuristic
    cols = list(df.columns)
    comment_cols = [c for c in cols if col_matches(c, ["تعليق", "سبب آخر", "اخري", "أخرى", "توضيح", "explain", "comment"])]
    consistency_checks = 0
    consistency_pass = 0
    for comment_col in comment_cols:
        idx_comment = cols.index(comment_col)
        parent_col = cols[idx_comment - 1] if idx_comment > 0 else None
        if parent_col:
            comment_filled = df[comment_col].notna() & (df[comment_col].astype(str).str.strip() != "")
            parent_missing = df[parent_col].isna() | (df[parent_col].astype(str).str.strip() == "")
            valid = ~(comment_filled & parent_missing)
            consistency_checks += len(df)
            consistency_pass += int(valid.sum())
            for idx in df.index[~valid]:
                add_issue(issues, int(idx)+2, f"{parent_col} -> {comment_col}", "Consistency", "حقل التعليق ممتلئ بينما السؤال السابق فارغ", f"{df.at[idx, parent_col]} -> {df.at[idx, comment_col]}", "Medium")
    scores["Consistency"] = round((consistency_pass / consistency_checks) * 100, 2) if consistency_checks else 100.0

    # 8) Accuracy placeholder
    scores["Accuracy"] = 100.0

    overall = round(sum(scores.values()) / len(scores), 2) if scores else 100.0
    scores_df = pd.DataFrame({"المعيار": list(scores.keys()), "النسبة %": list(scores.values())})
    issues_df = pd.DataFrame(issues).drop_duplicates() if issues else pd.DataFrame(columns=["Row","Column","Dimension","Issue","Value","Severity"])
    return scores_df, issues_df, overall, groups

def render_dashboard(scores_df, issues_df):
    st.subheader("📊 داش بورد جودة البيانات")

    c1, c2, c3 = st.columns(3)
    c1.metric("عدد المشكلات", int(len(issues_df)))
    c2.metric("عدد المعايير", int(len(scores_df)))
    c3.metric("متوسط نسب المعايير", f'{round(scores_df["النسبة %"].mean(),2) if not scores_df.empty else 100.0}%')

    if not scores_df.empty:
        fig = plt.figure(figsize=(8,4))
        plt.bar(scores_df["المعيار"], scores_df["النسبة %"])
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("النسبة %")
        plt.title("نسبة كل معيار")
        st.pyplot(fig)

    if not issues_df.empty:
        dim_counts = issues_df["Dimension"].value_counts()
        fig = plt.figure(figsize=(8,4))
        plt.bar(dim_counts.index, dim_counts.values)
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("عدد المشكلات")
        plt.title("المشكلات حسب المعيار")
        st.pyplot(fig)

        sev_counts = issues_df["Severity"].value_counts()
        fig = plt.figure(figsize=(6,4))
        plt.pie(sev_counts.values, labels=sev_counts.index, autopct="%1.1f%%")
        plt.title("توزيع الشدة")
        st.pyplot(fig)

        top_cols = issues_df["Column"].value_counts().head(10)
        fig = plt.figure(figsize=(8,4))
        plt.bar(top_cols.index, top_cols.values)
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("عدد المشكلات")
        plt.title("أكثر الأعمدة التي فيها مشكلات")
        st.pyplot(fig)

uploaded_file = st.file_uploader("📁 ارفع ملف Excel أو CSV", type=["csv", "xlsx"])

if uploaded_file:
    df = read_file(uploaded_file)

    st.subheader("🔍 معاينة البيانات")
    st.dataframe(df.head(20), use_container_width=True)

    with st.expander("📌 الأعمدة المكتشفة تلقائيًا", expanded=False):
        groups = detect_column_groups(df)
        for k, v in groups.items():
            st.write(f"**{k}:** {v if v else 'لا يوجد'}")

    if st.button("🚀 تشغيل الفحص التلقائي المحسن", type="primary"):
        scores_df, issues_df, overall, groups = auto_assess(df)

        st.subheader("📈 النتائج")
        st.metric("🎯 النسبة الكلية لجودة البيانات", f"{overall}%")
        st.dataframe(scores_df, use_container_width=True)

        render_dashboard(scores_df, issues_df)

        st.subheader("⚠️ المشكلات المكتشفة")
        if issues_df.empty:
            st.success("لم يتم اكتشاف مشكلات تلقائية وفق القواعد الحالية.")
        else:
            st.dataframe(issues_df, use_container_width=True)
            st.download_button(
                "⬇️ تحميل تقرير المشكلات CSV",
                issues_df.to_csv(index=False).encode("utf-8-sig"),
                "improved_auto_detected_issues.csv",
                "text/csv"
            )
        st.download_button(
            "⬇️ تحميل نسب المعايير CSV",
            scores_df.to_csv(index=False).encode("utf-8-sig"),
            "improved_auto_quality_scores.csv",
            "text/csv"
        )
