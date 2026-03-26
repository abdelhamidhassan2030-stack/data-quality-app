
import re
import pandas as pd
import streamlit as st

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
st.caption("نسخة عامة تدعم الفحص اليدوي + الاكتشاف التلقائي للمشكلات الشائعة")

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

def score_from_issue_count(total_rows, issue_count):
    if total_rows == 0:
        return 100.0
    return round(((total_rows - issue_count) / total_rows) * 100, 2)

def add_issue(issues, row, column, dimension, issue, value):
    issues.append({
        "Row": row,
        "Column": column,
        "Dimension": dimension,
        "Issue": issue,
        "Value": value
    })

def auto_assess(df):
    issues = []
    scores = {}
    groups = detect_column_groups(df)
    total_rows = len(df)

    # 1) Completeness on likely mandatory columns
    completeness_issues = 0
    for col in groups["required_candidates"]:
        s = df[col]
        mask = s.isna() | (s.astype(str).str.strip() == "")
        completeness_issues += int(mask.sum())
        for idx in df.index[mask]:
            add_issue(issues, int(idx)+2, col, "Completeness", "قيمة ناقصة في عمود مرشح كعمود أساسي", "" if pd.isna(df.at[idx, col]) else str(df.at[idx, col]))
    checks = max(total_rows * max(len(groups["required_candidates"]), 1), 1)
    if groups["required_candidates"]:
        scores["Completeness"] = round((1 - completeness_issues / checks) * 100, 2)
    else:
        scores["Completeness"] = 100.0

    # 2) Uniqueness on key identifiers
    uniq_cols = groups["uuid"] + groups["phone"] + groups["national_id"]
    uniq_scores = []
    for col in uniq_cols:
        normalized = df[col].apply(to_digits) if col in groups["phone"] + groups["national_id"] else df[col].astype(str).str.strip()
        dup_mask = normalized.duplicated(keep=False) & (normalized != "") & (normalized.str.lower() != "nan")
        uniq_scores.append(round((~dup_mask).mean() * 100, 2))
        for idx in df.index[dup_mask]:
            add_issue(issues, int(idx)+2, col, "Uniqueness", "قيمة مكررة في عمود يفترض أن يكون معرفًا أو شبه معرف", str(df.at[idx, col]))
    scores["Uniqueness"] = round(sum(uniq_scores) / len(uniq_scores), 2) if uniq_scores else 100.0

    # 3) Format/Pattern and Validity for phones
    format_scores = []
    validity_scores = []

    for col in groups["phone"]:
        digits = df[col].apply(to_digits)
        valid_11 = digits.apply(lambda x: (len(x) == 11 and x.startswith("0")) or x == "")
        likely_missing_zero = digits.apply(lambda x: len(x) == 10 and x.startswith("1"))
        format_scores.append(round(valid_11.mean() * 100, 2))
        validity_scores.append(round(valid_11.mean() * 100, 2))

        for idx in df.index[~valid_11 & (digits != "")]:
            issue = "رقم تليفون غير صحيح"
            if likely_missing_zero.loc[idx]:
                issue = "رقم تليفون غالبًا ناقص الصفر الأول بسبب تنسيق Excel"
            add_issue(issues, int(idx)+2, col, "Format/Pattern", issue, str(df.at[idx, col]))

    # 4) Format/Pattern and Validity for national ID
    for col in groups["national_id"]:
        digits = df[col].apply(to_digits)
        valid_14 = digits.apply(lambda x: len(x) == 14 or x == "")
        format_scores.append(round(valid_14.mean() * 100, 2))
        validity_scores.append(round(valid_14.mean() * 100, 2))
        for idx in df.index[~valid_14 & (digits != "")]:
            add_issue(issues, int(idx)+2, col, "Format/Pattern", "الرقم القومي لا يتكون من 14 رقمًا", str(df.at[idx, col]))

    # 5) Timeliness / chronology on start-end
    timeliness_scores = []
    if groups["start"] and groups["end"]:
        start_col = groups["start"][0]
        end_col = groups["end"][0]
        start_dt = pd.to_datetime(df[start_col], errors="coerce")
        end_dt = pd.to_datetime(df[end_col], errors="coerce")

        chrono_valid = ((end_dt >= start_dt) | start_dt.isna() | end_dt.isna())
        timeliness_scores.append(round(chrono_valid.mean() * 100, 2))
        for idx in df.index[~chrono_valid]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "وقت النهاية أقدم من وقت البداية", f"{df.at[idx, start_col]} -> {df.at[idx, end_col]}")

        duration_min = (end_dt - start_dt).dt.total_seconds() / 60
        over_30 = duration_min > 30
        over_60 = duration_min > 60

        for idx in df.index[over_30.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة المقابلة أكبر من 30 دقيقة وتحتاج مراجعة", round(duration_min.loc[idx], 2))
        for idx in df.index[over_60.fillna(False)]:
            add_issue(issues, int(idx)+2, f"{start_col} -> {end_col}", "Timeliness", "مدة المقابلة أكبر من 60 دقيقة وتعتبر حالة شاذة قوية", round(duration_min.loc[idx], 2))

    scores["Timeliness"] = round(sum(timeliness_scores) / len(timeliness_scores), 2) if timeliness_scores else 100.0

    # 6) Range on numeric columns using IQR outliers
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
            add_issue(issues, int(idx)+2, col, "Range", f"قيمة شاذة خارج النطاق الإحصائي التقريبي [{round(low,2)} - {round(high,2)}]", str(df.at[idx, col]))
    scores["Range"] = round(sum(range_scores) / len(range_scores), 2) if range_scores else 100.0

    # 7) Consistency heuristic: if a comment/explanation field has value while parent answer missing
    consistency_scores = []
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
                add_issue(issues, int(idx)+2, f"{parent_col} -> {comment_col}", "Consistency", "حقل التعليق ممتلئ بينما السؤال السابق فارغ", f"{df.at[idx, parent_col]} -> {df.at[idx, comment_col]}")
    scores["Consistency"] = round((1 - consistency_bad / consistency_checks) * 100, 2) if consistency_checks else 100.0

    # 8) Accuracy remains placeholder unless reference list supplied
    scores["Accuracy"] = 100.0

    # Aggregate validity/format
    scores["Validity"] = round(sum(validity_scores) / len(validity_scores), 2) if validity_scores else 100.0
    scores["Format/Pattern"] = round(sum(format_scores) / len(format_scores), 2) if format_scores else 100.0

    overall = round(sum(scores.values()) / len(scores), 2) if scores else 100.0

    scores_df = pd.DataFrame({"المعيار": list(scores.keys()), "النسبة %": list(scores.values())})
    issues_df = pd.DataFrame(issues)
    if not issues_df.empty:
        issues_df = issues_df.drop_duplicates()
    return scores_df, issues_df, overall, groups

uploaded_file = st.file_uploader("📁 ارفع ملف Excel أو CSV", type=["csv", "xlsx"])

if uploaded_file:
    df = read_file(uploaded_file)

    st.subheader("🔍 معاينة البيانات")
    st.dataframe(df.head(20), use_container_width=True)

    with st.expander("📌 الأعمدة المكتشفة تلقائيًا", expanded=False):
        groups = detect_column_groups(df)
        for k, v in groups.items():
            st.write(f"**{k}:** {v if v else 'لا يوجد'}")

    mode = st.radio("اختر وضع الفحص", ["فحص تلقائي ذكي", "فحص يدوي بالقواعد"], horizontal=True)

    if mode == "فحص تلقائي ذكي":
        st.info("هذا الوضع يكتشف المشكلات الشائعة تلقائيًا مثل: رقم الهاتف غير الصحيح، الرقم القومي غير الصحيح، النهاية قبل البداية، المدد الشاذة، التكرار، والفراغات في الأعمدة الأساسية.")
        if st.button("🚀 تشغيل الفحص التلقائي", type="primary"):
            scores_df, issues_df, overall, groups = auto_assess(df)

            st.subheader("📈 النتائج")
            st.metric("🎯 النسبة الكلية لجودة البيانات", f"{overall}%")
            st.dataframe(scores_df, use_container_width=True)

            st.subheader("⚠️ المشكلات المكتشفة")
            if issues_df.empty:
                st.success("لم يتم اكتشاف مشكلات تلقائية وفق القواعد الذكية الحالية.")
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

    else:
        st.warning("الوضع اليدوي مناسب عندما تريد تعريف قواعدك بنفسك على أي شيت.")
        columns = list(df.columns)

        st.subheader("⚙️ تفعيل المعايير")
        c1, c2 = st.columns(2)
        with c1:
            completeness_on = st.checkbox("1. Completeness — الاكتمال", value=True)
            uniqueness_on = st.checkbox("2. Uniqueness — التفرد", value=True)
            validity_on = st.checkbox("3. Validity — الصلاحية", value=True)
            accuracy_on = st.checkbox("4. Accuracy — الدقة", value=False)
        with c2:
            consistency_on = st.checkbox("5. Consistency — الاتساق", value=False)
            timeliness_on = st.checkbox("6. Timeliness — الحداثة", value=False)
            range_on = st.checkbox("7. Range — النطاق", value=True)
            format_on = st.checkbox("8. Format/Pattern — النمط أو الصيغة", value=True)

        required_cols = st.multiselect("الأعمدة الإلزامية", columns) if completeness_on else []
        unique_cols = st.multiselect("أعمدة التفرد", columns) if uniqueness_on else []
        validity_col = st.selectbox("عمود الصلاحية", ["بدون"] + columns) if validity_on else "بدون"
        allowed_values_text = st.text_input("القيم المسموحة", placeholder="مثال: نعم,لا") if validity_on else ""
        range_col = st.selectbox("عمود النطاق", ["بدون"] + columns) if range_on else "بدون"
        min_val = st.text_input("أقل قيمة") if range_on else ""
        max_val = st.text_input("أعلى قيمة") if range_on else ""
        format_col = st.selectbox("عمود النمط", ["بدون"] + columns) if format_on else "بدون"
        regex_pattern = st.text_input("Regex pattern", placeholder=r"^\d{11}$") if format_on else ""

        if st.button("🚀 تشغيل الفحص اليدوي", type="primary"):
            scores = {}
            issues = []

            if completeness_on:
                col_scores = []
                for col in required_cols:
                    non_empty = df[col].notna() & (df[col].astype(str).str.strip() != "")
                    col_scores.append(non_empty.mean() * 100)
                    for idx in df.index[~non_empty]:
                        add_issue(issues, int(idx)+2, col, "Completeness", "قيمة ناقصة", str(df.at[idx, col]))
                scores["Completeness"] = round(sum(col_scores) / len(col_scores), 2) if col_scores else 100.0

            if uniqueness_on:
                col_scores = []
                for col in unique_cols:
                    series = df[col].astype(str).str.strip()
                    dup_mask = series.duplicated(keep=False) & (series != "") & (series.str.lower() != "nan")
                    col_scores.append((~dup_mask).mean() * 100)
                    for idx in df.index[dup_mask]:
                        add_issue(issues, int(idx)+2, col, "Uniqueness", "قيمة مكررة", str(df.at[idx, col]))
                scores["Uniqueness"] = round(sum(col_scores) / len(col_scores), 2) if col_scores else 100.0

            if validity_on:
                if validity_col != "بدون" and allowed_values_text.strip():
                    allowed = [x.strip() for x in allowed_values_text.split(",") if x.strip()]
                    series = df[validity_col].astype(str).str.strip()
                    valid_mask = series.isin(allowed) | df[validity_col].isna() | (series == "")
                    scores["Validity"] = round(valid_mask.mean() * 100, 2)
                    for idx in df.index[~valid_mask]:
                        add_issue(issues, int(idx)+2, validity_col, "Validity", f"قيمة غير مسموحة. القيم المقبولة: {allowed}", str(df.at[idx, validity_col]))
                else:
                    scores["Validity"] = 100.0

            if accuracy_on:
                scores["Accuracy"] = 100.0

            if consistency_on:
                scores["Consistency"] = 100.0

            if timeliness_on:
                scores["Timeliness"] = 100.0

            if range_on:
                if range_col != "بدون" and (str(min_val).strip() or str(max_val).strip()):
                    num = pd.to_numeric(df[range_col], errors="coerce")
                    mask = pd.Series([True] * len(df), index=df.index)
                    if str(min_val).strip():
                        mask &= (num >= float(min_val)) | num.isna()
                    if str(max_val).strip():
                        mask &= (num <= float(max_val)) | num.isna()
                    scores["Range"] = round(mask.mean() * 100, 2)
                    for idx in df.index[~mask]:
                        add_issue(issues, int(idx)+2, range_col, "Range", f"قيمة خارج النطاق [{min_val or '-∞'} - {max_val or '∞'}]", str(df.at[idx, range_col]))
                else:
                    scores["Range"] = 100.0

            if format_on:
                if format_col != "بدون" and regex_pattern.strip():
                    series = df[format_col].astype(str).str.strip()
                    mask = series.apply(lambda x: bool(re.fullmatch(regex_pattern, x)) if x and x.lower() != "nan" else True)
                    scores["Format/Pattern"] = round(mask.mean() * 100, 2)
                    for idx in df.index[~mask]:
                        add_issue(issues, int(idx)+2, format_col, "Format/Pattern", f"القيمة لا تطابق النمط: {regex_pattern}", str(df.at[idx, format_col]))
                else:
                    scores["Format/Pattern"] = 100.0

            scores_df = pd.DataFrame({"المعيار": list(scores.keys()), "النسبة %": list(scores.values())})
            issues_df = pd.DataFrame(issues)
            overall = round(sum(scores.values()) / len(scores), 2) if scores else 100.0

            st.subheader("📈 النتائج")
            st.metric("🎯 النسبة الكلية لجودة البيانات", f"{overall}%")
            st.dataframe(scores_df, use_container_width=True)

            st.subheader("⚠️ المشكلات")
            if issues_df.empty:
                st.success("لا توجد مشكلات وفق القواعد الحالية.")
            else:
                st.dataframe(issues_df, use_container_width=True)
                st.download_button(
                    "⬇️ تحميل تقرير المشكلات CSV",
                    issues_df.to_csv(index=False).encode("utf-8-sig"),
                    "manual_detected_issues.csv",
                    "text/csv"
                )
