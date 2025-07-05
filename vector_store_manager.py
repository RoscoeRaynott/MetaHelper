# vector_store_manager.py (Corrected)

import streamlit as st
import os
# --- CORRECTED IMPORT: Use the official OpenAI class ---
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
# --- END CORRECTION ---
from langchain_community.vectorstores import Chroma
from langchain.docstore.document import Document

# Define a persistent path for the vector store within the project
VECTOR_STORE_PATH = "./chroma_db"

@st.cache_resource
def get_embedding_model():
    """
    Initializes and returns the Hugging Face embedding model.
    """
    if "HUGGINGFACE_API_TOKEN" not in st.secrets:
        st.error("HUGGINGFACE_API_TOKEN not found in Streamlit secrets. Please add it.")
        return None

    try:
        # Use the superior BGE model for better retrieval performance.
        model_name = "BAAI/bge-small-en-v1.5"
        
        hf_embeddings = HuggingFaceInferenceAPIEmbeddings(
            api_key=st.secrets.get("HUGGINGFACE_API_TOKEN"),
            model_name=model_name,
        )
        return hf_embeddings
    except Exception as e:
        st.error(f"Failed to initialize Hugging Face embedding model: {e}")
        return None

# The rest of the functions in this file (create_vector_store, load_vector_store)
# do not need any changes, as they just consume the embedding_model object.
def create_vector_store(text_chunks, source_url):
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
