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

# --- Helper function _construct_clinicaltrials_query_term_string is REMOVED ---

# --- Functions for Fetching Results from APIs ---
def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=10):
    # This function remains unchanged from your last working version for PubMed
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


def fetch_clinicaltrials_results(
    disease_input,    # For query.cond
    outcome_input,    # For query.outc
    population_input, # For query.term (the single free text)
    std_age_adv=None, # For query.patient.age
    location_country_adv=None, # For query.location.country
    gender_adv=None,  # For query.patient.gender
    study_type_from_sidebar=None, # For query.studyType
    # Post-fetch filters:
    masking_type_post_filter=None,
    intervention_model_post_filter=None,
    # General:
    max_results=10
):
    """
    Fetches results from ClinicalTrials.gov API v2 using specific query parameters
    for structured data and query.term for the single free-text population input.
    Filters for studies "no longer recruiting" and applies post-fetch filters.
    """

    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    params = {
        "format": "json",
        "pageSize": str(max_results * 2), # Fetch more for post-filtering
    }

    # 1. Add the single free-text input (population) to query.term
    if population_input and population_input.strip():
        params["query.term"] = population_input.strip() 
    # If population_input is empty, query.term will not be sent, 
    # and the search will rely solely on the other specific query.* parameters.

    # 2. Add specific query parameters for structured inputs
    if disease_input and disease_input.strip():
        params["query.cond"] = disease_input.strip() # Condition/Disease keywords

    if outcome_input and outcome_input.strip():
        params["query.outc"] = outcome_input.strip() # Outcome Measure keywords

    # Study Type (Interventional or Observational based on sidebar)
    # API expects: INTERVENTIONAL, OBSERVATIONAL, etc. (typically uppercase)
    if study_type_from_sidebar == "Clinical Trials":
    params["filter.advanced"] = "AREA[StudyType]INTERVENTIONAL"
elif study_type_from_sidebar == "Observational Studies":
    params["filter.advanced"] = "AREA[StudyType]OBSERVATIONAL"
    # If "All Study Types" or other, this parameter might be omitted or set to a default
    # For now, if not Clinical Trials or Observational, it won't be added, making it broader.
    # Or, you could default: else: params["query.studyType"] = "INTERVENTIONAL"

    # Overall Status: "No longer looking for participants"
    no_longer_recruiting_statuses = [
        "COMPLETED", "TERMINATED", "WITHDRAWN", 
        "ACTIVE_NOT_RECRUITING", "SUSPENDED"
    ]
    params["query.Status"] = ",".join(no_longer_recruiting_statuses)
    
    # Advanced Filters from user input
    if std_age_adv and std_age_adv != "Any":
        # API expects: CHILD, ADULT, OLDER_ADULT
        params["query.patient.age"] = std_age_adv.upper()
    
    if gender_adv and gender_adv != "Any":
        # API expects 'ALL' (maps to 'BOTH' in API), 'FEMALE', 'MALE'
        if gender_adv.upper() == "ALL":
            params["query.patient.gender"] = "BOTH" 
        else:
            params["query.patient.gender"] = gender_adv.upper()
    
    if location_country_adv and location_country_adv.strip() and location_country_adv != "Any":
        params["query.location.country"] = location_country_adv.strip()


    st.info(f"ClinicalTrials.gov API Request Params: {json.dumps(params, indent=2)}")

    ct_results_list = []
    try:
        response = requests.get(base_url, params=params, timeout=25)
        st.info(f"ClinicalTrials.gov API Request URL: {response.url}")
        response.raise_for_status()
        data = response.json()
        studies_from_api = data.get("studies", [])
        
        st.info(f"API returned {len(studies_from_api)} studies before post-filtering.")
        
        if not studies_from_api:
            return []

        # --- Post-fetch filtering ---
        temp_list_after_results_section = []
        for study_container in studies_from_api:
            if study_container.get("resultsSection"):
                temp_list_after_results_section.append(study_container)
        st.info(f"Studies after 'resultsSection' filter: {len(temp_list_after_results_section)}")
        if not temp_list_after_results_section: return []

        temp_list_after_masking = []
        for study_container in temp_list_after_results_section:
            protocol_section = study_container.get("protocolSection", {})
            design_module = protocol_section.get("designModule", {})
            passes_masking_filter = True
            if masking_type_post_filter and masking_type_post_filter != "Any":
                masking_info = design_module.get("maskingInfo", {})
                masking_from_api = masking_info.get("masking", "").upper()
                selected_masking_normalized = masking_type_post_filter.upper()
                if selected_masking_normalized == "NONE":
                    if not (masking_from_api == "NONE" or "OPEN" in masking_from_api):
                        passes_masking_filter = False
                elif selected_masking_normalized not in masking_from_api:
                    passes_masking_filter = False
            if passes_masking_filter:
                temp_list_after_masking.append(study_container)
        st.info(f"Studies after 'masking' filter: {len(temp_list_after_masking)}")
        if not temp_list_after_masking: return []

        final_filtered_list_before_cap = []
        for study_container in temp_list_after_masking:
            protocol_section = study_container.get("protocolSection", {})
            design_module = protocol_section.get("designModule", {})
            passes_intervention_filter = True
            if intervention_model_post_filter and intervention_model_post_filter != "Any":
                study_design_info = design_module.get("designInfo", {})
                intervention_model_from_api = study_design_info.get("interventionModel", "").upper()
                selected_intervention_model_normalized = intervention_model_post_filter.upper().replace(" ASSIGNMENT", "")
                if selected_intervention_model_normalized not in intervention_model_from_api:
                    passes_intervention_filter = False
            if passes_intervention_filter:
                final_filtered_list_before_cap.append(study_container)
        st.info(f"Studies after 'intervention model' filter: {len(final_filtered_list_before_cap)}")
        if not final_filtered_list_before_cap: return []

        for study_container in final_filtered_list_before_cap:
            protocol_section = study_container.get("protocolSection", {})
            identification_module = protocol_section.get("identificationModule", {})
            nct_id = identification_module.get("nctId", "N/A")
            title = (
                identification_module.get("officialTitle")
                or identification_module.get("briefTitle", "No title available")
            )
            link_url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            ct_results_list.append({
                "title": title, 
                "link": link_url,
                "nct_id": nct_id,
                "is_rag_candidate": True, 
                "source_type": "Clinical Trial Record (Results Available)"
            })
            if len(ct_results_list) >= max_results:
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
    
    return ct_results_list


# --- List of Other Databases ---
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
st.markdown("Finds **PubMed Central articles** and **Clinical Trial records (with results available)** suitable for RAG pipelines.")

st.sidebar.header("Search Parameters")
# Main inputs that will be used for specific API fields or general keyword
disease_input_ui = st.sidebar.text_input("Disease/Condition (for CT.gov: query.cond)", placeholder="e.g., Type 2 Diabetes")
outcome_input_ui = st.sidebar.text_input("Outcome of Interest (for CT.gov: query.outc)", placeholder="e.g., blood glucose control")
population_input_ui = st.sidebar.text_input("Target Population / Free Text (for CT.gov: query.term)", placeholder="e.g., elderly patients") # This is the single free text

study_type_ui = st.sidebar.selectbox( # Used for PubMed and CT.gov query.studyType
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 50, 10) # Increased max for slider

st.sidebar.markdown("---")
with st.sidebar.expander("Advanced ClinicalTrials.gov Filters", expanded=False):
    ct_std_age_options=["Any", "CHILD","ADULT","OLDER_ADULT"] # Values for query.patient.age
    ct_std_age_ui =st.selectbox("Standard Age Group", options=ct_std_age_options, index=0)
    
    country_options = ["Any", "United States", "Canada", "United Kingdom", "Germany", "France", "China", "India", "Japan", "Australia"]
    ct_location_country_ui = st.selectbox("Location Country", options=country_options, index=0)

    ct_gender_options = ["Any", "All", "Female", "Male"] # "All" will map to "BOTH" for API
    ct_gender_ui = st.selectbox("Gender", options=ct_gender_options, index=0)
    
    ct_masking_options = ["Any", "None", "Single", "Double", "Triple", "Quadruple"] 
    ct_masking_ui = st.selectbox("Masking (post-filtered)", options=ct_masking_options, index=0)
    
    ct_intervention_model_options = [
        "Any", "Single Group Assignment", "Parallel Assignment", 
        "Crossover Assignment", "Factorial Assignment", "Sequential Assignment"
    ]
    ct_intervention_model_ui = st.selectbox("Intervention Model (post-filtered)", options=ct_intervention_model_options, index=0)

# API Key and Email status display
if NCBI_API_KEY: st.sidebar.success("NCBI API Key loaded.")
else: st.sidebar.warning("NCBI API Key not loaded. Consider adding to secrets.")
if EMAIL_FOR_NCBI == "your_default_email@example.com" or not EMAIL_FOR_NCBI:
     st.sidebar.error("NCBI Email not set in secrets. Update .streamlit/secrets.toml")

if st.sidebar.button("Search"):
    # Use the UI variable names directly for clarity when passing to functions
    if not (disease_input_ui or outcome_input_ui or population_input_ui): # Check if at least one main keyword is provided
        st.error("Please fill in at least one of: Disease, Outcome, or Target Population.")
    else:
        # --- PubMed Search ---
        st.header("PubMed / PubMed Central Results")
        pubmed_status_message = st.empty()
        with st.spinner(f"Performing sequential PubMed search..."):
            pubmed_status_message.info("Initializing PubMed search...")
            # PubMed uses the main inputs as general keywords for its sequential search
            pubmed_results, pubmed_query_description = fetch_pubmed_results(
                disease_input_ui, outcome_input_ui, population_input_ui, 
                study_type_ui, max_results_per_source
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

        # --- ClinicalTrials.gov Search ---
        st.header("ClinicalTrials.gov Results")
        ct_status_message = st.empty()
        
        # Prepare parameters for fetch_clinicaltrials_results from UI elements
        location_country_to_pass = ct_location_country_ui if ct_location_country_ui != "Any" else None
        std_age_to_pass = ct_std_age_ui if ct_std_age_ui != "Any" else None
        gender_to_pass = ct_gender_ui if ct_gender_ui != "Any" else None
        masking_to_pass = ct_masking_ui if ct_masking_ui != "Any" else None
        intervention_model_to_pass = ct_intervention_model_ui if ct_intervention_model_ui != "Any" else None

        ct_status_message.info(f"Searching ClinicalTrials.gov with specified parameters...")
        
        with st.spinner(f"Searching ClinicalTrials.gov..."):
            ct_results = fetch_clinicaltrials_results(
                disease_input=disease_input_ui,         # For query.cond
                outcome_input=outcome_input_ui,       # For query.outc
                population_input=population_input_ui, # For query.term (free text)
                std_age_adv=std_age_to_pass,          # For query.patient.age
                location_country_adv=location_country_to_pass, # For query.location.country
                gender_adv=gender_to_pass,            # For query.patient.gender
                study_type_from_sidebar=study_type_ui,# For query.studyType
                masking_type_post_filter=masking_to_pass,
                intervention_model_post_filter=intervention_model_to_pass,
                max_results=max_results_per_source
            )
        
        if ct_results:
            st.write(f"Found {len(ct_results)} Clinical Trial records **with results available** matching all criteria:") 
            for res in ct_results:
                st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']} (NCT: {res['nct_id']})*") 
                st.divider()
        else:
            ct_status_message.warning(f"No Clinical Trial records found matching all criteria. Check API request details in the info messages above.")
        
        st.markdown("---")
        st.success("Search complete.")
else:
    st.info("Enter search parameters in the sidebar and click 'Search'.")

st.sidebar.markdown("---")
st.sidebar.header("Other Free Medical Research Databases")
for db in OTHER_DATABASES: 
    st.sidebar.markdown(f"[{db['name']}]({db['url']})")
st.sidebar.markdown("---")
st.sidebar.caption(f"Respect API terms of service.")
