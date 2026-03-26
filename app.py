
import streamlit as st
import pandas as pd

st.title("Data Quality App")

uploaded_file = st.file_uploader("Upload Excel or CSV", type=["csv","xlsx"])

if uploaded_file:
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.write("Preview Data", df.head())

    st.subheader("Basic Data Quality Check")

    missing = df.isnull().sum()
    st.write("Missing Values:", missing)

    duplicates = df.duplicated().sum()
    st.write("Duplicate Rows:", duplicates)

    st.success("Check Completed")
