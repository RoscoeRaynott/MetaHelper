# pages/2_Analyze_Papers.py

import streamlit as st
import os
from data_ingestor import process_single_link
from vector_store_manager import create_vector_store, load_vector_store
import time

st.set_page_config(layout="wide")
st.title("📄 Paper Analysis and Vector Store Management")
st.markdown("Process individual papers and add their content to a searchable knowledge library (Vector Store).")

# --- NEW: Display persisted status messages ---
if "status_message" in st.session_state and st.session_state.status_message:
    message_type, text = st.session_state.status_message
    if message_type == "success":
        st.success(text)
    elif message_type == "error":
        st.error(text)
    # Clear the message after displaying it so it doesn't show up again
    del st.session_state.status_message
# --- END NEW ---

# --- Initialize session state for this page ---
if 'processed_text' not in st.session_state:
    st.session_state['processed_text'] = None
if 'processed_chunks' not in st.session_state:
    st.session_state['processed_chunks'] = None
if 'processed_link' not in st.session_state:
    st.session_state['processed_link'] = ""

# --- 1. Vector Store Management UI ---
st.header("1. Knowledge Library Status")

vector_store = load_vector_store()
if vector_store:
    doc_count = vector_store._collection.count()
    st.success(f"✅ Vector Store is active and contains {doc_count} document chunks.")
else:
    st.warning("⚠️ No Vector Store found. Process a document below and add it to create one.")

# --- 2. Link Selection and Processing UI ---
st.markdown("---")
st.header("2. Select and Process a Link")

if 'links_for_rag' not in st.session_state or not st.session_state['links_for_rag']:
    st.warning("No links prepared. Go to the main search page to find and prepare links first.")
else:
    links = st.session_state['links_for_rag']
    st.info(f"Found {len(links)} links prepared from the search page.")
    
    selected_link = st.selectbox("Choose a link to process:", options=links)

    if st.button(f"Process Link"):
        with st.spinner(f"Fetching and parsing content from {selected_link}..."):
            full_text, text_chunks = process_single_link(selected_link)
            if full_text and text_chunks:
                st.session_state['processed_text'] = full_text
                st.session_state['processed_chunks'] = text_chunks
                st.session_state['processed_link'] = selected_link
                st.success("Successfully processed the document! You can now add it to the Vector Store below.")
            else:
                st.error(f"Failed to process the link. Reason: {text_chunks}")
                st.session_state['processed_text'] = None
                st.session_state['processed_chunks'] = None
                st.session_state['processed_link'] = ""

# --- 3. Display and Add to Vector Store ---
if st.session_state.get('processed_chunks'):
    st.markdown("---")
    st.header("3. Add Processed Document to Knowledge Library")
    
    st.subheader("Extracted Text Chunks (Preview)")
    st.write(f"The following document produced **{len(st.session_state['processed_chunks'])}** text chunks.")
    for i, chunk_data in enumerate(st.session_state['processed_chunks'][:3]):
        chunk_text = chunk_data.get("text", "")
        chunk_section = chunk_data.get("section", "Unknown")
        expander_title = f"Chunk {i+1} from Section: '{chunk_section}' (First 100 chars: '{chunk_text[:100].strip()}...')"
        with st.expander(expander_title):
            st.write(f"**Section:** {chunk_section}")
            st.markdown("---")
            st.write(chunk_text)

    if st.button("Add Chunks to Knowledge Library"):
        start_time = time.time()
        with st.spinner("Embedding chunks via OpenRouter and updating vector store..."):
            vs, status = create_vector_store(
                st.session_state['processed_chunks'], 
                st.session_state['processed_link']
            )
            end_time = time.time()
            duration = end_time - start_time
            if vs:
                success_message = f"{status} (Took {duration:.2f} seconds)"
                st.session_state.status_message = ("success", success_message)
                st.session_state['processed_text'] = None
                st.session_state['processed_chunks'] = None
                st.session_state['processed_link'] = ""
                st.rerun()
            else:
                st.error(status)

# --- 4. Discover Metrics in Documents ---
st.markdown("---")
st.header("4. Discover Available Metrics for Extraction")

# This section is for testing our new discovery function on a single document
if vector_store:
    # Get a list of unique documents already in the store
    all_docs_metadata = vector_store.get(include=["metadatas"])
    unique_sources = sorted(list(set(meta['source'] for meta in all_docs_metadata['metadatas'])))
    
    if unique_sources:
        st.info("Test the metric discovery process on a single document from your library.")
        doc_to_analyze = st.selectbox("Select a document from your library to analyze:", options=unique_sources)
        
        if st.button("Find All Metrics in This Document"):
            with st.spinner(f"Scanning '{doc_to_analyze}' for all quantifiable metrics..."):
                # Import and call our new function
                from query_handler import discover_metrics_in_doc
                
                discovered_metrics, status = discover_metrics_in_doc(doc_to_analyze)
            
            if discovered_metrics is not None:
                st.success(status)
                st.write("Discovered Metrics:")
                st.dataframe(discovered_metrics)
            else:
                st.error(status)
    else:
        st.info("Your Knowledge Library is empty. Add a document in Step 3 to begin.")
else:
    st.info("You must create a Knowledge Library first (by adding a document in Step 3).")
