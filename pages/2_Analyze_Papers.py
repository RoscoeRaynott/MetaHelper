# pages/2_Analyze_Papers.py

import streamlit as st
#import os
from data_ingestor import process_single_link
# from vector_store_manager import create_vector_store, load_vector_store
# from vector_store_manager import clear_vector_store
from vector_store_manager import add_to_in_memory_vector_store, clear_in_memory_vector_store
from data_ingestor import get_ct_gov_table_titles_from_api
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
            with st.spinner("Analyzing all documents..."):
                from query_handler import generate_outcome_table
                extracted_df, source_list, status = generate_outcome_table(user_outcome)
            
            st.success(status)
            if extracted_df is not None:
                st.session_state['summary_table_df'] = extracted_df
                st.session_state['summary_table_sources'] = source_list
                st.session_state['user_outcome'] = user_outcome
        
        # Display table with refresh buttons (outside button click)
        if 'summary_table_df' in st.session_state:
            # Add header row
            header1, header2, header3, header4 = st.columns([3, 2, 4, 1])
            with header1:
                st.markdown("**Source Document**")
            with header2:
                st.markdown("**Metric Definition**")
            with header3:
                st.markdown(f"**Outcome: {st.session_state['user_outcome']}**")
            with header4:
                st.markdown("**Refresh**")
            
            st.divider()
            for idx, row in st.session_state['summary_table_df'].iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 4, 1])
                
                with col1:
                    st.markdown(f"[Link]({row['Source Document']})")
                with col2:
                    st.text(row.get('Metric Definition', 'N/A'))
                with col3:
                    st.text(row[f"Outcome: {st.session_state['user_outcome']}"])
                with col4:
                    if st.button("🔄", key=f"refresh_{idx}"):
                        with st.spinner("Refreshing..."):
                            from query_handler import extract_outcome_from_doc
                            source_url = st.session_state['summary_table_sources'][idx]
                            new_findings, new_definition, _ = extract_outcome_from_doc(source_url, st.session_state['user_outcome'])
                            new_value = " | ".join(new_findings) if new_findings else "N/A"
                            st.session_state['summary_table_df'].at[idx, f"Outcome: {st.session_state['user_outcome']}"] = new_value
                            st.session_state['summary_table_df'].at[idx, 'Metric Definition'] = new_definition
                            st.rerun()
else:
    st.info("You must add documents to the Knowledge Library before you can generate a table.")

# --- 6. Test Specialized CT.gov API Parser ---
st.markdown("---")
st.header("6. Test Specialized ClinicalTrials.gov API Parser")

if vector_store:
    # Get the user's outcome of interest from the main page's search
    user_outcome = st.session_state.get('user_outcome_of_interest', '')
    
    if not user_outcome:
        st.warning("To test the parser, please perform a search on the main page with an 'Outcome of Interest' defined.")
    else:
        all_docs_metadata = vector_store.get(include=["metadatas"])
        # Filter for only ClinicalTrials.gov links
        ct_sources = sorted(list(set(
            meta['source'] for meta in all_docs_metadata['metadatas'] 
            if "clinicaltrials.gov" in meta['source']
        )))
        
        if ct_sources:
            st.info(f"This will test the API parser on a selected document for the outcome: **'{user_outcome}'**")
            doc_to_parse = st.selectbox(
                "Select a ClinicalTrials.gov document to test:", 
                options=ct_sources,
                key="ct_gov_parser_test"
            )
            
            if st.button("Test API Parser"):
                if doc_to_parse:
                    with st.spinner(f"Calling CT.gov API for {doc_to_parse} and parsing results..."):
                        # Import the function we want to test
                        from data_ingestor import extract_ct_gov_outcome_from_api
                        import re # Import re for the NCT ID extraction

                        # Extract the NCT ID from the URL to pass to the function
                        nct_match = re.search(r'NCT\d+', doc_to_parse)
                        if nct_match:
                            nct_id = nct_match.group(0)
                            parsed_data, status = extract_ct_gov_outcome_from_api(nct_id, user_outcome)
                            
                            st.info(status)
                            if parsed_data:
                                st.write("Successfully extracted data:")
                                # Display as a simple list for this test
                                st.write(parsed_data)
                        else:
                            st.error("Could not extract NCT ID from the selected URL.")
                else:
                    st.warning("Please select a document to test.")
        else:
            st.info("No ClinicalTrials.gov documents are in the library to test.")
else:
    st.info("You must add documents to the Knowledge Library before you can test the parser.")

# --- 7. Test CT.gov Table Title Lister ---
st.markdown("---")
st.header("7. Test ClinicalTrials.gov Table Title Lister")

# Use st.session_state.get to be safe
vector_store_exists = st.session_state.get('vector_store') is not None

if vector_store_exists:
    vector_store = st.session_state.get('vector_store')
    all_docs_metadata = vector_store.get(include=["metadatas"])
    ct_sources = sorted(list(set(
        meta['source'] for meta in all_docs_metadata['metadatas'] 
        if "clinicaltrials.gov" in meta['source']
    )))
    
    if ct_sources:
        st.info("This will call the CT.gov API and list all data table titles found in the results section.")
        doc_to_list = st.selectbox(
            "Select a ClinicalTrials.gov document to list its tables:", 
            options=ct_sources,
            key="ct_gov_title_lister_test"
        )
        
        if st.button("List Table Titles"):
            if doc_to_list:
                with st.spinner(f"Calling CT.gov API for {doc_to_list} and finding table titles..."):
                    from data_ingestor import get_ct_gov_table_titles_from_api
                    import re

                    nct_match = re.search(r'NCT\d+', doc_to_list)
                    if nct_match:
                        nct_id = nct_match.group(0)
                        table_titles, status = get_ct_gov_table_titles_from_api(nct_id)
                        
                        st.info(status)
                        if table_titles:
                            st.write("Found the following table titles:")
                            # Display as a numbered list
                            for i, title in enumerate(table_titles):
                                st.text(f"{i+1}. {title}")
                        elif table_titles is not None: # Handles empty list case
                            st.warning("No table titles were found in the results section of this trial.")
                    else:
                        st.error("Could not extract NCT ID from the selected URL.")
            else:
                st.warning("Please select a document to test.")
    else:
        st.info("No ClinicalTrials.gov documents are in the library to test.")
else:
    st.info("You must add documents to the Knowledge Library before you can test this feature.")

# In pages/2_Analyze_Papers.py
# ADD THIS ENTIRE BLOCK TO THE END OF THE FILE

# --- 8. Test Title Locator (LLM Filter) ---
st.markdown("---")
st.header("8. Test Title Locator (LLM Filter)")

if st.session_state.get('vector_store'):
    user_outcome = st.session_state.get('user_outcome_of_interest', '')
    
    if not user_outcome:
        st.warning("To test the locator, please perform a search on the main page with an 'Outcome of Interest' defined.")
    else:
        vector_store = st.session_state.get('vector_store')
        all_docs_metadata = vector_store.get(include=["metadatas"])
        ct_sources = sorted(list(set(
            meta['source'] for meta in all_docs_metadata['metadatas'] 
            if "clinicaltrials.gov" in meta['source']
        )))
        
        if ct_sources:
            st.info(f"This will first get all table titles for a document, then use an LLM to select the ones relevant to: **'{user_outcome}'**")
            doc_to_locate = st.selectbox(
                "Select a ClinicalTrials.gov document to test the locator on:", 
                options=ct_sources,
                key="ct_gov_locator_test"
            )
            
            if st.button("Find Relevant Titles"):
                if doc_to_locate:
                    with st.spinner(f"Step 1: Getting all titles from {doc_to_locate}..."):
                        from data_ingestor import get_ct_gov_table_titles_from_api
                        import re
                        nct_match = re.search(r'NCT\d+', doc_to_locate)
                        if not nct_match:
                            st.error("Could not extract NCT ID.")
                        else:
                            nct_id = nct_match.group(0)
                            all_titles, status = get_ct_gov_table_titles_from_api(nct_id)
                    
                    if all_titles:
                        st.write("Found all titles. Now running Step 2: LLM Selection...")
                        with st.spinner("Asking LLM to find relevant titles..."):
                            from query_handler import find_relevant_table_titles
                            
                            relevant_titles, status = find_relevant_table_titles(all_titles, user_outcome)
                        
                        st.info(status)
                        if relevant_titles:
                            st.write("LLM identified the following relevant titles:")
                            st.dataframe(relevant_titles)
                            # --- NEW: Run Extraction on these titles ---
                            st.markdown("---")
                            st.info("Step 3: Extracting Data for Selected Titles...")
                            
                            # Import our new function
                            from data_ingestor import extract_data_for_selected_titles
                            
                            # Call the function with the NCT ID and the list of titles found by the LLM
                            extracted_data, ext_status = extract_data_for_selected_titles(nct_id, relevant_titles)
                            
                            if extracted_data:
                                st.success("Data Extraction Successful!")
                                # Display the results in a nice table
                                st.table([
                                    {"Metric/Table Name": k, "Extracted Values": v} 
                                    for k, v in extracted_data.items()
                                ])
                            else:
                                st.error(f"Extraction failed: {ext_status}")
                            # --- END NEW ---
                        else:
                            st.warning("LLM did not identify any relevant titles from the list.")
                else:
                    st.warning("Please select a document to test.")
        else:
            st.info("No ClinicalTrials.gov documents are in the library to test.")
else:
    st.info("You must add documents to the Knowledge Library before you can test this feature.")
