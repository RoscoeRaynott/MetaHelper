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
    Constructs a simple keyword query for ClinicalTrials.gov API v2.
    Now returns a simple keyword string instead of field-specific syntax.
    """
    query_parts = []

    # Build simple keyword query from user inputs
    if disease_input and disease_input.strip():
        query_parts.append(disease_input.strip())
    
    if outcome_input and outcome_input.strip():
        query_parts.append(outcome_input.strip())

    if population_input and population_input.strip():
        query_parts.append(population_input.strip())

    if not query_parts:
        return None 

    # Return simple keyword query joined with AND
    final_query = "".join(query_parts)
    st.write(final_query)
    return final_query


# --- Functions for Fetching Results from APIs ---
def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=10):
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
    disease_input,
    outcome_input,
    population_input,
    min_age=None,
    max_age=None,
    location_country=None,
    gender=None,
    masking_type=None,
    intervention_model=None,
    max_results=10
):
    """
    Fetches results from ClinicalTrials.gov API v2 by embedding “Interventional” and
    “Completed” into query.cond (instead of using query.studyType/query.overallStatus).
    We'll do any stricter filtering (masking/interventionModel) after retrieving the JSON.
    """

    # If none of the three main terms (disease/outcome/population) are provided, return empty.
    if not (disease_input or outcome_input or population_input):
        return []

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    # Build the simple free‐text part (disease/outcome/population)
    query_parts = []
    if disease_input and disease_input.strip():
        query_parts.append(disease_input.strip())
    if outcome_input and outcome_input.strip():
        query_parts.append(outcome_input.strip())
    if population_input and population_input.strip():
        query_parts.append(population_input.strip())

    # According to v2 docs, we send everything (including “Interventional” & “Completed”)
    # into “query.cond” as a space‐separated string:
    params = {
        "format": "json",
        "pageSize": str(max_results),
        "query.cond": " ".join(query_parts + ["Interventional", "Completed"]),
    }

    # Add age filters if provided (these are still valid v2 parameters)
    if min_age is not None:
        params["query.eligibility.minimumAge"] = str(min_age)
    if max_age is not None:
        params["query.eligibility.maximumAge"] = str(max_age)

    # Add location filter if provided
    if location_country and location_country.strip() and location_country != "Any":
        params["query.location.country"] = location_country.strip()

    # Add gender filter if provided
    if gender and gender != "Any":
        params["query.eligibility.gender"] = "ALL" if gender == "All" else gender.upper()

    try:
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        studies = data.get("studies", [])
        if not studies:
            return []

        ct_results_list = []
        for study in studies:
            # Only include trials that have resultsSection
            if not study.get("resultsSection"):
                continue

            protocol = study.get("protocolSection", {})
            id_mod = protocol.get("identificationModule", {})
            status_mod = protocol.get("statusModule", {})

            nct_id = id_mod.get("nctId", "N/A")
            title = (
                id_mod.get("officialTitle")
                or id_mod.get("briefTitle", "No title available")
            )
            # We already requested “Completed” in query.cond, but double-check:
            overall_status = status_mod.get("overallStatus", "")
            if "Completed".lower() not in overall_status.lower():
                continue

            link_url = (
                f"https://clinicaltrials.gov/study/{nct_id}"
                if nct_id != "N/A"
                else "#"
            )

            # Now apply the v2 “masking” filter if requested:
            design_module = protocol.get("designModule", {})
            if masking_type and masking_type != "Any":
                masking_info = design_module.get("maskingInfo", {})
                masking = masking_info.get("masking", "")
                if masking_type.lower() == "none" and masking.upper() != "NONE":
                    continue
                if (
                    masking_type.lower() != "none"
                    and masking_type.upper() not in masking.upper()
                ):
                    continue

            # Apply “interventionModel” filter if requested
            if intervention_model and intervention_model != "Any":
                design_info = design_module.get("designInfo", {})
                intervention = design_info.get("interventionModel", "")
                if intervention_model.lower() not in intervention.lower():
                    continue

            ct_results_list.append(
                {
                    "title": title,
                    "link": link_url,
                    "nct_id": nct_id,
                    "is_rag_candidate": True,
                    "source_type": "Clinical Trial Record (Results Available)",
                }
            )

        return ct_results_list

    except requests.exceptions.HTTPError as http_err:
        st.error(
            f"ClinicalTrials.gov API Error: HTTP {http_err.response.status_code} - {http_err.response.text}"
        )
        return []
    except Exception as e:
        st.error(f"ClinicalTrials.gov API Error: {str(e)}")
        return []

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
    
    country_options = ["Any", "United States", "Canada", "United Kingdom", "Germany", "France", "China", "India", "Japan", "Australia"]
    ct_location_country = st.selectbox("Location Country", options=country_options, index=0)

    ct_gender_options = ["Any", "All", "Female", "Male"]
    ct_gender = st.selectbox("Gender", options=ct_gender_options, index=0)
    
    ct_masking_options = ["Any", "None", "Single", "Double", "Triple", "Quadruple"] 
    ct_masking = st.selectbox("Masking", options=ct_masking_options, index=0)
    
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
        
        # Prepare parameters for the enhanced function
        location_country_to_pass = ct_location_country if ct_location_country != "Any" else None
        min_age_to_pass = ct_min_age if ct_min_age is not None else None
        max_age_to_pass = ct_max_age if ct_max_age is not None else None
        gender_to_pass = ct_gender if ct_gender != "Any" else None
        masking_to_pass = ct_masking if ct_masking != "Any" else None
        intervention_model_to_pass = ct_intervention_model if ct_intervention_model != "Any" else None

        ct_status_message.info(f"Searching ClinicalTrials.gov with all specified filters...")
        
        with st.spinner(f"Searching ClinicalTrials.gov..."):
            ct_results = fetch_clinicaltrials_results(
                disease_input=disease,
                outcome_input=outcome_of_interest,
                population_input=target_population,
                min_age=min_age_to_pass,
                max_age=max_age_to_pass,
                location_country=location_country_to_pass,
                gender=gender_to_pass,
                masking_type=masking_to_pass,
                intervention_model=intervention_model_to_pass,
                max_results=max_results_per_source
            )
        
        if ct_results:
            st.write(f"Found {len(ct_results)} Clinical Trial records **with results available**:") 
            for res in ct_results:
                st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']} (NCT: {res['nct_id']})*") 
                st.divider()
        else:
            ct_status_message.info(f"No Clinical Trial records found **with results available** matching the specified criteria.")
        
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
