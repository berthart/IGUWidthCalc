import streamlit as st

# Pull the token from your hidden secrets.toml file
igsdb_api_token = st.secrets["IGSDB_TOKEN"]

url_single_product = "https://igsdb.lbl.gov/api/v1/products/{id}"
url_single_product_datafile = "https://igsdb.lbl.gov/api/v1/products/{id}/datafile"
headers = {"Authorization": "Token {token}".format(token=igsdb_api_token)}
