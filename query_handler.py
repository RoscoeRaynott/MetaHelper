# query_handler.py

import streamlit as st
import json
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA
import pandas as pd

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
            max_tokens=8192,
            model_kwargs={
                "response_format": {"type": "json_object"} # Instruct the model to output JSON
            }
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
