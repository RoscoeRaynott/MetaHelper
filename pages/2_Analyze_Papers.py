# pages/2_Analyze_Papers.py

import streamlit as st
from data_ingestor import process_single_link # Import our new function

st.set_page_config(layout="wide")
st.title("📄 Paper Analysis and Ingestion")
st.markdown("This page allows you to process the papers found on the search page.")

# --- 1. Link Selection UI ---
st.header("1. Select a Link to Process")

# Check if links were saved from the main page
if 'links_for_rag' not in st.session_state or not st.session_state['links_for_rag']:
    st.warning("No links have been prepared for analysis. Please go to the 'RAG-Ready Medical Research Finder' page, perform a search, and click 'Prepare Links for Analysis' first.")
else:
    links = st.session_state['links_for_rag']
    st.info(f"Found {len(links)} links prepared from the search page.")
    
    # Create a dropdown to select one link for our test
    selected_link = st.selectbox("Choose a link to process and verify:", options=links)

    # --- 2. Processing and Verification UI ---
    if selected_link:
        st.header("2. Process and Verify")
        
        if st.button(f"Process: {selected_link}"):
            with st.spinner(f"Fetching and parsing content from the selected link..."):
                # Call the main function from our new module
                full_text, text_chunks = process_single_link(selected_link)
            
            if full_text and text_chunks:
                st.success("Successfully processed the document!")
                
                # Display the results for verification
                st.subheader("Extracted Full Text (Cleaned)")
                st.text_area("Full Text", full_text, height=300)
                
                st.subheader(f"Text Chunks ({len(text_chunks)} chunks created)")
                st.write("These are the small pieces of text that will be converted into vectors for the RAG pipeline.")
                
                # Display a few chunks as an example
                for i, chunk in enumerate(text_chunks[:3]): # Show first 3 chunks
                    with st.expander(f"Chunk {i+1} (First 100 characters: '{chunk[:100].strip()...}')"):
                        st.write(chunk)
            else:
                st.error(f"Failed to process the link. Reason: {text_chunks}") # The second return value is the error message
