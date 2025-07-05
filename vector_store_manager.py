# vector_store_manager.py

import streamlit as st
import os
# --- NEW: Import OpenRouter-specific embedding class ---
from langchain_community.embeddings import OpenRouterEmbeddings
# --- END NEW ---
from langchain_community.vectorstores import Chroma
from langchain.docstore.document import Document

# Define a persistent path for the vector store within the project
VECTOR_STORE_PATH = "./chroma_db"

@st.cache_resource
def get_embedding_model():
    """
    Initializes and returns the OpenRouter embedding model.
    Caches the model to avoid re-initializing on every script rerun.
    """
    # Check if the key exists in secrets
    if "Openrouter_API_key" not in st.secrets:
        st.error("Openrouter_API_key not found in Streamlit secrets. Please add it.")
        return None

    try:
        # Initialize OpenRouterEmbeddings, specifying a model if desired.
        # "text-embedding-ada-002" is a common and effective choice available on OpenRouter.
        # The library will automatically use the 'OPENROUTER_API_KEY' environment variable.
        embeddings = OpenRouterEmbeddings(
            openrouter_api_key=st.secrets.get("Openrouter_API_key"),
            model_name="openai/text-embedding-ada-002" # You can change this to other models OpenRouter supports
        )
        return embeddings
    except Exception as e:
        st.error(f"Failed to initialize OpenRouter embedding model: {e}")
        return None

def create_vector_store(text_chunks, source_url):
    """
    Creates or updates a vector store from text chunks using OpenRouter embeddings.
    """
    if not text_chunks:
        return None, "No text chunks provided to create the vector store."

    documents = [
        Document(page_content=chunk, metadata={"source": source_url})
        for chunk in text_chunks
    ]
    
    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            return None, "Embedding model could not be initialized. Check API key."
        
        # This part remains the same, it just uses the OpenRouter embedding function
        vector_store = Chroma(
            persist_directory=VECTOR_STORE_PATH,
            embedding_function=embedding_model
        )
        vector_store.add_documents(documents)
        vector_store.persist()
        
        return vector_store, f"Successfully added {len(documents)} document chunks to the vector store."
    except Exception as e:
        return None, f"Failed to create or update vector store: {e}"

def load_vector_store():
    """
    Loads an existing vector store from disk.
    """
    if not os.path.exists(VECTOR_STORE_PATH):
        return None

    try:
        embedding_model = get_embedding_model()
        if not embedding_model:
            st.warning("Could not load vector store because embedding model failed to initialize.")
            return None
            
        vector_store = Chroma(
            persist_directory=VECTOR_STORE_PATH,
            embedding_function=embedding_model
        )
        return vector_store
    except Exception as e:
        st.error(f"Failed to load vector store: {e}")
        return None
