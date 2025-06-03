import streamlit as st
import requests
import xmltodict
import json

# --- Configuration ---
try:
    NCBI_API_KEY = st.secrets.get("NCBI_API_KEY")
    if not NCBI_API_KEY: NCBI_API_KEY = None
except Exception: NCBI_API_KEY = None

try:
    EMAIL_FOR_NCBI = st.secrets.get("EMAIL_FOR_NCBI", "your_default_email@example.com")
except Exception: EMAIL_FOR_NCBI = "your_default_email@example.com"


# --- Helper Function for ClinicalTrials.gov Query ---
def construct_clinicaltrials_api_query(disease, outcome, population, study_type_selection):
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


# --- Functions for Fetching Results from APIs ---
def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=200):
    search_stages_keywords = []
    if disease and disease.strip(): search_stages_keywords.append(disease.strip())
    if outcome and outcome.strip(): search_stages_keywords.append(outcome.strip())
    if population and population.strip(): search_stages_keywords.append(population.strip())

    if not search_stages_keywords:
        return [], "No search terms provided for PubMed."

    study_type_query_segment = ""
    if study_type_selection == "Clinical Trials":
        study_type_query_segment = '("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type])'
    elif study_type_selection == "Observational Studies":
        study_type_query_segment = '("observational study"[Publication Type] OR "cohort study"[All Fields] OR "case-control study"[All Fields])'

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    current_webenv = None
    current_query_key = None
    final_id_list = []
    processed_query_description_parts = []

    for i, keyword_stage_term in enumerate(search_stages_keywords):
        current_stage_search_query = ""
        if study_type_query_segment:
            current_stage_search_query = f"{keyword_stage_term} AND ({study_type_query_segment})"
        else:
            current_stage_search_query = keyword_stage_term
        
        description_keyword_display = keyword_stage_term
        processed_query_description_parts.append(f"Term: '{description_keyword_display}'")
        if i == 0 and study_type_query_segment:
             processed_query_description_parts.append(f"Study Filter: {study_type_selection}")

        esearch_params = {
            "db": "pubmed",
            "retmax": str(max_results * 5 if i < len(search_stages_keywords) - 1 else max_results),
            "usehistory": "y", "retmode": "json",
            "tool": "streamlit_app_pubmed_finder", "email": EMAIL_FOR_NCBI
        }
        if NCBI_API_KEY: esearch_params["api_key"] = NCBI_API_KEY

        if current_webenv and current_query_key:
            esearch_params["term"] = f"#{current_query_key} AND {current_stage_search_query}"
            esearch_params["WebEnv"] = current_webenv
        else:
            esearch_params["term"] = current_stage_search_query
        
        try:
            response = requests.get(f"{base_url}esearch.fcgi", params=esearch_params, timeout=20)
            response.raise_for_status()
            esearch_data = response.json()
            stage_id_list = esearch_data.get("esearchresult", {}).get("idlist", [])
            if not stage_id_list:
                return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (No results at this step)"
            final_id_list = stage_id_list
            current_webenv = esearch_data.get("esearchresult", {}).get("webenv")
            current_query_key = esearch_data.get("esearchresult", {}).get("querykey")
            if not current_webenv or not current_query_key:
                return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (Error retrieving history)"
        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP error ({http_err.response.status_code if http_err.response else 'N/A'}) at PubMed stage {i+1}"
            if hasattr(http_err, 'response') and http_err.response is not None and http_err.response.status_code == 429: 
                error_message += " (Too Many Requests)"
            return [], f"PubMed: {' -> '.join(processed_query_description_parts)} -> {error_message}"
        except Exception as e:
            return [], f"PubMed: {' -> '.join(processed_query_description_parts)} -> Error at stage {i+1}: {str(e)}"


    if not final_id_list:
        return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (No results after all stages)"

    final_id_list_for_efetch = final_id_list[:max_results]
    
    efetch_params = {
        "db": "pubmed", "retmode": "xml", "rettype": "abstract",
        "id": ",".join(final_id_list_for_efetch),
        "tool": "streamlit_app_pubmed_finder", "email": EMAIL_FOR_NCBI
    }
    if NCBI_API_KEY: efetch_params["api_key"] = NCBI_API_KEY

    pubmed_results_list = []
    try:
        summary_response = requests.get(f"{base_url}efetch.fcgi", params=efetch_params, timeout=25)
        summary_response.raise_for_status()
        articles_dict = xmltodict.parse(summary_response.content)
        pubmed_articles_container = articles_dict.get("PubmedArticleSet", {})
        if not pubmed_articles_container:
             return [], f"PubMed Fetch Details: {' -> '.join(processed_query_description_parts)} (No PubmedArticleSet)"
        articles_list_xml = pubmed_articles_container.get("PubmedArticle", [])
        if not isinstance(articles_list_xml, list): articles_list_xml = [articles_list_xml] if articles_list_xml else []
        if not articles_list_xml:
            return [], f"PubMed Fetch Details: {' -> '.join(processed_query_description_parts)} (No article details)"

        for article_data in articles_list_xml:
            if not isinstance(article_data, dict): continue
            medline_citation = article_data.get("MedlineCitation", {})
            if not medline_citation: continue 
            article_info = medline_citation.get("Article", {})
            if not article_info: continue
            pmid_obj = medline_citation.get("PMID", {})
            pmid = pmid_obj.get("#text", "N/A") if isinstance(pmid_obj, dict) else pmid_obj if isinstance(pmid_obj, str) else "N/A"
            title_obj = article_info.get("ArticleTitle", "No title available")
            if isinstance(title_obj, dict): title = title_obj.get("#text", "No title available")
            elif isinstance(title_obj, list): title = "".join(str(t.get("#text", t)) if isinstance(t, dict) else str(t) for t in title_obj)
            else: title = str(title_obj)

            pubmed_link_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid != "N/A" else "#"
            pmc_link_url = None
            is_rag_candidate = False
            
            pubmed_data = article_data.get("PubmedData", {})
            if pubmed_data:
                article_id_list_xml = pubmed_data.get("ArticleIdList", {}).get("ArticleId", [])
                if not isinstance(article_id_list_xml, list): article_id_list_xml = [article_id_list_xml]
                for aid in article_id_list_xml:
                    if isinstance(aid, dict) and aid.get("@IdType") == "pmc":
                        pmcid = aid.get("#text")
                        if pmcid: 
                            pmc_link_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
                            is_rag_candidate = True
                            break
            
            pubmed_results_list.append({
                "title": title, 
                "link": pmc_link_url if is_rag_candidate else pubmed_link_url,
                "is_rag_candidate": is_rag_candidate,
                "source_type": "PubMed Central Article" if is_rag_candidate else "PubMed Abstract"
            })
        return pubmed_results_list, f"PubMed: {' -> '.join(processed_query_description_parts)} (Fetched {len(pubmed_results_list)} details)"
    except Exception as e:
        return [], f"PubMed Fetch Details Error: {' -> '.join(processed_query_description_parts)} -> {str(e)}"


def fetch_clinicaltrials_results(query, max_results=200): # query is the string from construct_clinicaltrials_api_query
    if not query: 
        st.warning("ClinicalTrials.gov query string is empty.") # Added warning
        return []

    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    # Define statuses that mean "no longer looking for participants"
    # You can adjust this list based on your exact needs.
    # 'COMPLETED' is the primary one you mentioned.
    no_longer_recruiting_statuses = [
        "COMPLETED", 
        #"TERMINATED", 
        #"WITHDRAWN", 
        #"ACTIVE_NOT_RECRUITING",
        #"SUSPENDED" # Optional: if suspended means not looking *now*
    ]

    params = {
        "query.term": query,  # Your existing keywords (disease, outcome, population, study_type)
        "query.overallStatus": ",".join(no_longer_recruiting_statuses), # Filter by these statuses
        "pageSize": str(max_results),
        "format": "json"
    }

    # For debugging, let's see the exact params being sent
    st.info(f"ClinicalTrials.gov API Request Params: {json.dumps(params, indent=2)}")

    ct_results_list = []
    try:
        response = requests.get(base_url, params=params, timeout=20) # Increased timeout
        st.info(f"ClinicalTrials.gov API Request URL: {response.url}") # Log the exact URL
        response.raise_for_status()
        data = response.json()
        studies = data.get("studies", [])
        
        st.info(f"ClinicalTrials.gov API returned {len(studies)} studies.") # Debug how many are returned by API

        if not studies: 
            return []

        for study_container in studies:
            # No need for post-fetch status filter if API handles it, but good to have for display
            protocol_section = study_container.get("protocolSection", {})
            if not protocol_section: continue # Should not happen with valid API response

            identification_module = protocol_section.get("identificationModule", {})
            status_module = protocol_section.get("statusModule", {}) # For displaying status if needed
            
            nct_id = identification_module.get("nctId", "N/A")
            title = identification_module.get("officialTitle") or identification_module.get("briefTitle", "No title available")
            # overall_status_from_api = status_module.get("overallStatus", "N/A") # For display
            link_url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            # Your requirement is to only include these, which the API filter should handle.
            # We can add an explicit check for the `resultsSection` if that's still desired for RAG.
            if not study_container.get("resultsSection"): # If you only want trials with results posted
                 st.write(f"Skipping {nct_id} - no results section.") # Debug
                 continue

            ct_results_list.append({
                "title": title, 
                "link": link_url,
                "nct_id": nct_id,
                "is_rag_candidate": True, # HTML record is RAG-readable
                "source_type": "Clinical Trial Record" # Can add status_from_api if needed
            })
            if len(ct_results_list) >= max_results: # Ensure we don't exceed max_results
                break

    except requests.exceptions.HTTPError as http_err:
        error_detail = f" (URL: {http_err.request.url if http_err.request else 'N/A'})"
        if http_err.response is not None:
             error_detail += f" - Response Code: {http_err.response.status_code} - Detail: {http_err.response.text[:1000]}"
        else:
            error_detail += " - No response object."
        st.error(f"ClinicalTrials.gov API Error: HTTP Error {error_detail}")
        return []
    except Exception as e:
        st.error(f"ClinicalTrials.gov API Error (Other): {str(e)}")
        return []
    
    st.info(f"Returning {len(ct_results_list)} Clinical Trial results after all processing.") # Debug
    return ct_results_list

# --- List of Other Databases --- CORRECTED SECTION
OTHER_DATABASES = [
    {"name": "Europe PMC", "url": "https://europepmc.org/"},
    {"name": "Lens.org", "url": "https://www.lens.org/"},
    {"name": "Directory of Open Access Journals (DOAJ)", "url": "https://doaj.org/"},
    {"name": "Google Scholar", "url": "https://scholar.google.com/"},
    {"name": "medRxiv (Preprint Server)", "url": "https://www.medrxiv.org/"},
    {"name": "bioRxiv (Preprint Server)", "url": "https://www.biorxiv.org/"}
]

# --- Streamlit App UI ---
st.set_page_config(layout="wide")
st.title("RAG-Ready Medical Research Finder")
st.markdown("Finds **PubMed Central articles** and **Clinical Trial records** suitable for RAG pipelines.")

st.sidebar.header("Search Parameters")
target_population = st.sidebar.text_input("Target Population", placeholder="e.g., elderly patients with diabetes")
disease = st.sidebar.text_input("Disease/Condition", placeholder="e.g., Type 2 Diabetes")
outcome_of_interest = st.sidebar.text_input("Outcome of Interest", placeholder="e.g., blood glucose control")
study_type = st.sidebar.selectbox(
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 150, 10)

if NCBI_API_KEY: st.sidebar.success("NCBI API Key loaded.")
else: st.sidebar.warning("NCBI API Key not loaded. Consider adding to secrets.")
if EMAIL_FOR_NCBI == "your_default_email@example.com" or not EMAIL_FOR_NCBI:
     st.sidebar.error("NCBI Email not set in secrets. Update .streamlit/secrets.toml")

if st.sidebar.button("Search"):
    if not (disease or outcome_of_interest or target_population):
        st.error("Please fill in at least one of: Disease, Outcome, or Population.")
    else:
        st.header("PubMed / PubMed Central Results")
        pubmed_status_message = st.empty()
        with st.spinner(f"Performing sequential PubMed search..."):
            pubmed_status_message.info("Initializing PubMed search...")
            pubmed_results, pubmed_query_description = fetch_pubmed_results(
                disease, outcome_of_interest, target_population, study_type, max_results_per_source
            )
        pubmed_status_message.info(f"PubMed Strategy: {pubmed_query_description}")
            
        if pubmed_results:
            st.write(f"Found {len(pubmed_results)} PubMed/PMC items:")
            for res in pubmed_results:
                if res.get("is_rag_candidate"):
                    st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']}* (Likely RAG-readable)")
                else:
                    st.markdown(f"⚠️ [{res['title']}]({res['link']})** - *{res['source_type']}* (Access for RAG needs verification)")
                st.divider()
        else:
            st.write("No results from PubMed based on the criteria or an error occurred during search.")
        st.markdown("---")

        st.header("ClinicalTrials.gov Results")
        ct_status_message = st.empty()
        ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, study_type)
        
        if ct_api_query_string:
            ct_status_message.info(f"Searching ClinicalTrials.gov with terms: {ct_api_query_string}")
            with st.spinner(f"Searching ClinicalTrials.gov..."):
                ct_results = fetch_clinicaltrials_results(ct_api_query_string, max_results_per_source)
            
            if ct_results:
                st.write(f"Found {len(ct_results)} Clinical Trial records:")
                for res in ct_results:
                    st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']} (NCT: {res['nct_id']})* (RAG-readable HTML record)")
                    st.divider()
            else:
                ct_status_message.info(f"No results from ClinicalTrials.gov for terms: {ct_api_query_string}")
        else: 
            ct_status_message.warning("Could not construct a ClinicalTrials.gov query from inputs.")
        st.markdown("---")
        st.success("Search complete.")
else:
    st.info("Enter search parameters in the sidebar and click 'Search'.")

st.sidebar.markdown("---")
st.sidebar.header("Other Free Medical Research Databases")
# This ensures the loop iterates over the correctly defined list
for db in OTHER_DATABASES: 
    st.sidebar.markdown(f"[{db['name']}]({db['url']})")
st.sidebar.markdown("---")
st.sidebar.caption(f"Respect API terms of service.")
