
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import re

st.set_page_config(layout="wide")

st.title("📊 Data Quality App v4 (Smart + Manual)")

mode = st.radio("طريقة التشغيل", ["Auto", "Manual", "Hybrid"])

uploaded_file = st.file_uploader("ارفع ملف")

def to_digits(x):
    if pd.isna(x): return ""
    return re.sub(r"\D", "", str(x))

def is_phone_valid(x):
    d = to_digits(x)
    return len(d) == 11 or len(d) == 10

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.dataframe(df.head())

    issues = []

    # Completeness
    for col in df.columns:
        if df[col].isna().any():
            for i in df[df[col].isna()].index:
                issues.append((i, col, "Completeness"))

    # Uniqueness
    if "ID" in df.columns:
        dup = df["ID"].duplicated()
        for i in df[dup].index:
            issues.append((i, "ID", "Uniqueness"))

    # Validity ONLY for categorical
    if "Gender" in df.columns:
        for i, v in df["Gender"].items():
            if v not in ["Male", "Female"]:
                issues.append((i, "Gender", "Validity"))

    # Range for Age
    if "Age" in df.columns:
        for i, v in df["Age"].items():
            if v > 120 or v < 0:
                issues.append((i, "Age", "Range"))

    st.write("### Issues")
    st.write(issues)

    # Dashboard
    if issues:
        df_issues = pd.DataFrame(issues, columns=["row","col","type"])
        st.write(df_issues)

        plt.figure()
        df_issues["type"].value_counts().plot(kind="bar")
        st.pyplot(plt)
