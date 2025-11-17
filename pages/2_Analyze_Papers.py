# pages/2_Analyze_Papers.py

import streamlit as st
#import os
from data_ingestor import process_single_link
# from vector_store_manager import create_vector_store, load_vector_store
# from vector_store_manager import clear_vector_store
from vector_store_manager import add_to_in_memory_vector_store, clear_in_memory_vector_store
import time

st.set_page_config(layout="wide")
st.title("📄 Paper Analysis and Ingestion")
st.markdown("Process papers and add them to a temporary, in-memory knowledge library for this session.")

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

# # --- 1. Vector Store Management UI ---
# st.header("1. Knowledge Library Status")

# vector_store = load_vector_store()
# if vector_store:
#     doc_count = vector_store._collection.count()
#     st.success(f"✅ Knowledge Library is active and contains **{doc_count}** document chunks.")
    
#     # Get the list of unique source documents in the library
#     all_docs_metadata = vector_store.get(include=["metadatas"])
#     sources_in_library = sorted(list(set(meta['source'] for meta in all_docs_metadata['metadatas'])))
    
#     with st.expander("View documents currently in the library"):
#         for source in sources_in_library:
#             st.text(source)

#     if st.button("Clear Knowledge Library"):
#         success, message = clear_vector_store()
#         if success:
#             st.success(message)
#             # Clear any processed data from the session and rerun to reflect the change
#             st.session_state['processed_text'] = None
#             st.session_state['processed_chunks'] = None
#             st.session_state['processed_link'] = ""
#             st.rerun()
#         else:
#             st.error(message)
# else:
#     st.warning("⚠️ No Knowledge Library found. Process and add documents below to create one.")

# --- 1. Knowledge Library Status ---
st.header("1. Knowledge Library Status")

# Load the store directly from session state
vector_store = st.session_state.get('vector_store', None)
if vector_store:
    doc_count = vector_store._collection.count()
    st.success(f"✅ In-memory library is active and contains **{doc_count}** document chunks.")
    
    all_docs_metadata = vector_store.get(include=["metadatas"])
    sources_in_library = sorted(list(set(meta['source'] for meta in all_docs_metadata['metadatas'])))
    
    with st.expander("View documents currently in the library"):
        for source in sources_in_library:
            st.text(source)

    if st.button("Clear Knowledge Library"):
        success, message = clear_in_memory_vector_store()
        if success:
            st.session_state['processed_text'] = None
            st.session_state['processed_chunks'] = None
            st.session_state['processed_link'] = ""
            st.session_state.status_message = ("success", message)
            st.rerun()  # <-- Force a UI refresh
        else:
            st.error(message)
else:
    st.warning("⚠️ No Knowledge Library found for this session. Process and add a document below.")

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
            vs, status = add_to_in_memory_vector_store(
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

# --- 4. Analyze Library and Select Metrics for Extraction ---
st.markdown("---")
st.header("4. Analyze Library & Select Metrics for Table")

# Initialize a session state variable to hold the discovered metrics
if 'discovered_metrics_df' not in st.session_state:
    st.session_state.discovered_metrics_df = None

if vector_store:
    # --- Part A: Full Library Analysis ---
    st.subheader("Analyze Full Library to Find Common Metrics")
    st.write("This will scan all documents in your library to find the most common metrics available for extraction. This process can take several minutes depending on the number of documents.")
    
    if st.button("Analyze Library & Find Common Metrics"):
        with st.spinner("Scanning all documents to discover and normalize metrics..."):
            # Import and call our new controller function
            from query_handler import discover_and_normalize_metrics_from_library
            
            metrics_df, status = discover_and_normalize_metrics_from_library()
            
            if metrics_df is not None and not metrics_df.empty:
                st.session_state.discovered_metrics_df = metrics_df
                st.success(status)
            else:
                st.session_state.discovered_metrics_df = None
                st.error(status)
        st.rerun() # Rerun to display the dataframe below immediately

    # --- Part B: Display results of full analysis ---
    if st.session_state.discovered_metrics_df is not None:
        st.subheader("Discovered Common Metrics")
        st.write("The following metrics were found across the documents in your library, sorted by frequency.")
        st.dataframe(st.session_state.discovered_metrics_df)

else:
    st.info("You must add documents to the Knowledge Library before you can analyze it.")

# --- 5. Generate Final Outcome Table ---
st.markdown("---")
st.header("5. Generate Outcome Summary Table")

if vector_store:
    user_outcome = st.session_state.get('user_outcome_of_interest', '')
    
    if not user_outcome:
        st.warning("Please perform a search on the main page and provide an 'Outcome of Interest' to generate the table.")
    else:
        st.info(f"The table will be generated by extracting the outcome: **'{user_outcome}'** from all documents in the library.")
        
        if st.button("Generate Summary Table"):
            with st.spinner("Analyzing all documents in the library to extract the outcome... This may take some time."):
                # Import and call our new table generator function
                from query_handler import generate_outcome_table
                
                extracted_df, status = generate_outcome_table(user_outcome)
            
            st.success(status)
            if extracted_df is not None:
                st.dataframe(extracted_df)
            else:
                st.error("Could not generate the table.")
else:
    st.info("You must add documents to the Knowledge Library before you can generate a table.")

# --- 6. Test ClinicalTrials.gov Table Parser ---
st.markdown("---")
st.header("6. Test Specialized Table Parser (for ClinicalTrials.gov)")

if vector_store:
    all_docs_metadata = vector_store.get(include=["metadatas"])
    # Filter for only ClinicalTrials.gov links
    ct_sources = sorted(list(set(
        meta['source'] for meta in all_docs_metadata['metadatas'] 
        if "clinicaltrials.gov" in meta['source']
    )))
    
    if ct_sources:
        doc_to_parse = st.selectbox("Select a ClinicalTrials.gov document to test:", options=ct_sources)
        
        # We need the user to provide the exact title of the table to parse
        exact_table_title = st.text_input("Enter the EXACT title of the outcome table to parse:", 
                                          placeholder="e.g., Mortality at 28 Days (n (%))")

        if st.button("Test Table Parser"):
            if doc_to_parse and exact_table_title:
                with st.spinner("Fetching page and parsing table..."):
                    from query_handler import test_table_parser
                    
                    parsed_data, status = test_table_parser(doc_to_parse, exact_table_title)
                
                st.info(status)
                if parsed_data:
                    st.write("Successfully extracted data:")
                    st.dataframe(parsed_data)
            else:
                st.warning("Please select a document and enter a table title.")
    else:
        st.info("No ClinicalTrials.gov documents are in the library to test.")
