
import re
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="Data Quality Assessment App", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] {
    direction: rtl;
    text-align: right;
}
.block-container {padding-top: 1rem;}
</style>
""", unsafe_allow_html=True)

st.title("📊 تطبيق تقييم جودة البيانات")
st.caption("فحص تلقائي ذكي + داش بورد لتحليل جودة البيانات")

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
    s = re.sub(r"\D", "", s)
    return s

def is_valid_phone_digits(x):
    return x == "" or (len(x) == 11 and x.startswith("0")) or (len(x) == 10 and x.startswith("1"))

def normalize_phone_for_dup(x):
    if x == "":
        return ""
    if len(x) == 10 and x.startswith("1"):
        return "0" + x
    return x

def col_matches(col_name, patterns):
    col = str(col_name).strip().lower()
    return any(p in col for p in patterns)

def detect_column_groups(df):
    groups = {
        "phone": [],
        "national_id": [],
        "start": [],
        "end": [],
        "uuid": [],
        "required_candidates": [],
        "numeric": []
    }
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
        if "_uuid" in c or c == "uuid":
            groups["uuid"].append(col)
        if col_matches(c, ["تليفون", "رقم قومي", "المحافظة", "الجمعية", "phone", "mobile", "governorate", "association", "start", "end"]):
            groups["required_candidates"].append(col)
        num = pd.to_numeric(df[col], errors="coerce")
        if num.notna().mean() > 0.8:
            groups["numeric"].append(col)
    return groups

def add_issue(issues, row, column, dimension, issue, value, severity="Medium"):
    issues.append({
        "Row": row,
        "Column": column,
        "Dimension": dimension,
        "Issue": issue,
        "Value": value,
        "Severity": severity
    })

def auto_assess(df):
    issues = []
    scores = {}
    groups = detect_column_groups(df)

    completeness_issues = 0
    completeness_checks = 0
    for col in groups["required_candidates"]:
        s = df[col]
        mask = s.isna() | (s.astype(str).str.strip() == "")
        completeness_issues += int(mask.sum())
        completeness_checks += len(df)
        for idx in df.index[mask]:
            add_issue(issues, int(idx)+2, col, "Completeness", "قيمة ناقصة في عمود أساسي مرشح تلقائيًا", "" if pd.isna(df.at[idx, col]) else str(df.at[idx, col]), "High")
    scores["Completeness"] = round((1 - completeness_issues / completeness_checks) * 100, 2) if completeness_checks else 100.0

    uniq_cols = groups["uuid"] + groups["phone"] + groups["national_id"]
    uniq_scores = []
    for col in uniq_cols:
        if col in groups["phone"]:
            normalized = df[col].apply(to_digits).apply(normalize_phone_for_dup)
        elif col in groups["national_id"]:
            normalized = df[col].apply(to_digits)
        else:
            normalized = df[col].astype(str).str.strip()
        dup_mask = normalized.duplicated(keep=False) & (normalized != "") & (normalized.str.lower() != "nan")
        uniq_scores.append(round((~dup_mask).mean() * 100, 2))
        for idx in df.index[dup_mask]:
            add_issue(issues, int(idx)+2, col, "Uniqueness", "قيمة مكررة في عمود معرف أو شبه معرف", str(df.at[idx, col]), "High")
    scores["Uniqueness"] = round(sum(uniq_scores) / len(uniq_scores), 2) if uniq_scores else 100.0

    format_scores = []
    validity_scores = []
    for col in groups["phone"]:
        digits = df[col].apply(to_digits)
        valid_phone = digits.apply(is_valid_phone_digits)
        format_scores.append(round(valid_phone.mean() * 100, 2))
        validity_scores.append(round(valid_phone.mean() * 100, 2))
        for idx in df.index[~valid_phone & (digits != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "رقم تليفون غير صحيح", str(df.at[idx, col]), "High")

    for col in groups["national_id"]:
        digits = df[col].apply(to_digits)
        valid_14 = digits.apply(lambda x: len(x) == 14 or x == "")
        format_scores.append(round(valid_14.mean() * 100, 2))
        validity_scores.append(round(valid_14.mean() * 100, 2))
        for idx in df.index[~valid_14 & (digits != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "الرقم القومي لا يتكون من 14 رقمًا", str(df.at[idx, col]), "High")

    timeliness_scores = []
    if groups["start"] and groups["end"]:
        start_col = groups["start"][0]
        end_col = groups["end"][0]
        start_dt = pd.to_datetime(df[start_col], errors="coerce")
        end_dt = pd.to_datetime(df[end_col], errors="coerce")

        chrono_valid = ((end_dt >= start_dt) | start_dt.isna() | end_dt.isna())
        timeliness_scores.append(round(chrono_valid.mean() * 100, 2))
        for idx in df.index[~chrono_valid]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "وقت النهاية أقدم من وقت البداية", f"{df.at[idx, start_col]} -> {df.at[idx, end_col]}", "High")

        duration_min = (end_dt - start_dt).dt.total_seconds() / 60
        over_30 = duration_min > 30
        over_60 = duration_min > 60
        for idx in df.index[over_30.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة المقابلة أكبر من 30 دقيقة وتحتاج مراجعة", round(duration_min.loc[idx], 2), "Medium")
        for idx in df.index[over_60.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة المقابلة أكبر من 60 دقيقة وتعتبر حالة شاذة قوية", round(duration_min.loc[idx], 2), "High")
    scores["Timeliness"] = round(sum(timeliness_scores) / len(timeliness_scores), 2) if timeliness_scores else 100.0

    range_scores = []
    for col in groups["numeric"]:
        num = pd.to_numeric(df[col], errors="coerce")
        valid = num.dropna()
        if len(valid) < 8:
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

    cols = list(df.columns)
    comment_cols = [c for c in cols if col_matches(c, ["تعليق", "سبب آخر", "اخري", "أخرى", "توضيح", "explain", "comment"])]
    consistency_checks = 0
    consistency_bad = 0
    for comment_col in comment_cols:
        idx_comment = cols.index(comment_col)
        parent_col = cols[idx_comment - 1] if idx_comment > 0 else None
        if parent_col:
            comment_filled = df[comment_col].notna() & (df[comment_col].astype(str).str.strip() != "")
            parent_missing = df[parent_col].isna() | (df[parent_col].astype(str).str.strip() == "")
            inconsistent = comment_filled & parent_missing
            consistency_checks += len(df)
            consistency_bad += int(inconsistent.sum())
            for idx in df.index[inconsistent]:
                add_issue(issues, int(idx)+2, f"{parent_col} -> {comment_col}", "Consistency", "حقل التعليق ممتلئ بينما السؤال السابق فارغ", f"{df.at[idx, parent_col]} -> {df.at[idx, comment_col]}", "Medium")
    scores["Consistency"] = round((1 - consistency_bad / consistency_checks) * 100, 2) if consistency_checks else 100.0

    scores["Accuracy"] = 100.0
    scores["Validity"] = round(sum(validity_scores) / len(validity_scores), 2) if validity_scores else 100.0
    scores["Format/Pattern"] = round(sum(format_scores) / len(format_scores), 2) if format_scores else 100.0

    overall = round(sum(scores.values()) / len(scores), 2) if scores else 100.0

    scores_df = pd.DataFrame({"المعيار": list(scores.keys()), "النسبة %": list(scores.values())})
    issues_df = pd.DataFrame(issues).drop_duplicates() if issues else pd.DataFrame(columns=["Row","Column","Dimension","Issue","Value","Severity"])
    return scores_df, issues_df, overall, groups

def render_dashboard(scores_df, issues_df):
    st.subheader("📊 داش بورد جودة البيانات")

    c1, c2, c3 = st.columns(3)
    c1.metric("عدد المشكلات", int(len(issues_df)))
    c2.metric("عدد المعايير المفحوصة", int(len(scores_df)))
    avg_score = round(scores_df["النسبة %"].mean(), 2) if not scores_df.empty else 100.0
    c3.metric("متوسط نسب المعايير", f"{avg_score}%")

    if not scores_df.empty:
        fig1 = plt.figure(figsize=(8, 4))
        plt.bar(scores_df["المعيار"], scores_df["النسبة %"])
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("النسبة %")
        plt.title("نسبة كل معيار من معايير جودة البيانات")
        st.pyplot(fig1)

    if not issues_df.empty:
        dim_counts = issues_df["Dimension"].value_counts().reset_index()
        dim_counts.columns = ["Dimension", "Count"]
        fig2 = plt.figure(figsize=(8, 4))
        plt.bar(dim_counts["Dimension"], dim_counts["Count"])
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("عدد المشكلات")
        plt.title("توزيع المشكلات حسب المعيار")
        st.pyplot(fig2)

        sev_counts = issues_df["Severity"].value_counts().reset_index()
        sev_counts.columns = ["Severity", "Count"]
        fig3 = plt.figure(figsize=(6, 4))
        plt.pie(sev_counts["Count"], labels=sev_counts["Severity"], autopct="%1.1f%%")
        plt.title("توزيع المشكلات حسب الشدة")
        st.pyplot(fig3)

        top_cols = issues_df["Column"].value_counts().head(10).reset_index()
        top_cols.columns = ["Column", "Count"]
        fig4 = plt.figure(figsize=(8, 4))
        plt.bar(top_cols["Column"], top_cols["Count"])
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("عدد المشكلات")
        plt.title("أكثر الأعمدة التي تحتوي على مشكلات")
        st.pyplot(fig4)

uploaded_file = st.file_uploader("📁 ارفع ملف Excel أو CSV", type=["csv", "xlsx"])

if uploaded_file:
    df = read_file(uploaded_file)

    st.subheader("🔍 معاينة البيانات")
    st.dataframe(df.head(20), use_container_width=True)

    with st.expander("📌 الأعمدة المكتشفة تلقائيًا", expanded=False):
        groups = detect_column_groups(df)
        for k, v in groups.items():
            st.write(f"**{k}:** {v if v else 'لا يوجد'}")

    if st.button("🚀 تشغيل الفحص التلقائي", type="primary"):
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
                "auto_detected_issues.csv",
                "text/csv"
            )
        st.download_button(
            "⬇️ تحميل نسب المعايير CSV",
            scores_df.to_csv(index=False).encode("utf-8-sig"),
            "auto_quality_scores.csv",
            "text/csv"
        )
