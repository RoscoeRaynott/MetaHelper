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
            model_name="meta-llama/llama-3-8b-instruct", # "microsoft/Phi-3-mini-128k-instruct",#"meta-llama/llama-3-8b-instruct",
            openai_api_key=st.secrets.get("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.0, # Crucial for factual, non-creative extraction
            max_tokens=100000,
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
        return "N/A (No relevant sections found)", "N/A", "Extraction complete."
        
    context_string_for_locator = "\n\n---\n\n".join([doc.page_content for doc in locator_context_chunks])

    locator_prompt = f"""
    Based ONLY on the context below, find the single, most relevant, full and exact name of the outcome measure related to "{user_outcome_of_interest}".
    ALSO find the full definition or expansion of any acronyms in that name.
    Context: {context_string_for_locator}
    Respond in JSON with two keys: "exact_metric_name" and "metric_definition".
    If the definition is not found, set "metric_definition" to "N/A".
    """
    
    exact_metric_name = user_outcome_of_interest
    metric_definition = "N/A"
    try:
        result = llm.invoke(locator_prompt)
        cleaned_content = clean_json_output(result.content)
        answer_json = json.loads(cleaned_content)
        if answer_json.get("exact_metric_name"): exact_metric_name = answer_json.get("exact_metric_name")
        metric_definition = answer_json.get("metric_definition", "N/A")
    except Exception:
        pass
    
    # --- Step 2: The "Scooper" Query (Modified) ---
    extractor_retriever = vector_store.as_retriever(
        search_kwargs={'k': 15, 'filter': { # Increased k to capture more context/table rows
            "$and": [
                {'source': source_url},
                {'section': {"$in": ["Results", "Conclusion", "Abstract"]}}
            ]
        }}
    )

    extractor_query = f"{user_outcome_of_interest}: {exact_metric_name}"
    context_chunks_for_extractor = extractor_retriever.invoke(extractor_query)
    
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

    Respond in JSON with a single key: "data_block".
    The value should be a single string containing all the extracted text and table rows combined.
    """

    try:
        result = llm.invoke(extractor_prompt)
        
        # Debug output to verify the "scoop"
        st.warning(f"🔍 DEBUG SCOOP for {source_url}:")
        st.text(result.content) 
        
        cleaned_content = clean_json_output(result.content)
        answer_json = json.loads(cleaned_content)
        data_block = answer_json.get('data_block', "")
        
        if not data_block:
            return "N/A (Value not found in text)", metric_definition, "Extraction complete."
            
        return data_block, metric_definition, "Extraction successful."
        
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        st.error(f"Failed to parse LLM response: {e}")
        return None, metric_definition, "Failed to parse LLM response."
    except Exception as e:
        return None, metric_definition, f"An error occurred during extraction: {e}"

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

        # --- NEW: Filter out ClinicalTrials.gov links ---
        if "clinicaltrials.gov" in source_url:
            continue
        # --- END NEW ---
        
        # --- NEW: Unpack 3 values instead of 2 ---
        findings, definition, status = extract_outcome_from_doc(source_url, outcome_of_interest)
        
        findings_str = " | ".join(findings) if findings else "N/A"
        
        table_data.append({
            "Source Document": source_url,
            "Metric Definition": definition, # <--- Add the new column here
            f"Outcome: {outcome_of_interest}": findings_str
        })

    

    progress_bar.empty()
    
    if not table_data:
        return None, "Could not extract data from any documents."

    df = pd.DataFrame(table_data)
    return df, unique_sources, "Table generation complete."

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
