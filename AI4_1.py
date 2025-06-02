import streamlit as st
import requests
import xmltodict
import json
import shlex # Not strictly needed for the simplified query, but good to have if you revert

# --- Configuration ---
# Attempt to get NCBI_API_KEY from Streamlit secrets
try:
    NCBI_API_KEY = st.secrets.get("NCBI_API_KEY")
    if not NCBI_API_KEY: # Handles if key exists but is empty
        NCBI_API_KEY = None
        st.sidebar.warning("NCBI_API_KEY not found or empty in Streamlit secrets. Using default rate limits.")
except Exception: # Handles if st.secrets itself or the key doesn't exist (e.g. local run without secrets file)
    NCBI_API_KEY = None
    st.sidebar.warning("Streamlit secrets not found or NCBI_API_KEY missing. Using default rate limits.")

# Get email from secrets or use a default/placeholder
try:
    EMAIL_FOR_NCBI = st.secrets.get("EMAIL_FOR_NCBI", "your_default_email@example.com") # Provide a default
    if not EMAIL_FOR_NCBI or EMAIL_FOR_NCBI == "your_default_email@example.com":
        st.sidebar.error("IMPORTANT: Please set your EMAIL_FOR_NCBI in Streamlit secrets for NCBI API usage.")
except Exception:
    EMAIL_FOR_NCBI = "your_default_email@example.com" # Fallback
    st.sidebar.error("IMPORTANT: Please set your EMAIL_FOR_NCBI in Streamlit secrets for NCBI API usage.")

# --- Helper Functions for Query Construction ---
def construct_pubmed_query(disease, outcome, population, study_type_selection):
    """
    Constructs a very simple PubMed query string, by space-separating all terms.
    Multi-word phrases from input are quoted. Study type keywords are added.
    This mimics a more natural PubMed search bar query.
    """
    query_terms = []

    def add_term_to_query(term_str):
        if not term_str or not term_str.strip():
            return
        term_str = term_str.strip()
        # If the term contains spaces, quote it to treat as a phrase
        if ' ' in term_str:
            query_terms.append(f'"{term_str}"')
        else:
            query_terms.append(term_str)

    add_term_to_query(disease)
    add_term_to_query(outcome)
    add_term_to_query(population)
    
    if study_type_selection == "Clinical Trials":
        query_terms.append('"clinical trial"') # PubMed recognizes this phrase
        query_terms.append('"randomized controlled trial"') # Also common
        # query_terms.append('trial') # Could add simpler 'trial' if needed
    elif study_type_selection == "Observational Studies":
        query_terms.append('"observational study"')
        query_terms.append('"cohort study"')
        query_terms.append('"case-control study"')
    # If "All Study Types (PubMed only)", no specific study type keyword is added here.

    if not query_terms:
        return None 

    return " ".join(query_terms)


def construct_clinicaltrials_api_query(disease, outcome, population, study_type_selection):
    # This function remains the same as it was working well.
    terms = []
    if disease: terms.append(disease.strip())
    if outcome: terms.append(outcome.strip())
    if population: terms.append(population.strip())

    study_type_term = ""
    if study_type_selection == "Clinical Trials": study_type_term = "Interventional"
    elif study_type_selection == "Observational Studies": study_type_term = "Observational"
    
    if study_type_term: terms.append(study_type_term)
        
    valid_terms = [term for term in terms if term]
    if not valid_terms: return None
    return " ".join(valid_terms)


# --- Functions for Fetching Results from APIs (fetch_pubmed_results and fetch_clinicaltrials_results) ---
# These functions (fetch_pubmed_results, fetch_clinicaltrials_results)
# remain IDENTICAL to the previous version.
# The change is only in how the pubmed_query_string is *created*.
# For brevity, I will not repeat them here but assume you have them from the previous response.

def fetch_pubmed_results(query, max_results=10):
    if not query:
        st.warning("PubMed query is empty. Please provide search terms.")
        return []
        
    st.info(f"Searching PubMed with query: {query}")
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    esearch_params = {
        "db": "pubmed", "term": query, "retmax": str(max_results),
        "usehistory": "y", "retmode": "json",
        "tool": "streamlit_app_pubmed_finder", "email": EMAIL_FOR_NCBI
    }
    if NCBI_API_KEY: esearch_params["api_key"] = NCBI_API_KEY

    pubmed_results = []
    try:
        response = requests.get(f"{base_url}esearch.fcgi", params=esearch_params, timeout=15)
        response.raise_for_status() # Will raise an HTTPError for bad responses (4XX or 5XX)
        esearch_data = response.json()
        
        id_list = esearch_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            st.warning("No PMIDs found for the PubMed query. Try broadening your search terms or checking the query on PubMed's website.")
            return []

        efetch_params = {
            "db": "pubmed", "retmode": "xml", "rettype": "abstract",
            "id": ",".join(id_list),
            "tool": "streamlit_app_pubmed_finder", "email": EMAIL_FOR_NCBI
        }
        if NCBI_API_KEY: efetch_params["api_key"] = NCBI_API_KEY

        summary_response = requests.get(f"{base_url}efetch.fcgi", params=efetch_params, timeout=20)
        summary_response.raise_for_status()
        
        articles_dict = xmltodict.parse(summary_response.content)
        
        pubmed_articles_container = articles_dict.get("PubmedArticleSet", {})
        if not pubmed_articles_container:
             st.warning("PubMed response structure unexpected (No PubmedArticleSet).")
             return []

        articles_list = pubmed_articles_container.get("PubmedArticle", [])
        if not isinstance(articles_list, list): # If only one article, it's a dict, not list
            articles_list = [articles_list] if articles_list else []

        if not articles_list: # Should not happen if id_list was populated, but good check
            st.warning("No article details found in PubMed response, though PMIDs were retrieved.")
            return []

        for article_data in articles_list:
            if not isinstance(article_data, dict): continue
            medline_citation = article_data.get("MedlineCitation", {})
            if not medline_citation: continue 
            article_info = medline_citation.get("Article", {})
            if not article_info: continue

            pmid_obj = medline_citation.get("PMID", {})
            pmid = pmid_obj.get("#text", "N/A") if isinstance(pmid_obj, dict) else pmid_obj if isinstance(pmid_obj, str) else "N/A"
            
            title_obj = article_info.get("ArticleTitle", "No title available")
            if isinstance(title_obj, dict): 
                title = title_obj.get("#text", "No title available")
            elif isinstance(title_obj, list): # Handle cases where ArticleTitle might be a list of segments
                title = "".join(str(t.get("#text", t)) if isinstance(t, dict) else str(t) for t in title_obj)
            else: # String or other
                title = str(title_obj)


            abstract_text_parts = []
            abstract_section = article_info.get("Abstract", {})
            if abstract_section:
                abstract_texts = abstract_section.get("AbstractText")
                if abstract_texts:
                    if isinstance(abstract_texts, list):
                        for part in abstract_texts:
                            if isinstance(part, dict) and '#text' in part: abstract_text_parts.append(part['#text'])
                            elif isinstance(part, str): abstract_text_parts.append(part)
                    elif isinstance(abstract_texts, dict) and '#text' in abstract_texts:
                        abstract_text_parts.append(abstract_texts['#text'])
                    elif isinstance(abstract_texts, str):
                        abstract_text_parts.append(abstract_texts)
            
            snippet = (" ".join(abstract_text_parts)[:300] + "...") if abstract_text_parts else "No abstract available."
            pubmed_link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid != "N/A" else "#"
            pmc_link = None
            
            pubmed_data = article_data.get("PubmedData", {})
            if pubmed_data:
                article_id_list = pubmed_data.get("ArticleIdList", {}).get("ArticleId", [])
                if not isinstance(article_id_list, list): article_id_list = [article_id_list]
                
                for aid in article_id_list:
                    if isinstance(aid, dict) and aid.get("@IdType") == "pmc":
                        pmcid = aid.get("#text")
                        if pmcid:
                            pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
                            break
            
            access_type = "Open Access (via PMC)" if pmc_link else "Check PubMed Link for Access"
            result_item = {
                "title": title, "link": pmc_link if pmc_link else pubmed_link,
                "pubmed_url": pubmed_link, "snippet": snippet, "access": access_type,
                "source": "PubMed Central" if pmc_link else "PubMed"
            }
            if pmc_link: result_item["pmc_link"] = pmc_link
            pubmed_results.append(result_item)

    except requests.exceptions.HTTPError as http_err: # Specifically catch HTTP errors
        st.error(f"HTTP error occurred while fetching from PubMed: {http_err} - URL: {http_err.request.url}")
        if http_err.response.status_code == 429:
            st.error("This is a 'Too Many Requests' error. Please wait a few minutes and try again, or use an NCBI API key.")
        # You could inspect http_err.response.text for more details from NCBI
    except requests.exceptions.Timeout:
        st.error("PubMed request timed out. The server might be busy or your connection unstable.")
    except requests.exceptions.RequestException as e: # Other network errors
        st.error(f"Error fetching from PubMed: {e}")
    except json.JSONDecodeError as e: # For esearch if response is not valid JSON
        st.error(f"Error decoding PubMed JSON response: {e}")
    except Exception as e: # Catch-all for other errors, like xmltodict parsing
        st.error(f"An unexpected error occurred with PubMed processing: {e}")
        # st.error(f"Problematic XML content snippet: {summary_response.text[:500] if 'summary_response' in locals() and hasattr(summary_response, 'text') else 'N/A'}")

    return pubmed_results

def fetch_clinicaltrials_results(query, max_results=10):
    if not query:
        st.warning("ClinicalTrials.gov query is empty. Please provide search terms.")
        return []

    st.info(f"Searching ClinicalTrials.gov with query: {query}")
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    params = { "query.term": query, "pageSize": str(max_results), "format": "json" }
    ct_results = []
    try:
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        studies = data.get("studies", [])
        if not studies:
            st.warning("No clinical trials found for the query. Try broadening your search terms.")
            return []

        for study_container in studies:
            study = study_container.get("protocolSection", {})
            if not study: continue

            identification_module = study.get("identificationModule", {})
            status_module = study.get("statusModule", {})
            description_module = study.get("descriptionModule", {})
            
            nct_id = identification_module.get("nctId", "N/A")
            title = identification_module.get("officialTitle") or identification_module.get("briefTitle", "No title available")

            status = status_module.get("overallStatus", "N/A")
            summary = description_module.get("briefSummary", "")
            if not summary and description_module.get("detailedDescription"):
                summary = description_module.get("detailedDescription")[:300] + "..."
            if not summary: summary = "No summary available."

            link = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            ct_results.append({
                "title": title, "link": link, "nct_id": nct_id,
                "status": status, "summary": summary, "source": "ClinicalTrials.gov"
            })
            
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error occurred while fetching from ClinicalTrials.gov: {http_err}")
    except requests.exceptions.Timeout:
        st.error("ClinicalTrials.gov request timed out.")
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching from ClinicalTrials.gov: {e}")
    except json.JSONDecodeError as e:
        st.error(f"Error decoding ClinicalTrials.gov JSON response: {e}")
    except Exception as e:
        st.error(f"An unexpected error occurred with ClinicalTrials.gov: {e}")
    return ct_results

# --- List of Other Databases (Same as before) ---
OTHER_DATABASES = [
    {"name": "Europe PMC", "url": "https://europepmc.org/"},
    {"name": "Lens.org", "url": "https://www.lens.org/"},
    {"name": "Directory of Open Access Journals (DOAJ)", "url": "https://doaj.org/"},
    {"name": "Google Scholar", "url": "https://scholar.google.com/"},
    {"name": "medRxiv (Preprint Server)", "url": "https://www.medrxiv.org/"},
    {"name": "bioRxiv (Preprint Server)", "url": "https://www.biorxiv.org/"}
]

# --- Streamlit App UI (This also remains IDENTICAL to the previous version) ---
st.set_page_config(layout="wide")
st.title("Medical Research Paper & Trial Finder")
st.markdown("""
This app searches PubMed and ClinicalTrials.gov.
It prioritizes links to PubMed Central (PMC) for articles, as these are generally open access.
**Note:** This tool *finds potential sources*. The next step for a RAG pipeline would be to download and process the content from these links.
""")

st.sidebar.header("Search Parameters")
target_population = st.sidebar.text_input("Target Population", placeholder="e.g., elderly patients with diabetes")
disease = st.sidebar.text_input("Disease/Condition", placeholder="e.g., Type 2 Diabetes")
outcome_of_interest = st.sidebar.text_input("Outcome of Interest", placeholder="e.g., blood glucose control")
study_type = st.sidebar.selectbox(
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 25, 10)


if st.sidebar.button("Search"):
    if not (disease or outcome_of_interest or target_population):
        st.error("Please fill in at least one of: Disease, Outcome, or Population.")
    else:
        # --- PubMed Search ---
        st.header("PubMed / PubMed Central Results")
        pubmed_query_string = construct_pubmed_query(disease, outcome_of_interest, target_population, study_type)
        
        if pubmed_query_string:
            st.write("**PubMed Query (Simplified for broad search):**")
            st.code(pubmed_query_string, language="text")
            with st.spinner(f"Searching PubMed for up to {max_results_per_source} results..."):
                pubmed_results = fetch_pubmed_results(pubmed_query_string, max_results_per_source)
            
            if pubmed_results:
                st.write(f"Found {len(pubmed_results)} results from PubMed/PMC:")
                for res in pubmed_results:
                    col1, col2 = st.columns([3,1])
                    with col1:
                        st.markdown(f"**[{res['title']}]({res['link']})**")
                        st.caption(f"Source: {res['source']}")
                        if res['source'] == "PubMed Central" and 'pubmed_url' in res and res['link'] != res['pubmed_url']:
                            st.caption(f"Original PubMed Abstract: [{res['pubmed_url']}]({res['pubmed_url']})")
                        st.write(f"_{res.get('snippet', 'No snippet available.')}_")
                    with col2:
                        st.markdown(f"**Access:**")
                        st.markdown(f"[{res['access']}]({res['link']})")
                    st.divider()
        else:
            st.warning("Could not construct a valid PubMed query from the inputs. Please provide at least one search term.")
        st.markdown("---")

        # --- ClinicalTrials.gov Search ---
        st.header("ClinicalTrials.gov Results")
        ct_study_type_for_query = study_type
        if study_type == "All Study Types (PubMed only)":
            ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, "")
        else:
            ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, study_type)

        if ct_api_query_string:
            st.write("**ClinicalTrials.gov API Query (Keywords):**")
            st.code(ct_api_query_string, language="text")
            with st.spinner(f"Searching ClinicalTrials.gov for up to {max_results_per_source} results..."):
                ct_results = fetch_clinicaltrials_results(ct_api_query_string, max_results_per_source)

            if ct_results:
                st.write(f"Found {len(ct_results)} results from ClinicalTrials.gov:")
                for res in ct_results:
                    st.markdown(f"**[{res['title']}]({res['link']})**")
                    st.caption(f"NCT ID: {res['nct_id']} | Status: {res['status']}")
                    st.write(f"_{res.get('summary', 'No summary available.')}_")
                    st.divider()
        else:
            st.warning("Could not construct a valid ClinicalTrials.gov query from the inputs. Please provide at least one search term.")
        
        st.markdown("---")
        st.success("Search complete. Review the links above. Prioritize PubMed Central (PMC) links for open access articles suitable for a RAG pipeline.")

else:
    st.info("Enter search parameters in the sidebar and click 'Search'.")

st.sidebar.markdown("---")
st.sidebar.header("Other Free Medical Research Databases")
for db in OTHER_DATABASES:
    st.sidebar.markdown(f"[{db['name']}]({db['url']})")

st.sidebar.markdown("---")
st.sidebar.caption(f"Remember to respect API terms of service. Provide your email for NCBI: {EMAIL_FOR_NCBI}")
