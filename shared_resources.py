import streamlit as st

from env_setup import load_env  # noqa: F401 -- round 38d: the shared .env loader, re-exported here
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma

DB_FOLDER = "./carrier_docs_db"

@st.cache_resource
def get_embeddings():
    return FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")

@st.cache_resource
def get_vectorstore():
    return Chroma(
        persist_directory=DB_FOLDER,
        embedding_function=get_embeddings()
    )
