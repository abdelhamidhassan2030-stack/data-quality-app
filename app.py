
import re
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Data Quality Assessment App", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] {
    direction: rtl;
    text-align: right;
}
.block-container {
    padding-top: 1.5rem;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 تطبيق تقييم جودة البيانات")
st.caption("تقييم جودة البيانات بناءً على المعايير: الاكتمال، التفرد، الصلاحية، الدقة، الاتساق، الحداثة، النطاق، النمط")

def pct(pass_count, total_count):
    return round((pass_count / total_count) * 100, 2) if total_count else 100.0

def read_file(uploaded_file):
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    xls = pd.ExcelFile(uploaded_file)
    if len(xls.sheet_names) == 1:
        return pd.read_excel(uploaded_file)
    sheet_name = st.selectbox("اختر الشيت", xls.sheet_names)
    return pd.read_excel(uploaded_file, sheet_name=sheet_name)

def to_datetime_safe(series):
    return pd.to_datetime(series, errors="coerce")

uploaded_file = st.file_uploader("📁 ارفع ملف Excel أو CSV", type=["csv", "xlsx"])

if uploaded_file:
    df = read_file(uploaded_file)

    st.subheader("🔍 معاينة البيانات")
    st.dataframe(df.head(20), use_container_width=True)

    st.subheader("⚙️ قائمة المعايير")
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

    st.markdown("---")
    st.subheader("🧩 إعداد القواعد")

    columns = list(df.columns)

    # Completeness
    required_cols = st.multiselect(
        "الأعمدة الإلزامية للاكتمال (Completeness)",
        columns,
        help="أي عمود هنا يعتبر مطلوبًا، والقيم الفارغة فيه تُحسب مشكلة."
    ) if completeness_on else []

    # Uniqueness
    unique_cols = st.multiselect(
        "الأعمدة التي يجب أن تكون فريدة (Uniqueness)",
        columns,
        help="مثل ID أو الرقم القومي أو كود المستفيد."
    ) if uniqueness_on else []

    # Validity
    validity_col = st.selectbox(
        "عمود الصلاحية (Validity)",
        ["بدون"] + columns,
        help="اختر عمودًا لوضع قائمة قيم مسموحة."
    ) if validity_on else "بدون"
    allowed_values_text = st.text_input(
        "القيم المسموحة لهذا العمود - افصل بفاصلة",
        placeholder="مثال: Male,Female أو نعم,لا"
    ) if validity_on else ""

    # Accuracy
    accuracy_col = st.selectbox(
        "عمود الدقة (Accuracy)",
        ["بدون"] + columns,
        help="يمكن استخدامه حاليًا كفحص مرجعي بسيط عبر القيم المسموحة أيضًا."
    ) if accuracy_on else "بدون"
    accuracy_values_text = st.text_input(
        "القيم المرجعية الصحيحة للدقة - افصل بفاصلة",
        placeholder="مثال: مكتمل,غير مكتمل"
    ) if accuracy_on else ""

    # Consistency
    st.markdown("### الاتساق (Consistency)") if consistency_on else None
    cons_if_col = st.selectbox("إذا كان العمود", ["بدون"] + columns, key="cons_if") if consistency_on else "بدون"
    cons_if_val = st.text_input("يساوي القيمة", key="cons_if_val") if consistency_on else ""
    cons_then_col = st.selectbox("فإن العمود", ["بدون"] + columns, key="cons_then") if consistency_on else "بدون"
    cons_then_val = st.text_input("يجب أن يساوي", key="cons_then_val") if consistency_on else ""

    # Timeliness
    time_col = st.selectbox(
        "عمود التاريخ للحداثة (Timeliness)",
        ["بدون"] + columns
    ) if timeliness_on else "بدون"
    max_age_days = st.text_input(
        "أقصى عمر مسموح للتاريخ بالأيام",
        placeholder="مثال: 30"
    ) if timeliness_on else ""

    # Range
    range_col = st.selectbox(
        "العمود الرقمي للنطاق (Range)",
        ["بدون"] + columns
    ) if range_on else "بدون"
    min_val = st.text_input("أقل قيمة مسموحة", placeholder="مثال: 0") if range_on else ""
    max_val = st.text_input("أعلى قيمة مسموحة", placeholder="مثال: 100") if range_on else ""

    # Format
    format_col = st.selectbox(
        "العمود المطلوب فحص نمطه (Format/Pattern)",
        ["بدون"] + columns
    ) if format_on else "بدون"
    regex_pattern = st.text_input(
        "Regex pattern",
        placeholder=r"مثال: ^\d{11}$"
    ) if format_on else ""

    if st.button("🚀 تحليل جودة البيانات", type="primary"):
        issues = []
        scores = {}

        # 1 Completeness
        if completeness_on:
            col_scores = []
            for col in required_cols:
                non_empty = df[col].notna() & (df[col].astype(str).str.strip() != "")
                col_scores.append(non_empty.mean() * 100)
                for idx in df.index[~non_empty]:
                    issues.append([idx + 2, col, "Completeness", "قيمة ناقصة", str(df.at[idx, col])])
            scores["Completeness"] = round(sum(col_scores) / len(col_scores), 2) if col_scores else 100.0

        # 2 Uniqueness
        if uniqueness_on:
            col_scores = []
            for col in unique_cols:
                series = df[col]
                dup_mask = series.duplicated(keep=False) & series.notna() & (series.astype(str).str.strip() != "")
                pass_mask = ~dup_mask
                col_scores.append(pass_mask.mean() * 100)
                for idx in df.index[dup_mask]:
                    issues.append([idx + 2, col, "Uniqueness", "قيمة مكررة في عمود يفترض أن يكون فريدًا", str(df.at[idx, col])])
            scores["Uniqueness"] = round(sum(col_scores) / len(col_scores), 2) if col_scores else 100.0

        # 3 Validity
        if validity_on:
            if validity_col != "بدون" and allowed_values_text.strip():
                allowed = [x.strip() for x in allowed_values_text.split(",") if x.strip()]
                series = df[validity_col].astype(str).str.strip()
                valid_mask = series.isin(allowed) | df[validity_col].isna() | (series == "")
                scores["Validity"] = round(valid_mask.mean() * 100, 2)
                for idx in df.index[~valid_mask]:
                    issues.append([idx + 2, validity_col, "Validity", f"قيمة غير مسموحة. القيم المقبولة: {allowed}", str(df.at[idx, validity_col])])
            else:
                scores["Validity"] = 100.0

        # 4 Accuracy
        if accuracy_on:
            if accuracy_col != "بدون" and accuracy_values_text.strip():
                allowed = [x.strip() for x in accuracy_values_text.split(",") if x.strip()]
                series = df[accuracy_col].astype(str).str.strip()
                accurate_mask = series.isin(allowed) | df[accuracy_col].isna() | (series == "")
                scores["Accuracy"] = round(accurate_mask.mean() * 100, 2)
                for idx in df.index[~accurate_mask]:
                    issues.append([idx + 2, accuracy_col, "Accuracy", f"قيمة غير مطابقة للقيم المرجعية: {allowed}", str(df.at[idx, accuracy_col])])
            else:
                scores["Accuracy"] = 100.0

        # 5 Consistency
        if consistency_on:
            if cons_if_col != "بدون" and cons_then_col != "بدون":
                applicable = df[cons_if_col].astype(str).str.strip() == str(cons_if_val).strip()
                consistent = (~applicable) | (df[cons_then_col].astype(str).str.strip() == str(cons_then_val).strip())
                scores["Consistency"] = round(consistent.mean() * 100, 2)
                for idx in df.index[~consistent]:
                    issues.append([
                        idx + 2,
                        f"{cons_if_col} -> {cons_then_col}",
                        "Consistency",
                        f"إذا كان {cons_if_col} = {cons_if_val} فيجب أن {cons_then_col} = {cons_then_val}",
                        f"{df.at[idx, cons_if_col]} -> {df.at[idx, cons_then_col]}"
                    ])
            else:
                scores["Consistency"] = 100.0

        # 6 Timeliness
        if timeliness_on:
            if time_col != "بدون" and str(max_age_days).strip():
                d = to_datetime_safe(df[time_col])
                days = int(max_age_days)
                cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
                timely_mask = (d >= cutoff) | d.isna()
                scores["Timeliness"] = round(timely_mask.mean() * 100, 2)
                for idx in df.index[~timely_mask]:
                    issues.append([idx + 2, time_col, "Timeliness", f"تاريخ أقدم من {days} يوم", str(df.at[idx, time_col])])
            else:
                scores["Timeliness"] = 100.0

        # 7 Range
        if range_on:
            if range_col != "بدون" and (str(min_val).strip() or str(max_val).strip()):
                num = pd.to_numeric(df[range_col], errors="coerce")
                valid_mask = pd.Series([True] * len(df), index=df.index)
                if str(min_val).strip():
                    valid_mask &= (num >= float(min_val)) | num.isna()
                if str(max_val).strip():
                    valid_mask &= (num <= float(max_val)) | num.isna()
                scores["Range"] = round(valid_mask.mean() * 100, 2)
                for idx in df.index[~valid_mask]:
                    issues.append([idx + 2, range_col, "Range", f"قيمة خارج النطاق [{min_val or '-∞'} - {max_val or '∞'}]", str(df.at[idx, range_col])])
            else:
                scores["Range"] = 100.0

        # 8 Format/Pattern
        if format_on:
            if format_col != "بدون" and regex_pattern.strip():
                series = df[format_col].astype(str).str.strip()
                format_mask = series.apply(lambda x: bool(re.fullmatch(regex_pattern, x)) if x and x.lower() != "nan" else True)
                scores["Format/Pattern"] = round(format_mask.mean() * 100, 2)
                for idx in df.index[~format_mask]:
                    issues.append([idx + 2, format_col, "Format/Pattern", f"القيمة لا تطابق النمط: {regex_pattern}", str(df.at[idx, format_col])])
            else:
                scores["Format/Pattern"] = 100.0

        overall = round(sum(scores.values()) / len(scores), 2) if scores else 100.0

        st.markdown("---")
        st.subheader("📈 النتائج")
        st.metric("🎯 النسبة الكلية لجودة البيانات", f"{overall}%")

        scores_df = pd.DataFrame({
            "المعيار": list(scores.keys()),
            "النسبة %": list(scores.values())
        })
        st.dataframe(scores_df, use_container_width=True)

        issues_df = pd.DataFrame(issues, columns=["Row", "Column", "Dimension", "Issue", "Value"])
        st.subheader("⚠️ المشكلات")
        if issues_df.empty:
            st.success("لا توجد مشكلات بناءً على القواعد الحالية.")
        else:
            st.dataframe(issues_df, use_container_width=True)
            st.download_button(
                "⬇️ تحميل تقرير المشكلات CSV",
                issues_df.to_csv(index=False).encode("utf-8-sig"),
                "data_quality_issues.csv",
                "text/csv"
            )

        st.download_button(
            "⬇️ تحميل نسب المعايير CSV",
            scores_df.to_csv(index=False).encode("utf-8-sig"),
            "data_quality_scores.csv",
            "text/csv"
        )
