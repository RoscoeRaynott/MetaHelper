# import streamlit as st
# import os
# import requests
# from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
# from langchain_community.vectorstores import Chroma
# from langchain.docstore.document import Document

# VECTOR_STORE_PATH = "./chroma_db"

# @st.cache_resource
# def get_embedding_model():
#     if "HUGGINGFACE_API_TOKEN" not in st.secrets:
#         st.error("HUGGINGFACE_API_TOKEN not found in Streamlit secrets.")
#         return None
#     api_key = st.secrets.get("HUGGINGFACE_API_TOKEN")
#     try:
#         # Validate API key with a test request
#         response = requests.post(
#             "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2",
#             headers={"Authorization": f"Bearer {api_key}"},
#             json={"inputs": "test"}
#         )
#         if response.status_code != 200:
#             st.error(f"API key validation failed: {response.status_code} - {response.text}")
#             return None
#         embeddings = HuggingFaceInferenceAPIEmbeddings(
#             api_key=api_key,
#             model_name="sentence-transformers/all-MiniLM-L6-v2"
#         )
#         test_embedding = embeddings.embed_query("test")
#         if not test_embedding:
#             st.error("Empty embedding response from Hugging Face API.")
#             return None
#         return embeddings
#     except Exception as e:
#         st.error(f"Failed to initialize Hugging Face embedding model: {e}")
#         return None

# def create_vector_store(text_chunks, source_url):
#     if not text_chunks:
#         return None, "No text chunks provided."
#     documents = [Document(page_content=chunk, metadata={"source": source_url}) for chunk in text_chunks]
#     try:
#         embedding_model = get_embedding_model()
#         if not embedding_model:
#             return None, "Embedding model initialization failed."
#         vector_store = Chroma(persist_directory=VECTOR_STORE_PATH, embedding_function=embedding_model)
#         vector_store.add_documents(documents)
#         vector_store.persist()
#         return vector_store, f"Added {len(documents)} chunks to vector store."
#     except Exception as e:
#         return None, f"Failed to create/update vector store: {e}"

# def load_vector_store():
#     if not os.path.exists(VECTOR_STORE_PATH):
#         return None
#     try:
#         embedding_model = get_embedding_model()
#         if not embedding_model:
#             st.warning("Could not load vector store: embedding model failed.")
#             return None
#         vector_store = Chroma(persist_directory=VECTOR_STORE_PATH, embedding_function=embedding_model)
#         return vector_store
#     except Exception as e:
#         st.error(f"Failed to load vector store: {e}")
#         return None
###########################################################################################################################################
# vector_store_manager.py (Final Corrected Version)

import streamlit as st
import os
import requests
import json
from langchain_community.vectorstores import Chroma
from langchain.docstore.document import Document
from langchain.embeddings.base import Embeddings

# --- Custom Hugging Face Embedding Class ---
# This class calls the API directly and specifies the correct pipeline.
class CustomHuggingFaceEmbeddings(Embeddings):
    def __init__(self, api_key: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.api_key = api_key
        self.model_name = model_name
        # --- THE FIX: Explicitly use the "feature-extraction" pipeline endpoint ---
        self.api_url = f"https://huggingface.co/{self.model_name}"
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Helper function to call the API and get embeddings."""
        try:
            # The feature-extraction pipeline correctly uses the "inputs" key.
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={"inputs": texts, "options": {"wait_for_model": True}}
            )
            response.raise_for_status()
            embeddings = response.json()
            
            if isinstance(embeddings, list) and all(isinstance(e, list) for e in embeddings):
                return embeddings
            else:
                st.error(f"Unexpected embedding format from HF API: {embeddings}")
                return None

        except requests.exceptions.RequestException as e:
            st.error(f"Hugging Face API request failed: {e}")
            if e.response:
                st.error(f"Response Body: {e.response.text}")
            return None
        except json.JSONDecodeError:
            st.error(f"JSON Decode Error. API returned non-JSON response: {response.text}")
            return None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        result = self._embed([text])
        return result[0] if result else []

# --- END Custom Class ---


# Define a persistent path for the vector store
VECTOR_STORE_PATH = "./chroma_db"

@st.cache_resource
def get_embedding_model():
    """
    Initializes and returns our custom Hugging Face embedding model.
    """
    if "HUGGINGFACE_API_TOKEN" not in st.secrets:
        st.error("HUGGINGFACE_API_TOKEN not found in Streamlit secrets. Please add it.")
        return None

    try:
        custom_embeddings = CustomHuggingFaceEmbeddings(
            api_key=st.secrets.get("HUGGINGFACE_API_TOKEN"),
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        return custom_embeddings
    except Exception as e:
        st.error(f"Failed to initialize Custom Hugging Face embedding model: {e}")
        return None

# The rest of the functions are UNCHANGED.
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
