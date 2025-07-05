# vector_store_manager.py (Final Working Version)

import streamlit as st
import os
import requests
import json
from langchain_community.vectorstores import Chroma
from langchain.docstore.document import Document
from langchain.embeddings.base import Embeddings
import time

# --- Custom Hugging Face Embedding Class ---
# This class calls the API directly using the correct endpoint and payload.
class DirectHuggingFaceEmbeddings(Embeddings):
    def __init__(self, api_key: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.api_key = api_key
        self.model_name = model_name
        # --- THE FIX: Use the correct router endpoint you discovered ---
        self.api_url = f"https://router.huggingface.co/hf-inference/models/{self.model_name}/pipeline/feature-extraction"
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Helper function to call the API and get embeddings."""
        # The feature-extraction pipeline correctly uses the "inputs" key.
        payload = {"inputs": texts}
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=45)
            response.raise_for_status()
            embeddings = response.json()
            
            if isinstance(embeddings, list) and all(isinstance(e, list) for e in embeddings):
                return embeddings
            else:
                st.error(f"Hugging Face API returned an unexpected format: {embeddings}")
                return None

        except requests.exceptions.RequestException as e:
            st.error(f"Hugging Face API request failed: {e}")
            if e.response:
                st.error(f"Response Status: {e.response.status_code}")
                st.error(f"Response Body: {e.response.text}")
            return None
        except json.JSONDecodeError:
            st.error(f"Failed to decode JSON from API. Raw response: {response.text}")
            return None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        # The free inference API can sometimes handle only one input at a time.
        # We process texts one by one for maximum stability.
        embeddings_list = []
        for text in texts:
            # Add a small delay to be respectful to the free API tier
            time.sleep(0.1)
            result = self._embed([text]) # Send as a list with one item
            if result:
                embeddings_list.append(result[0])
            else:
                st.error(f"Failed to get embedding for text: '{text[:100]}...'")
                return None # Signal failure
        return embeddings_list

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        result = self._embed([text])
        return result[0] if result else []

# --- END Custom Class ---

VECTOR_STORE_PATH = "./chroma_db"

@st.cache_resource
def get_embedding_model():
    """Initializes our custom Hugging Face embedding model."""
    if "HUGGINGFACE_API_TOKEN" not in st.secrets:
        st.error("HUGGINGFACE_API_TOKEN not found in Streamlit secrets.")
        return None
    try:
        return DirectHuggingFaceEmbeddings(
            api_key=st.secrets.get("HUGGINGFACE_API_TOKEN"),
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    except Exception as e:
        st.error(f"Failed to initialize embedding model: {e}")
        return None

def create_vector_store(text_chunks, source_url):
    if not text_chunks:
        return None, "No text chunks provided."
    documents = [Document(page_content=chunk, metadata={"source": source_url}) for chunk in text_chunks]
    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            return None, "Embedding model could not be initialized."
        
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
            return None
        return Chroma(persist_directory=VECTOR_STORE_PATH, embedding_function=embedding_model)
    except Exception as e:
        st.error(f"Failed to load vector store: {e}")
        return None
