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
def construct_clinicaltrials_api_query(
    disease_input, 
    outcome_input, 
    population_input, 
    min_age=None,
    max_age=None,
    location_country=None,
    gender=None,
    masking_type=None,
    intervention_model=None
):
    """
    Constructs a targeted ClinicalTrials.gov API query with fixed parameters
    and optional advanced filters.
    "Population" input is now primarily searched within ELIGIBILITY_CRITERIA.
    """
    query_parts = []

    # --- Fixed Parameters ---
    query_parts.append("STUDY_TYPE[Interventional]")
    query_parts.append("OVERALL_STATUS[COMPLETED]")

    # --- User Inputs (Mapped to Specific Fields) ---
    if disease_input and disease_input.strip():
        query_parts.append(f"CONDITION[{disease_input.strip()}]")
    
    if outcome_input and outcome_input.strip():
        query_parts.append(f"OUTCOME_MEASURE[{outcome_input.strip()}]")

    # --- Population Input: Targeted to Eligibility Criteria ---
    if population_input and population_input.strip():
        # This is a more precise way to handle population descriptions
        query_parts.append(f"ELIGIBILITY_CRITERIA[{population_input.strip()}]")
        # You could also add it as a general keyword search if desired,
        # but targeting eligibility is often better for "population".
        # For example, to also search titles/summaries etc. for the population term:
        # query_parts.append(f"AREA[OverallOfficialOrBriefTitleBriefSummary]Search[{population_input.strip()}]")
        # However, be cautious as this can make the query very broad or very narrow unpredictably.
        # Let's stick to ELIGIBILITY_CRITERIA for now for more predictability.

    # --- Advanced Filters ---
    if min_age is not None: # Check for None explicitly as 0 is a valid age
        query_parts.append(f"MIN_AGE[{min_age}]") # Using just the number
    
    if max_age is not None:
        query_parts.append(f"MAX_AGE[{max_age}]") # Using just the number
        
    if location_country and location_country.strip() and location_country != "Any":
        query_parts.append(f"LOCATION_COUNTRY[{location_country.strip()}]")
        
    if gender and gender != "Any": 
        query_parts.append(f"GENDER[{gender}]")
        
    if masking_type and masking_type != "Any": 
        query_parts.append(f"MASKING[{masking_type}]")
        
    if intervention_model and intervention_model != "Any": 
        query_parts.append(f"INTERVENTION_MODEL[{intervention_model.strip()}]")

    if not query_parts:
        return None 
    
    # Ensure no empty strings are joined if some inputs were None or empty
    # Though fixed params should prevent a completely empty list.
    valid_query_parts = [part for part in query_parts if part]
    if not valid_query_parts:
        return None

    final_query = " AND ".join(valid_query_parts)
    return final_query


# --- Functions for Fetching Results from APIs ---
def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=10):
    # ... (fetch_pubmed_results function remains the same as the previous corrected version)
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


def fetch_clinicaltrials_results(query, max_results=10):
    if not query: return []
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    params = { "query.term": query, "pageSize": str(max_results), "format": "json" }
    ct_results_list = []
    try:
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        studies = data.get("studies", [])
        if not studies: return []

        # START OF MODIFIED FILTERING LOGIC FOR ClinicalTrials.gov
        for study_container in studies: 
            # MODIFIED FILTER: Check for the presence and non-emptiness of 'resultsSection'
            results_section = study_container.get("resultsSection")
            if not results_section: # If 'resultsSection' key is missing or its value is None/empty
                continue # Skip this trial
            
            # If results_section exists, proceed to extract other details
            protocol_section = study_container.get("protocolSection", {}) 
            if not protocol_section: continue 

            identification_module = protocol_section.get("identificationModule", {})
            status_module = protocol_section.get("statusModule", {})
            
            nct_id = identification_module.get("nctId", "N/A")
            title = identification_module.get("officialTitle") or identification_module.get("briefTitle", "No title available")
            overall_status = status_module.get("overallStatus", "N/A") # Get overallStatus from statusModule
            link_url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            ct_results_list.append({
                "title": title, 
                "link": link_url,
                "nct_id": nct_id,
                "is_rag_candidate": True, 
                "source_type": "Clinical Trial Record (Results Available)" # Updated source_type slightly
            })
        # END OF MODIFIED FILTERING LOGIC
            
    except Exception as e:
        st.error(f"ClinicalTrials.gov API Error: {str(e)}")
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
target_population = st.sidebar.text_input("Target Population", placeholder="e.g., elderly patients with diabetes")
disease = st.sidebar.text_input("Disease/Condition", placeholder="e.g., Type 2 Diabetes")
outcome_of_interest = st.sidebar.text_input("Outcome of Interest", placeholder="e.g., blood glucose control")
study_type = st.sidebar.selectbox(
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 25, 10)

st.sidebar.markdown("---") # Separator
with st.sidebar.expander("Advanced ClinicalTrials.gov Filters", expanded=False):
    ct_min_age = st.number_input("Minimum Age (Years)", min_value=0, max_value=120, value=None, step=1, placeholder="Any")
    ct_max_age = st.number_input("Maximum Age (Years)", min_value=0, max_value=120, value=None, step=1, placeholder="Any")
    
    # For country, a long dropdown isn't ideal. Text input is better.
    # User needs to know country names as API expects them.
    # Or, provide a curated list of common countries.
    country_options = ["Any", "United States", "Canada", "United Kingdom", "Germany", "France", "China", "India", "Japan", "Australia"] # Example
    ct_location_country = st.selectbox("Location Country", options=country_options, index=0)
    # Alternatively, for more flexibility:
    # ct_location_country_text = st.text_input("Location Country (e.g., United States)", placeholder="Any")


    ct_gender_options = ["Any", "All", "Female", "Male"] # "All" is official CT.gov term for both if specified
    ct_gender = st.selectbox("Gender", options=ct_gender_options, index=0)
    
    # Masking types from ClinicalTrials.gov API documentation or common usage
    ct_masking_options = ["Any", "None", "Single", "Double", "Triple", "Quadruple"] 
    ct_masking = st.selectbox("Masking", options=ct_masking_options, index=0)
    
    # Intervention Models from ClinicalTrials.gov
    ct_intervention_model_options = [
        "Any", "Single Group Assignment", "Parallel Assignment", 
        "Crossover Assignment", "Factorial Assignment", "Sequential Assignment"
    ]
    ct_intervention_model = st.selectbox("Intervention Model", options=ct_intervention_model_options, index=0)

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
        
        # The 'study_type' from the sidebar is now fully ignored by the CT.gov function,
        # as "Interventional" is fixed within construct_clinicaltrials_api_query.
        # Population input for ct_location_country_text would be:
        # location_country_to_pass = ct_location_country_text if ct_location_country_text else None
        # For the selectbox version:
        location_country_to_pass = ct_location_country if ct_location_country != "Any" else None
        
        min_age_to_pass = ct_min_age if ct_min_age is not None else None # Handle placeholder for number_input
        max_age_to_pass = ct_max_age if ct_max_age is not None else None


        ct_api_query_string = construct_clinicaltrials_api_query(
            disease_input=disease,                 # from main sidebar input
            outcome_input=outcome_of_interest,     # from main sidebar input
            population_input=target_population,    # from main sidebar input
            min_age=min_age_to_pass,
            max_age=max_age_to_pass,
            location_country=location_country_to_pass,
            gender=ct_gender if ct_gender != "Any" else None,
            masking_type=ct_masking if ct_masking != "Any" else None,
            intervention_model=ct_intervention_model if ct_intervention_model != "Any" else None
        )
        
        if ct_api_query_string:
            ct_status_message.info(f"Searching ClinicalTrials.gov with specified parameters...")
            st.write("**ClinicalTrials.gov API Query (Structured):**")
            st.code(ct_api_query_string, language="text")
            with st.spinner(f"Searching ClinicalTrials.gov..."):
                ct_results = fetch_clinicaltrials_results(ct_api_query_string, max_results_per_source)
            
            if ct_results:
                st.write(f"Found {len(ct_results)} Clinical Trial records **with results available**:") 
                for res in ct_results:
                    st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']} (NCT: {res['nct_id']})*") 
                    st.divider()
            else:
                ct_status_message.info(f"No Clinical Trial records found **with results available** for terms: {ct_api_query_string}")
        else: 
            ct_status_message.warning("Could not construct a ClinicalTrials.gov query from inputs.")
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
