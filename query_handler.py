# query_handler.py

import streamlit as st
import json
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA
from vector_store_manager import load_vector_store

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
