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
            model_name="meta-llama/llama-3-8b-instruct",
            openai_api_key=st.secrets.get("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.0, # Crucial for factual, non-creative extraction
            max_tokens=1024,
            model_kwargs={
                "response_format": {"type": "json_object"} # Instruct the model to output JSON
            }
        )
        return llm
    except Exception as e:
        st.error(f"Failed to initialize LLM via OpenRouter: {e}")
        return None

def discover_metrics_in_doc(source_url):
    """
    Performs a RAG query on a single document to find all quantifiable metrics.
    """
    vector_store = st.session_state.get('vector_store', None)
    if not vector_store:
        return None, "Vector Store not found in session. Please process and add documents first."

    llm = get_llm()
    if not llm:
        return None, "LLM not initialized. Check API keys."

    # Create a retriever filtered to search ONLY within the specified document
    retriever = vector_store.as_retriever(
        search_kwargs={'k': 15, 'filter': {'source': source_url}}
    )

    # The chain that combines the retriever and LLM
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
    )

    # This prompt asks the LLM to act as a scanner
    discovery_prompt = """
    Based ONLY on the provided context from this single research paper, identify and list every single quantifiable statistical metric or outcome measure that is reported with a numerical value.
    Do not include metrics that are only mentioned without an associated result.
    Respond in a valid JSON format with a single key 'metrics', which is a list of strings. Each string should be a concise name for the metric, including units if appropriate.
    Example Response: {"metrics": ["Sample Size (participants)", "Mean Age (years)", "Baseline BMI (kg/m^2)", "Change in Body Weight (kg)", "Adverse Event Rate (%)"]}
    """

    try:
        result = qa_chain.invoke({"query": discovery_prompt})
        # The LLM's raw output should be a JSON string
        answer_json = json.loads(result['result'])
        metrics_list = answer_json.get('metrics', [])
        return metrics_list, "Discovery successful."
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        st.error(f"Failed to parse LLM response during discovery: {e}")
        st.write("LLM Raw Output:", result.get('result', 'No result found.'))
        return None, "Failed to parse LLM response."
    except Exception as e:
        return None, f"An error occurred during discovery: {e}"

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
