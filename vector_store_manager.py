# vector_store_manager.py (Final Working Version)

import streamlit as st
#import os
import requests
import json
#import shutil
#from langchain_community.vectorstores import Chroma
from langchain_chroma import Chroma
from langchain.docstore.document import Document
from langchain.embeddings.base import Embeddings
import time

# --- Custom Hugging Face Embedding Class ---
# This class calls the API directly using the correct endpoint and payload.
class DirectHuggingFaceEmbeddings(Embeddings):
    def __init__(self, api_key: str, model_name: str = "BAAI/bge-small-en-v1.5"):#"sentence-transformers/all-MiniLM-L6-v2"):
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
        """
        Embed a list of documents by sending them all in a single API call (batching).
        This is much faster than one-by-one processing.
        """
        # The _embed function is already designed to handle a list of texts.
        # We can simply call it directly with the full list.
        embeddings = self._embed(texts)
        
        if embeddings and len(embeddings) == len(texts):
            return embeddings
        else:
            # If the call fails or returns a mismatched number of embeddings, return None.
            st.error("Failed to generate embeddings for the batch of documents.")
            return None

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        result = self._embed([text])
        return result[0] if result else []

# --- END Custom Class ---

#VECTOR_STORE_PATH = "./chroma_db"

def create_in_memory_vector_store(text_chunks, source_url):
    """
    Creates a new in-memory vector store.
    This will be stored in the user's session state.
    """
    if not text_chunks:
        return None, "No text chunks provided."
    
    documents = [
        Document(
            page_content=chunk["text"], 
            metadata={"source": source_url, "section": chunk.get("section", "Unknown")}
        ) for chunk in text_chunks
    ]
    
    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            return None, "Embedding model could not be initialized."
        
        # Create the vector store in memory by not providing a persist_directory
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embedding_model
        )
        
        # Store the entire vector store object in the session state
        st.session_state['vector_store'] = vector_store
        
        return vector_store, f"Added {len(documents)} chunks to the in-memory knowledge library."
    except Exception as e:
        return None, f"Failed to create in-memory vector store: {e}"

def add_to_in_memory_vector_store(text_chunks, source_url):
    """
    Adds new documents to an existing in-memory vector store.
    """
    if 'vector_store' not in st.session_state or st.session_state['vector_store'] is None:
        # If no store exists, create a new one
        return create_in_memory_vector_store(text_chunks, source_url)

    if not text_chunks:
        return None, "No text chunks provided."

    documents = [
        Document(
            page_content=chunk["text"], 
            metadata={"source": source_url, "section": chunk.get("section", "Unknown")}
        ) for chunk in text_chunks
    ]

    try:
        # Get the existing store from session state and add documents
        vector_store = st.session_state['vector_store']
        vector_store.add_documents(documents)
        
        return vector_store, f"Added {len(documents)} chunks to the in-memory knowledge library."
    except Exception as e:
        return None, f"Failed to add to in-memory vector store: {e}"

def clear_in_memory_vector_store():
    """Clears the in-memory vector store from the session state."""
    if 'vector_store' in st.session_state:
        del st.session_state['vector_store']
    return True, "In-memory knowledge library cleared."
