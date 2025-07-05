import streamlit as st
import os
import requests
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.docstore.document import Document

VECTOR_STORE_PATH = "./chroma_db"

@st.cache_resource
def get_embedding_model():
    if "HUGGINGFACE_API_TOKEN" not in st.secrets:
        st.error("HUGGINGFACE_API_TOKEN not found in Streamlit secrets.")
        return None
    api_key = st.secrets.get("HUGGINGFACE_API_TOKEN")
    try:
        # Validate API key with a test request
        response = requests.post(
            "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"inputs": "test"}
        )
        if response.status_code != 200:
            st.error(f"API key validation failed: {response.status_code} - {response.text}")
            return None
        embeddings = HuggingFaceInferenceAPIEmbeddings(
            api_key=api_key,
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        test_embedding = embeddings.embed_query("test")
        if not test_embedding:
            st.error("Empty embedding response from Hugging Face API.")
            return None
        return embeddings
    except Exception as e:
        st.error(f"Failed to initialize Hugging Face embedding model: {e}")
        return None

def create_vector_store(text_chunks, source_url):
    if not text_chunks:
        return None, "No text chunks provided."
    documents = [Document(page_content=chunk, metadata={"source": source_url}) for chunk in text_chunks]
    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            return None, "Embedding model initialization failed."
        vector_store = Chroma(persist_directory=VECTOR_STORE_PATH, embedding_function=embedding_model)
        vector_store.add_documents(documents)
        vector_store.persist()
        return vector_store, f"Added {len(documents)} chunks to vector store."
    except Exception as e:
        return None, f"Failed to create/update vector store: {e}"

def load_vector_store():
    if not os.path.exists(VECTOR_STORE_PATH):
        return None
    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            st.warning("Could not load vector store: embedding model failed.")
            return None
        vector_store = Chroma(persist_directory=VECTOR_STORE_PATH, embedding_function=embedding_model)
        return vector_store
    except Exception as e:
        st.error(f"Failed to load vector store: {e}")
        return None
