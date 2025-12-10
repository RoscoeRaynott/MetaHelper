# query_handler.py

import streamlit as st
import json
from langchain_openai import ChatOpenAI
#from langchain.chains.retrieval_qa.base import RetrievalQA
import pandas as pd

def clean_json_output(text):
    """
    Robustly extracts JSON from LLM output by finding the first '{' and last '}'.
    Handles Markdown blocks and conversational filler.
    """
    text = text.strip()
    
    # 1. Find the start of the JSON object
    start_index = text.find('{')
    if start_index == -1:
        return text # No JSON object found, return original text (will likely fail parsing)
        
    # 2. Find the end of the JSON object
    end_index = text.rfind('}')
    if end_index == -1:
        return text # Incomplete JSON
        
    # 3. Extract just the JSON part
    # Add 1 to end_index to include the closing brace
    return text[start_index : end_index + 1]
    
@st.cache_resource
def get_llm():
    """Initializes the LLM for question answering, configured for OpenRouter."""
    if "OPENROUTER_API_KEY" not in st.secrets:
        st.error("Openrouter_API_key not found in Streamlit secrets. Please add it.")
        return None
    try:
        # Use a model known for strong instruction-following and JSON capabilities
        llm = ChatOpenAI(
            model_name="meta-llama/llama-3.3-70b-instruct:free",#"amazon/nova-2-lite-v1:free",#"google/gemini-2.0-flash-exp:free",#"meta-llama/llama-3-8b-instruct", # "microsoft/Phi-3-mini-128k-instruct",#"meta-llama/llama-3-8b-instruct",
            openai_api_key=st.secrets.get("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.0, # Crucial for factual, non-creative extraction
            max_tokens=4096,
            # model_kwargs={
            #     "response_format": {"type": "json_object"} # Instruct the model to output JSON
            # }
            # model_name="google/gemma-2-9b-it",
            # openai_api_key=st.secrets.get("OPENROUTER_API_KEY"),
            # openai_api_base="https://openrouter.ai/api/v1",
            # temperature=0.0,
            # max_tokens=4096, # Gemma 2 has an 8k context window, 4k for output is safe
            # # We can try re-enabling JSON mode, as many modern models support it
            # model_kwargs={"response_format": {"type": "json_object"}}
        )
        return llm
    except Exception as e:
        st.error(f"Failed to initialize LLM via OpenRouter: {e}")
        return None

# In query_handler.py
# REPLACE the entire discover_metrics_in_doc function with this new version

def discover_metrics_in_doc(source_url):
    """
    Performs a RAG query on a single document to find all quantifiable metrics.
    Retrieves ALL chunks for full context, and guarantees the return is a list of strings.
    """
    import re

    vector_store = st.session_state.get('vector_store', None)
    if not vector_store:
        return None, "Vector Store not found in session."

    llm = get_llm()
    if not llm:
        return None, "LLM not initialized."

    # --- Retrieve ALL chunks for the document ---
    all_doc_chunks = vector_store.get(
        where={"source": source_url},
        include=["documents"]
    )
    context_string = "\n\n---\n\n".join(all_doc_chunks.get("documents", []))

    if not context_string.strip():
        return [], "No text content found for this document in the vector store."

    # --- Helper: force everything into strings ---
    def _force_strings(metrics_list):
        cleaned = []
        for m in metrics_list:
            if isinstance(m, dict):
                # Pick "metric" key if it exists, else first value
                if "metric" in m:
                    cleaned.append(str(m["metric"]))
                elif len(m.values()) > 0:
                    cleaned.append(str(list(m.values())[0]))
                else:
                    cleaned.append(str(m))
            else:
                cleaned.append(str(m))
        return cleaned

    # --- Prompt with full document context ---
    discovery_prompt = f"""
    Here is the full text of a research paper:
    --- CONTEXT START ---
    {context_string}
    --- CONTEXT END ---

    Based ONLY on the context provided above, identify and list every single quantifiable statistical metric or outcome measure that is reported with a numerical value.
    Do not include metrics that are only mentioned without an associated result.
    Your response MUST be a valid JSON object containing a single key "metrics", which is a list of strings.
    Example: {{"metrics": ["Sample Size (participants)", "Mean Age (years)", "Baseline BMI (kg/m^2)"]}}
    If no metrics are found, return an empty list: {{"metrics": []}}
    """

    try:
        # Invoke the LLM
        result = llm.invoke(discovery_prompt)
        raw_output = getattr(result, "content", str(result))

        st.write("🔎 Raw LLM Output:", raw_output)

        # Try JSON first
        try:
            answer_json = json.loads(raw_output)
            metrics_list = _force_strings(answer_json.get("metrics", []))
            if metrics_list:
                return metrics_list, "Discovery successful."
        except Exception:
            st.warning("⚠️ JSON parsing failed, using fallback parsing.")

        # --- Fallback: regex-based extraction ---
        candidates = re.findall(r'([A-Za-z][\w\s/%\(\)\-]*?\d+[\w\s/%\(\)\-]*)', raw_output)
        fallback_metrics = _force_strings(candidates)

        if fallback_metrics:
            return fallback_metrics, "Discovery fallback: parsed metrics from raw text."
        else:
            return [], "Discovery complete but no numeric-like metrics found."

    except Exception as e:
        return [], f"An error occurred during discovery: {e}"



def _normalize_metrics(raw_metrics_list, llm):
    """
    Uses an LLM to normalize a messy list of metric names.
    """
    # Get unique, non-empty metric names
    unique_metrics = sorted(list(set(m for m in raw_metrics_list if m)))
    
    if not unique_metrics:
        return {}

    # Create a single string of the metrics list for the prompt
    metrics_string = ", ".join(f'"{m}"' for m in unique_metrics)
    
    normalization_prompt = f"""
    You are a data cleaning expert. I have a list of metric names extracted from multiple scientific papers: [{metrics_string}].
    Your task is to group synonyms and normalize them to a single, canonical name.
    Respond in a valid JSON format where keys are the clean, canonical names and values are a list of the original synonyms from the input list that map to it.
    Example Input: ["BMI", "Body Mass Index", "BMI (kg/m^2)", "Age", "Mean Age (years)"]
    Example Response: {{
        "Baseline BMI (kg/m^2)": ["BMI", "Body Mass Index", "BMI (kg/m^2)"],
        "Mean Age (years)": ["Age", "Mean Age (years)"]
    }}
    """
    
    try:
        # Note: Using .invoke() directly on the string with ChatOpenAI
        result = llm.invoke(normalization_prompt)
        # The response from ChatOpenAI is an AIMessage object, its content is in the .content attribute
        normalized_map = json.loads(result.content)
        return normalized_map
    except (json.JSONDecodeError, TypeError) as e:
        st.error(f"Failed to parse LLM response during normalization: {e}")
        st.write("LLM Raw Output for Normalization:", result.content if 'result' in locals() else "No result")
        return None
    except Exception as e:
        st.error(f"An error occurred during normalization: {e}")
        return None

def discover_and_normalize_metrics_from_library():
    """
    Scans all documents in the vector store, discovers all metrics,
    normalizes them, and returns a counted & sorted list of common metrics.
    """
    vector_store = st.session_state.get('vector_store', None)
    if not vector_store:
        return None, "Vector Store is not available."

    llm = get_llm()
    if not llm:
        return None, "LLM is not available."

    all_docs_metadata = vector_store.get(include=["metadatas"])
    unique_sources = sorted(list(set(meta['source'] for meta in all_docs_metadata['metadatas'])))
    
    if not unique_sources:
        return None, "No documents found in the library to analyze."

    # --- Phase 1: Discovery ---
    raw_metrics_per_doc = {}
    progress_bar = st.progress(0, text="Starting discovery phase...")
    
    for i, source_url in enumerate(unique_sources):
        progress_bar.progress((i + 1) / len(unique_sources), text=f"Discovering metrics in: {source_url}")
        metrics_list, status = discover_metrics_in_doc(source_url)
        if metrics_list:
            raw_metrics_per_doc[source_url] = metrics_list
    
    progress_bar.empty()
    
    all_raw_metrics = [metric for metrics in raw_metrics_per_doc.values() for metric in metrics]
    if not all_raw_metrics:
        return pd.DataFrame(), "Discovery complete. No quantifiable metrics were found across any documents."

    # --- Phase 2: Normalization ---
    with st.spinner("Normalizing discovered metric names..."):
        normalized_map = _normalize_metrics(all_raw_metrics, llm)
    
    if not normalized_map:
        return pd.DataFrame(), "Metric normalization failed. Cannot proceed."

    # --- 🔎 Show raw + normalized metrics per document ---
    synonym_to_canonical_map = {
        synonym.lower(): canonical
        for canonical, synonyms in normalized_map.items()
        for synonym in synonyms
    }
    
    for doc, raw_metrics in raw_metrics_per_doc.items():
        if not raw_metrics:
            st.write(f"📄 {doc}: No metrics discovered.")
            continue
        normalized = []
        for metric in raw_metrics:
            norm = synonym_to_canonical_map.get(metric.lower(), metric)
            normalized.append(norm)
        st.write(f"📄 {doc}")
        st.write("   Raw metrics:", raw_metrics)
        st.write("   Normalized metrics:", normalized)

    # --- Phase 3: Counting and Formatting ---
    # Invert the map for easy lookup
    synonym_to_canonical_map = {synonym.lower(): canonical for canonical, synonyms in normalized_map.items() for synonym in synonyms}
    
    # Count occurrences of each CANONICAL metric across documents
    canonical_counts = {}
    for source_metrics in raw_metrics_per_doc.values():
        canonical_metrics_in_doc = set()
        for metric in source_metrics:
            if metric.lower() in synonym_to_canonical_map:
                canonical_metrics_in_doc.add(synonym_to_canonical_map[metric.lower()])
        
        for canonical_metric in canonical_metrics_in_doc:
            canonical_counts[canonical_metric] = canonical_counts.get(canonical_metric, 0) + 1
            
    if not canonical_counts:
        return pd.DataFrame(), "Could not count any canonical metrics."

    # Create a DataFrame for display
    metrics_df = pd.DataFrame({
        "Metric Name": canonical_counts.keys(),
        "Found in # Docs": canonical_counts.values()
    })
    metrics_df["Prevalence (%)"] = (metrics_df["Found in # Docs"] / len(unique_sources)) * 100
    metrics_df = metrics_df.sort_values(by="Found in # Docs", ascending=False).reset_index(drop=True)
    
    return metrics_df, "Metric discovery and normalization complete."

def extract_outcome_from_doc(source_url, user_outcome_of_interest):
    """
    Performs a targeted RAG query to "scoop" all raw data related to an outcome.
    Step 1: Locator (Find name + definition).
    Step 2: Scooper (Extract all relevant text/table rows).
    """
    vector_store = st.session_state.get('vector_store', None)
    if not vector_store: return None, "Vector Store not found.", "Error"
    llm = get_llm()
    if not llm: return None, "LLM not initialized.", "Error"

    # --- Step 1: The "Locator" Query (Unchanged) ---
    locator_retriever = vector_store.as_retriever(
        search_kwargs={'k': 5, 'filter': {
            "$and": [
                {'source': source_url},
                {'section': {"$in": ["Outcomes", "Results", "Abstract"]}}
            ]
        }}
    )
    
    locator_context_chunks = locator_retriever.invoke(user_outcome_of_interest)
    if not locator_context_chunks:
        return "N/A (No relevant sections found)", "Extraction complete."
        
    context_string_for_locator = "\n\n---\n\n".join([doc.page_content for doc in locator_context_chunks])

    locator_prompt = f"""
    Based ONLY on the context below, find the single, most relevant, full and exact name of the outcome measure related to "{user_outcome_of_interest}".
    Context: {context_string_for_locator}
    Respond in JSON with one key "exact_metric_name". If not found, return null.
    """
    
    exact_metric_name = user_outcome_of_interest
    try:
        result = llm.invoke(locator_prompt)
        cleaned_content = clean_json_output(result.content)
        answer_json = json.loads(cleaned_content)
        if answer_json.get("exact_metric_name"): exact_metric_name = answer_json.get("exact_metric_name")
    except Exception:
        pass
    
    # --- Step 2: The "Scooper" Query (Modified) ---
    # extractor_retriever = vector_store.as_retriever(
    #     search_kwargs={'k': 20, 'filter': { # Increased k to capture more context/table rows
    #         "$and": [
    #             {'source': source_url},
    #             {'section': {"$in": ["Results", "Conclusion", "Abstract"]}}
    #         ]
    #     }}
    # )
    extractor_retriever = vector_store.as_retriever(
        search_kwargs={'k': 40, 'filter': {'source': source_url}} 
    )
    
    # extractor_query = f"{user_outcome_of_interest} {exact_metric_name} table data values"
    # context_chunks_for_extractor = extractor_retriever.invoke(extractor_query)

    # --- CHANGE: Ensemble Retrieval (Merged Scoop) ---
    # 1. Search using the User's Input (The "Anchor")
    chunks_original = extractor_retriever.invoke(user_outcome_of_interest)
    
    # 2. Search using the LLM's Found Name (The "Specific")
    chunks_specific = []
    if exact_metric_name and exact_metric_name.lower() != user_outcome_of_interest.lower():
        chunks_specific = extractor_retriever.invoke(exact_metric_name)
    
    # 3. Merge and Deduplicate based on text content
    # Using a dict preserves order while removing duplicates
    combined_chunks_map = {doc.page_content: doc for doc in chunks_original + chunks_specific}
    context_chunks_for_extractor = list(combined_chunks_map.values())
    # -------------------------------------------------
    
    if not context_chunks_for_extractor:
        return "N/A (No data found for this metric)", metric_definition, "Extraction complete."

    context_string_for_extractor = "\n\n---\n\n".join([doc.page_content for doc in context_chunks_for_extractor])

    # --- NEW PROMPT: The "Scoop" ---
    extractor_prompt = f"""
    You are a research assistant. Your goal is to extract all raw data related to the outcome: "{exact_metric_name}".
    
    Context:
    {context_string_for_extractor}

    Instructions:
    1. Identify every sentence or Markdown table row in the context that reports data for "{exact_metric_name}".
    2. Keep the format exactly as it is in the text (preserve Markdown table syntax like | row | value |).
    3. Do NOT summarize. Copy the specific details, values, confidence intervals, and p-values.
    4. Exclude data that is clearly about a different, unrelated outcome.

    RESPONSE FORMAT:
    Just return the raw text block. Do not wrap it in JSON. Do not add "Here is the data". Just give me the data.
    """

    try:
        result = llm.invoke(extractor_prompt)
        
        # --- NEW PARSING: Direct Text ---
        data_block = result.content.strip()
        
        # # Debug output
        # st.warning(f"🔍 DEBUG SCOOP for {source_url}:")
        # st.text(data_block) 
        
        if not data_block:
            return "N/A (Value not found in text)", "Extraction complete."
            
        return data_block,  "Extraction successful."
        
    except Exception as e:
        return None,  f"An error occurred during extraction: {e}"

# def extract_outcome_from_doc(source_url, user_outcome_of_interest):
#     """
#     Performs a targeted, two-step RAG query to extract all values for a specific outcome.
#     Includes robust JSON cleaning and debugging.
#     """
#     vector_store = st.session_state.get('vector_store', None)
#     if not vector_store: return None, "Vector Store not found in session."
#     llm = get_llm()
#     if not llm: return None, "LLM not initialized."

#     # --- Step 1: The "Locator" Query ---
#     locator_retriever = vector_store.as_retriever(
#         search_kwargs={'k': 5, 'filter': {
#             "$and": [
#                 {'source': source_url},
#                 {'section': {"$in": ["Outcomes", "Results", "Abstract"]}}
#             ]
#         }}
#     )
    
#     locator_context_chunks = locator_retriever.invoke(user_outcome_of_interest)
#     if not locator_context_chunks:
#         return ["N/A (No relevant sections found)"], "N/A", "Extraction complete."
        
#     context_string_for_locator = "\n\n---\n\n".join([doc.page_content for doc in locator_context_chunks])

#     locator_prompt = f"""
#     Based ONLY on the context below, find the single, most relevant, full and exact name of the outcome measure related to "{user_outcome_of_interest}".
#     ALSO find the full definition or expansion of any acronyms in that name (e.g. if name is "FBG", definition is "Fasting Blood Glucose").
#     Context: {context_string_for_locator}
#     Respond in JSON with two keys: "exact_metric_name" and "metric_definition".
#     If the definition is not found, set "metric_definition" to "N/A".
#     If the metric is not found, return null.
    
#     """
    
#     exact_metric_name = user_outcome_of_interest
#     metric_definition = "N/A" # Default value
#     try:
#         result = llm.invoke(locator_prompt)
#         cleaned_content = clean_json_output(result.content) # Clean the output
#         answer_json = json.loads(cleaned_content)
#         found_name = answer_json.get("exact_metric_name")
#         if found_name:
#             exact_metric_name = found_name
#             # st.info(f"Locator found exact metric name: '{exact_metric_name}'") # Optional debug
#         # Capture the definition
#         metric_definition = answer_json.get("metric_definition", "N/A")
#     except Exception:
#         # st.warning("Could not locate a more specific metric name, proceeding with user's term.")
#         pass
    
#     # --- Step 2: The "Extractor" Query ---
#     extractor_retriever = vector_store.as_retriever(
#         search_kwargs={'k': 10, 'filter': {
#             "$and": [
#                 {'source': source_url},
#                 {'section': {"$in": ["Results", "Conclusion", "Abstract"]}}
#             ]
#         }}
#     )

#     # Combine user term and found term for better retrieval
#     extractor_query = f"{user_outcome_of_interest}: {exact_metric_name}"
#     context_chunks_for_extractor = extractor_retriever.invoke(extractor_query)
    
#     if not context_chunks_for_extractor:
#         return ["N/A (No data found for this metric)"], metric_definition, "Extraction complete."

#     context_string_for_extractor = "\n\n---\n\n".join([doc.page_content for doc in context_chunks_for_extractor])

#     extractor_prompt = f"""
#     Based ONLY on the context below, extract the outcome "{exact_metric_name}" with its GROUP/ARM labels.

#     Context: {context_string_for_extractor}

#      1. Format each finding as "GroupName: value" (e.g., "Placebo (BT): 5.2 mg/dL").
#     2. Identify and define any acronyms used in the Group Names or Timepoints (e.g., "BT = Before Treatment").

#     Respond in JSON with two keys:
#     - "findings": a list of strings.
#     - "definitions": a single string containing definitions for any acronyms found in the groups. If none, return "".

#     Example: {{"findings": ["Control (BT): 100", "Control (AT): 90"], "definitions": "BT=Before Treatment, AT=After Treatment"}}
#     """

#     try:
#         result = llm.invoke(extractor_prompt)
#         # --- DEBUG INSERT ---
#         st.write(f"🔍 DEBUG for {source_url}:", result.content)
#         # --------------------
#         cleaned_content = clean_json_output(result.content)
#         answer_json = json.loads(cleaned_content)
#         findings_list = answer_json.get('findings', [])
#         group_definitions = answer_json.get('definitions', "")
        
#         # Combine the outcome definition (from Step 1) with group definitions (from Step 2)
#         if group_definitions and group_definitions.lower() != "n/a":
#             metric_definition = f"{metric_definition}. Key: {group_definitions}"
        
#         if not findings_list:
#             return ["N/A (Value not found in text)"], metric_definition, "Extraction complete."
            
#         return findings_list, metric_definition, "Extraction successful."
        
#     except (json.JSONDecodeError, KeyError, TypeError) as e:
#         st.error(f"Failed to parse LLM response: {e}")
#         return None, metric_definition, "Failed to parse LLM response."
#     except Exception as e:
#         return None, metric_definition, f"An error occurred during extraction: {e}"



def generate_outcome_table(outcome_of_interest):
    """
    Main controller to generate the final data table.
    Iterates through all unique documents in the vector store and extracts the
    specified outcome for each one.
    """
    vector_store = st.session_state.get('vector_store', None)
    if not vector_store:
        return None, "Vector Store not found. Please add documents first."

    all_docs_metadata = vector_store.get(include=["metadatas"])
    unique_sources = sorted(list(set(meta['source'] for meta in all_docs_metadata['metadatas'])))
    
    if not unique_sources:
        return None, "No documents found in the library to analyze."

    table_data = []
    progress_bar = st.progress(0, text="Starting table generation...")

    for i, source_url in enumerate(unique_sources):
        progress_bar.progress((i + 1) / len(unique_sources), text=f"Extracting from: {source_url}")

        # Default values
        findings_str = "N/A"
        definition_str = "N/A"
        placebo_data = "N/A"
        treatment_arms = "N/A"
        durations = "N/A"
        raw_scoop = "N/A"
                    
        # --- NEW: Filter out ClinicalTrials.gov links ---
        if "clinicaltrials.gov" in source_url:
            continue
        # --- END NEW ---
        
        # --- PUBMED WORKFLOW ---
        # 1. Scoop the raw data
        raw_data_block, status = extract_outcome_from_doc(source_url, outcome_of_interest)
        
        raw_scoop = raw_data_block # Store the raw text

        # 2. Analyze the data (Step 2)
        if "N/A" not in raw_data_block and raw_data_block.strip():
            analysis = analyze_outcome_data(raw_data_block, outcome_of_interest)
            placebo_data = analysis.get("placebo_data", "N/A")
            treatment_arms = analysis.get("treatment_arms", "N/A")
            durations = analysis.get("durations", "N/A")
            
            # For the main "Outcome" column, we can use the raw scoop or a summary. 
            # For now, let's keep the raw scoop as the main finding, or leave it blank if you prefer the specific columns.
            # Let's set findings_str to "See detailed columns" or similar if we have good analysis.
            findings_str = "See extracted details" 
        else:
            findings_str = "Data not found"

        table_data.append({
            "Source Document": source_url,
            f"Outcome: {outcome_of_interest}": findings_str,
            "Placebo Data": placebo_data,
            "Treatment Arms": treatment_arms,
            "Durations": durations,
            "Raw Data Scoop": raw_scoop
        })

    progress_bar.empty()
    if not table_data: return None, "Could not extract data."

    df = pd.DataFrame(table_data)
    return df, "Table generation complete."

    # In query_handler.py, add this new function at the end of the file

# def find_relevant_table_titles(all_titles, user_outcome_of_interest):
#     """
#     Uses an LLM to select the most relevant titles from a list based on the user's outcome.
#     """
#     llm = get_llm()
#     if not llm:
#         return None, "LLM not initialized."

#     # We need to remove the prefixes like "[Baseline]" for the LLM prompt
#     # but keep them for mapping back later.
#     titles_for_prompt = [title.split("] ", 1)[1] for title in all_titles]
#     titles_string = "\n".join(f"- {title}" for title in titles_for_prompt)

#     # --- NEW: DEBUGGING ---
#     st.warning("--- DEBUG: Data Sent to LLM Locator ---")
#     st.write("**User Outcome of Interest:**", user_outcome_of_interest)
#     st.write("**List of Titles Sent to LLM:**")
#     st.text(titles_string)
#     st.warning("--- END DEBUG ---")
#     # --- END NEW ---
    
#     locator_prompt = f"""
#     The user's query is: "{user_outcome_of_interest}"

#     From the following list, select the item that is the best semantic match to the user's query.
#     Return ONLY the single best matching item, exactly as it appears in the list. Do not add any other text.

#     List of items:
#     {titles_string}
#     """

#     try:
#         response_content = llm.invoke(locator_prompt).content.strip()
#         selected_titles_from_llm = {line.strip() for line in response_content.split("\n") if line.strip()}

#         # Now, map the LLM's selection back to the original titles with prefixes
#         final_relevant_titles = [
#             original_title for original_title in all_titles 
#             if original_title.split("] ", 1)[1] in selected_titles_from_llm
#         ]
        
#         if not final_relevant_titles:
#             return [], "LLM did not find any relevant titles."

#         return final_relevant_titles, "Successfully identified relevant titles."

#     except Exception as e:
#         st.error(f"An error occurred during the LLM locator step: {e}")
#         # Fallback to simple string matching if the LLM fails
#         st.warning("LLM locator failed. Falling back to simple keyword matching.")
#         fallback_titles = [
#             title for title in all_titles 
#             if user_outcome_of_interest.lower() in title.lower()
#         ]
#         return fallback_titles, "Used fallback keyword matching."


def find_relevant_table_titles(all_titles, user_outcome_of_interest):
    """
    Uses an LLM to select the most relevant title from a list based on the user's outcome.
    Enhanced with multiple strategies to force concise output.
    """
    llm = get_llm()
    if not llm:
        return None, "LLM not initialized."

    # Remove prefixes for cleaner matching
    titles_for_prompt = [title.split("] ", 1)[1] if "] " in title else title for title in all_titles]
    
    # Strategy 1: Numbered list for easier parsing
    titles_string = "\n".join(f"{i+1}. {title}" for i, title in enumerate(titles_for_prompt))

    # Strategy 2: Extremely strict prompt with multiple constraints
    locator_prompt = f"""You must respond with ONLY numbers separated by commas.

User query: "{user_outcome_of_interest}"

Select ALL relevant matches from this list (maximum 3 most relevant):
{titles_string}

CRITICAL INSTRUCTIONS:
- Output ONLY numbers separated by commas (e.g., "3,7,12" or "5")
- Do NOT write any explanation
- Do NOT write "The matches are..."
- Do NOT use JSON
- Just the numbers

Your response:"""

    try:
        # Strategy 3: Reduce max_tokens drastically to prevent long responses
        response = llm.invoke(locator_prompt)
        response_content = response.content.strip()
        
        # --- DEBUGGING OUTPUT ---
        st.warning("--- DEBUG: LLM Response ---")
        st.write("**Raw LLM Output:**", response_content)
        st.warning("--- END DEBUG ---")
        
        # Strategy 4: Multiple parsing methods
        
        # Method A: Parse comma-separated numbers
        try:
            # Split by comma and parse each number
            numbers = [int(n.strip()) for n in response_content.replace(' ', '').split(',')]
            selected_indices = [n - 1 for n in numbers if 0 < n <= len(all_titles)]
            
            # Limit to top 4
            selected_indices = selected_indices[:1]  # <-- THIS IS THE [:4] YOU'RE LOOKING FOR
            
            if selected_indices:
                selected_titles = [all_titles[idx] for idx in selected_indices]
                st.success(f"✓ Successfully matched to {len(selected_titles)} title(s)")
                return selected_titles, "Successfully identified relevant titles."
        except ValueError:
            pass  # Try next method
        
        # Method B: Extract first number from response
        import re
        numbers = re.findall(r'\b(\d+)\b', response_content)
        if numbers:
            selected_index = int(numbers[0]) - 1
            if 0 <= selected_index < len(all_titles):
                selected_title = all_titles[selected_index]
                st.success(f"✓ Successfully matched to: {selected_title}")
                return [selected_title], "Successfully identified relevant title."
        
        # Method C: Fuzzy string matching (fallback)
        st.warning("Could not parse number, attempting fuzzy matching...")
        from difflib import SequenceMatcher
        
        best_match = None
        best_score = 0
        
        for original_title in all_titles:
            clean_title = original_title.split("] ", 1)[1] if "] " in original_title else original_title
            score = SequenceMatcher(None, response_content.lower(), clean_title.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = original_title
        
        if best_match and best_score > 0.3:  # Threshold for acceptable match
            st.info(f"Fuzzy match found (score: {best_score:.2f}): {best_match}")
            return [best_match], "Used fuzzy matching fallback."
        
        # Method D: Keyword matching (final fallback)
        st.warning("Fuzzy matching failed. Using keyword matching...")
        keyword_matches = [
            title for title in all_titles 
            if user_outcome_of_interest.lower() in title.lower()
        ]
        
        if keyword_matches:
            return keyword_matches, "Used keyword matching fallback."
        
        return [], "Could not identify any relevant titles."

    except Exception as e:
        st.error(f"An error occurred during the LLM locator step: {e}")
        
        # Ultimate fallback: keyword matching
        st.warning("LLM locator failed completely. Using keyword matching fallback.")
        fallback_titles = [
            title for title in all_titles 
            if user_outcome_of_interest.lower() in title.lower()
        ]
        
        if fallback_titles:
            return fallback_titles, "Used keyword matching fallback after error."
        else:
            return [], "No matches found even with keyword fallback."

def analyze_outcome_data(raw_data_block, outcome_name):
    """
    Step 2: Analyzes the "scooped" raw data.
    Uses a "Retry Loop" to ensure high-quality extraction.
    """
    llm = get_llm()
    if not llm: return None

    best_result = {
        "placebo_data": "N/A",
        "treatment_arms": "N/A",
        "durations": "N/A"
    }

    # --- AUTOMATED RETRY LOOP (Max 3 attempts) ---
    for attempt in range(3):
        try:
            # --- Pass 1: The Classifier (Identify Groups) ---
            classification_prompt = f"""
            Analyze the text below to identify the study groups.
            
            RAW DATA:
            {raw_data_block}

            Task:
            1. List all group names found in headers.
            2. Identify the Placebo/Control group (e.g., "Placebo", "PLA", "Control", "Sham").
            3. **CRITICAL:** Do NOT select aggregate columns like "Total", "Overall", or "All Patients" as the Placebo.
            4. Identify the Active Treatment groups.

            Respond in VALID JSON:
            {{
                "placebo_name": "Exact string found in text for placebo. If none, return 'None'",
                "treatment_names": ["Exact string for Treatment A", "Exact string for Treatment B"]
            }}
            """
            
            # Run Classifier
            result = llm.invoke(classification_prompt)
            cleaned = clean_json_output(result.content)
            classification = json.loads(cleaned)
            
            placebo_name = classification.get("placebo_name", "None")
            treatment_names = classification.get("treatment_names", [])

            # --- Pass 2: The Extractor (Get Values) ---
            extraction_prompt = f"""
            Extract data for "{outcome_name}" based on the identified groups.

            RAW DATA:
            {raw_data_block}

            Groups: Placebo="{placebo_name}", Treatments={treatment_names}

            INSTRUCTIONS:
            1. **Placebo Data:** Extract values (mean, SD, n, %) for "{placebo_name}".
            2. **Treatment Arms:** Extract values for {treatment_names}. Format: "Group: Value".
            3. **Durations:** List timepoints.
            
            **NEGATIVE CONSTRAINTS:**
            - IGNORE rows for Age, Sex, Weight, or BMI unless they match "{outcome_name}".
            - Extract ONLY data specific to the outcome "{outcome_name}".

            RESPONSE FORMAT (JSON):
            {{
                "placebo_data": "String describing values for {placebo_name}",
                "treatment_arms": "String listing values for {treatment_names}",
                "durations": "String listing timepoints"
            }}
            """
            # extraction_prompt = f"""
            # You are a medical data analyst. Extract data for "{outcome_name}" based on the identified groups.

            # RAW DATA:
            # {raw_data_block}

            # Group Definitions:
            # - Placebo/Control Group Identifier: "{placebo_name}"
            # - Treatment Group Identifiers: {treatment_names}

            # INSTRUCTIONS:
            # 1. **Focus Strictly on the Outcome:** Look for the specific row or sentence that reports results for "{outcome_name}".
            # 2. **Placebo Data:** Extract the value (mean, SD, n, %, CI) for the "{placebo_name}" group.
            # 3. **Treatment Arms:** Extract values for the {treatment_names} groups. Format: "Group Name: Value".
            # 4. **Durations:** List timepoints.

            # CRITICAL NEGATIVE CONSTRAINTS:
            # - **DO NOT** extract demographic data (Age, Sex, Weight, Height) unless "{outcome_name}" IS a demographic metric.
            # - **DO NOT** extract values from rows that are not "{outcome_name}".
            # - If the data is in a table, find the intersection of the Group Column and the Outcome Row.

            # RESPONSE FORMAT (JSON):
            # {{
            #     "placebo_data": "String describing values for {placebo_name}",
            #     "treatment_arms": "String listing values for {treatment_names}",
            #     "durations": "String listing timepoints"
            # }}
            # """           
            # extraction_prompt = f"""
            # You are a medical data analyst. Extract data for "{outcome_name}" based on the identified groups.

            # RAW DATA:
            # {raw_data_block}

            # Group Definitions:
            # - Placebo/Control Group Identifier: "{placebo_name}"
            # - Treatment Group Identifiers: {treatment_names}

            # INSTRUCTIONS:
            # 1. **Placebo Data:** Extract values (mean, SD, n, %) specifically for the group identified as "{placebo_name}".
            # 2. **Treatment Arms:** Extract values specifically for the groups identified as {treatment_names}. Format as "Group Name: Value".
            # 3. **Durations:** List all follow-up timepoints mentioned.

            # RESPONSE FORMAT (JSON):
            # {{
            #     "placebo_data": "String describing values for {placebo_name}",
            #     "treatment_arms": "String listing values for {treatment_names}",
            #     "durations": "String listing timepoints"
            # }}
            # """

            result = llm.invoke(extraction_prompt)
            cleaned_content = clean_json_output(result.content)
            current_analysis = json.loads(cleaned_content)
            
            # --- QUALITY CHECK ---
            # If we found actual Placebo data (not "No Placebo" or "N/A"), this is a good result.
            # We trust it and return immediately.
            p_data = current_analysis.get("placebo_data", "").lower()
            if "no placebo" not in p_data and "n/a" not in p_data and "none" not in p_data:
                return current_analysis
            
            # If we didn't find placebo data, save this result as a backup but try again
            best_result = current_analysis

        except Exception:
            continue # If an error occurs, just try the next attempt

    # If we tried 3 times and never got a "perfect" result, return the last valid one we found
    return best_result
# In query_handler.py

# --- NEW HELPER FUNCTION ---
def process_single_ct_gov_doc(nct_id, outcome_of_interest):
    """
    Runs the full 3-step API workflow for a single CT.gov ID.
    Returns: (placebo_str, treatment_str, table_names_str)
    """
    from data_ingestor import get_ct_gov_table_titles_from_api, extract_data_for_selected_titles
    
    # 1. List Titles
    all_titles, _ = get_ct_gov_table_titles_from_api(nct_id)
    
    if not all_titles:
        return "N/A", "N/A", "No data tables found"

    # 2. Locate Relevant (LLM Step - this is why Refresh is useful!)
    relevant_titles, _ = find_relevant_table_titles(all_titles, outcome_of_interest)
    
    if not relevant_titles:
        return "N/A", "N/A", "No relevant tables found"

    # 3. Extract Data
    extracted_data, _ = extract_data_for_selected_titles(nct_id, relevant_titles)
    
    if not extracted_data:
        return "N/A", "N/A", "Extraction failed"

    # 4. Parse into Columns
    placebo_list = []
    treatment_list = []
    table_names = list(extracted_data.keys())
    
    for title, val_str in extracted_data.items():
        groups = val_str.split(" | ")
        for group_str in groups:
            if ":" in group_str:
                group_name, val = group_str.split(":", 1)
                if any(k in group_name.lower() for k in ['placebo', 'control', 'sham', 'vehicle']):
                    placebo_list.append(f"{group_name.strip()}: {val.strip()}")
                else:
                    treatment_list.append(f"{group_name.strip()}: {val.strip()}")

    placebo_cell = " || ".join(placebo_list) if placebo_list else "N/A"
    treatment_cell = " || ".join(treatment_list) if treatment_list else "N/A"
    table_name_cell = " || ".join(table_names)

    return placebo_cell, treatment_cell, table_name_cell
# --- END NEW HELPER ---

# --- UPDATED CONTROLLER ---
def generate_ct_gov_table(outcome_of_interest):
    """
    Generates the table for ClinicalTrials.gov links.
    """
    vector_store = st.session_state.get('vector_store', None)
    if not vector_store: return None, "Vector Store not found."

    all_docs_metadata = vector_store.get(include=["metadatas"])
    ct_sources = sorted(list(set(
        meta['source'] for meta in all_docs_metadata['metadatas'] 
        if "clinicaltrials.gov" in meta['source']
    )))
    
    if not ct_sources: return None, "No ClinicalTrials.gov documents found."

    table_data = []
    progress_bar = st.progress(0, text="Generating CT.gov table...")

    for i, source_url in enumerate(ct_sources):
        progress_bar.progress((i + 1) / len(ct_sources), text=f"Processing API: {source_url}")
        
        import re
        nct_match = re.search(r'NCT\d+', source_url)
        if nct_match:
            nct_id = nct_match.group(0)
            # Call the helper
            p_val, t_val, tab_name = process_single_ct_gov_doc(nct_id, outcome_of_interest)
            
            table_data.append({
                "Link": source_url,
                "Table Name": tab_name, # New Column
                "Placebo/Control Value": p_val,
                "Treatment Value": t_val
            })
        else:
            table_data.append({
                "Link": source_url,
                "Table Name": "Error",
                "Placebo/Control Value": "Invalid URL",
                "Treatment Value": "Invalid URL"
            })

    progress_bar.empty()
    if not table_data: return None, "No data extracted."
    
    return pd.DataFrame(table_data), "CT.gov Table Generated."
