import streamlit as st
import requests
import xmltodict
import json
import re

# --- Configuration ---
try:
    NCBI_API_KEY = st.secrets.get("NCBI_API_KEY")
    if not NCBI_API_KEY: NCBI_API_KEY = None
except Exception: NCBI_API_KEY = None

try:
    EMAIL_FOR_NCBI = st.secrets.get("EMAIL_FOR_NCBI", "your_default_email@example.com")
except Exception: EMAIL_FOR_NCBI = "your_default_email@example.com"

def get_mesh_term_for_ct(term, api_key=None, email=None):
    """
    Fetches the official MeSH term for a given keyword.
    Returns the official term, or the original term if not found.
    """
    if not term or not term.strip():
        return term

    original_term = term.strip()
    sanitized_term = original_term.replace('-', ' ').strip()
    sanitized_lower = sanitized_term.lower()

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "mesh",
        "term": f"\"{sanitized_term}\"[MeSH Terms] OR {sanitized_term}[All Fields]",
        "retmax": "20",
        "retmode": "json",
        "tool": "streamlit_app_pubmed_finder",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        translationset = data.get("esearchresult", {}).get("translationset", [])

        if not id_list:
            return original_term

        mesh_term_from_translation = None
        for translation in translationset:
            to_field = translation.get("to", "")
            match = re.search(r'"([^"]+)"\[MeSH Terms\]', to_field)
            if match:
                mesh_term_from_translation = match.group(1)
                break

        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        summary_params = {
            "db": "mesh",
            "id": ",".join(id_list),
            "retmode": "json",
            "tool": "streamlit_app_pubmed_finder",
            "email": email
        }
        if api_key:
            summary_params["api_key"] = api_key

        summary_response = requests.get(summary_url, params=summary_params, timeout=10)
        summary_response.raise_for_status()
        summary_data = summary_response.json()

        best_match = None
        best_score = -1

        for mesh_id in id_list:
            result_for_id = summary_data.get("result", {}).get(mesh_id, {})
            mesh_terms = result_for_id.get("ds_meshterms", [])
            record_type = result_for_id.get("ds_recordtype", "")

            if not mesh_terms:
                continue

            mesh_term = mesh_terms[0] if mesh_terms else ""
            mesh_terms_lower = [mt.lower() for mt in mesh_terms if isinstance(mt, str)]

            score = 0
            if mesh_term_from_translation and mesh_term.lower() == mesh_term_from_translation.lower():
                score = 5
            elif record_type == "descriptor":
                score += 2
                if sanitized_lower == mesh_term.lower():
                    score += 2
                elif sanitized_lower in mesh_terms_lower:
                    score += 1
            elif record_type == "supplemental-record" and sanitized_lower in mesh_terms_lower:
                score = 1

            if score > best_score:
                best_score = score
                best_match = mesh_term

        if best_match:
            return best_match

        for mesh_id in id_list:
            result_for_id = summary_data.get("result", {}).get(mesh_id, {})
            if result_for_id.get("ds_recordtype") == "descriptor":
                mesh_term = result_for_id.get("ds_meshterms", [original_term])[0]
                return mesh_term

        return original_term

    except Exception as e:
        st.warning(f"MeSH lookup failed for '{original_term}', using original term. Error: {str(e)}")
        return original_term

def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=10):
    """
    Constructs a simple, effective PubMed query, fetches results,
    and extracts MeSH terms for display.
    """
    query_parts = []
    if disease and disease.strip():
        query_parts.append(disease.strip())
    if outcome and outcome.strip():
        query_parts.append(outcome.strip())
    if population and population.strip():
        query_parts.append(population.strip())

    if not query_parts:
        return [], "No search terms provided for PubMed."

    final_query = " AND ".join(query_parts)

    study_type_query_segment = ""
    if study_type_selection == "Clinical Trials":
        study_type_query_segment = '("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type])'
    elif study_type_selection == "Observational Studies":
        study_type_query_segment = '("observational study"[Publication Type] OR "cohort study"[All Fields] OR "case-control study"[All Fields])'
    
    if study_type_query_segment:
        final_query = f"({final_query}) AND ({study_type_query_segment})"

    st.info(f"PubMed Final Query: {final_query}")

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    esearch_params = {
        "db": "pubmed", "term": final_query, "retmax": str(max_results),
        "retmode": "json", "usehistory": "y", "tool": "streamlit_app_pubmed_finder",
        "email": EMAIL_FOR_NCBI,
    }
    if NCBI_API_KEY:
        esearch_params["api_key"] = NCBI_API_KEY

    try:
        response = requests.get(f"{base_url}esearch.fcgi", params=esearch_params, timeout=20)
        response.raise_for_status()
        esearch_data = response.json()
        id_list = esearch_data.get("esearchresult", {}).get("idlist", [])

        if not id_list:
            st.warning(f"No PubMed results for query. Try simplifying your terms.")
            return [], f"PubMed: No results for query: {final_query}"

        efetch_params = {
            "db": "pubmed", "retmode": "xml", "rettype": "abstract",
            "id": ",".join(id_list), "tool": "streamlit_app_pubmed_finder",
            "email": EMAIL_FOR_NCBI,
        }
        if NCBI_API_KEY:
            efetch_params["api_key"] = NCBI_API_KEY

        summary_response = requests.get(f"{base_url}efetch.fcgi", params=efetch_params, timeout=25)
        summary_response.raise_for_status()
        
        articles_dict = xmltodict.parse(summary_response.content)
        pubmed_articles_container = articles_dict.get("PubmedArticleSet", {})
        if not pubmed_articles_container:
            return [], f"PubMed: No PubmedArticleSet for query: {final_query}"

        articles_list_xml = pubmed_articles_container.get("PubmedArticle", [])
        if not isinstance(articles_list_xml, list):
            articles_list_xml = [articles_list_xml] if articles_list_xml else []

        pubmed_results_list = []
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

            mesh_terms_list = []
            mesh_heading_list = medline_citation.get("MeshHeadingList", {}).get("MeshHeading", [])
            if not isinstance(mesh_heading_list, list):
                mesh_heading_list = [mesh_heading_list] if mesh_heading_list else []
            
            for heading in mesh_heading_list:
                descriptor_name = heading.get("DescriptorName", {}).get("#text")
                if descriptor_name:
                    mesh_terms_list.append(descriptor_name)

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
                "source_type": "PubMed Central Article" if is_rag_candidate else "PubMed Abstract",
                "mesh_terms": mesh_terms_list
            })

        return pubmed_results_list, f"PubMed: Fetched {len(pubmed_results_list)} results for query: {final_query}"

    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP error ({http_err.response.status_code if http_err.response else 'N/A'}): {http_err.response.text[:200] if http_err.response else str(http_err)}"
        st.error(f"PubMed API Error: {error_message}")
        return [], f"PubMed: {error_message}"
    except Exception as e:
        st.error(f"PubMed Search Error: {str(e)}")
        return [], f"PubMed: Error: {str(e)}"
        
def fetch_clinicaltrials_results(
    disease_input,
    outcome_input,
    population_input,
    std_age_adv=None,
    location_country_adv=None,
    gender_adv=None,
    study_type_from_sidebar=None,
    masking_type_post_filter=None,
    intervention_model_post_filter=None,
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
        "pageSize": str(max_results * 2),
    }

    if disease_input and disease_input.strip():
        st.info(f"Looking up MeSH term for '{disease_input}'...")
        mesh_disease_term = get_mesh_term_for_ct(disease_input, NCBI_API_KEY, EMAIL_FOR_NCBI)
        if mesh_disease_term.lower() != disease_input.strip().lower():
            st.info(f"Found MeSH term: '{mesh_disease_term}'. Using it for the condition search.")
            params["query.cond"] = f'{mesh_disease_term} OR "{disease_input.strip()}"'
        else:
            st.info("No specific MeSH term found, using original term for condition search.")
            params["query.cond"] = disease_input.strip()

    if population_input and population_input.strip():
        params["query.term"] = population_input.strip() 

    if outcome_input and outcome_input.strip():
        params["query.outc"] = outcome_input.strip()

    if study_type_from_sidebar == "Clinical Trials":
        params["filter.advanced"] = "AREA[StudyType]INTERVENTIONAL"
    elif study_type_from_sidebar == "Observational Studies":
        params["filter.advanced"] = "AREA[StudyType]OBSERVATIONAL"

    no_longer_recruiting_statuses = [
        "COMPLETED", "TERMINATED", "WITHDRAWN", 
        "ACTIVE_NOT_RECRUITING", "SUSPENDED"
    ]
    params["filter.overallStatus"] = ",".join(no_longer_recruiting_statuses)
    
    if std_age_adv and std_age_adv != "Any":
        if std_age_adv == "CHILD":
            age_filter = "AREA[MinimumAge]RANGE[MIN, 17 years] AND AREA[MaximumAge]RANGE[MIN, 17 years]"
        elif std_age_adv == "ADULT":
            age_filter = "AREA[MinimumAge]RANGE[18 years, 64 years] AND AREA[MaximumAge]RANGE[18 years, 64 years]"
        elif std_age_adv == "OLDER_ADULT":
            age_filter = "AREA[MinimumAge]RANGE[65 years, MAX]"
        if "filter.advanced" in params:
            params["filter.advanced"] += f" AND {age_filter}"
        else:
            params["filter.advanced"] = age_filter
    
    if gender_adv and gender_adv != "Any":
        sex_value = "ALL" if gender_adv.upper() == "ALL" else gender_adv.upper()
        gender_filter = f"AREA[Sex]{sex_value}"
        if "filter.advanced" in params:
            params["filter.advanced"] += f" AND {gender_filter}"
        else:
            params["filter.advanced"] = gender_filter
    
    if location_country_adv and location_country_adv.strip() and location_country_adv != "Any":
        params["query.locn"] = location_country_adv.strip()

    ct_results_list = []
    try:
        response = requests.get(base_url, params=params, timeout=25)
        response.raise_for_status()
        data = response.json()
        studies_from_api = data.get("studies", [])
        
        if not studies_from_api:
            return []

        temp_list_after_results_section = []
        for study_container in studies_from_api:
            if study_container.get("resultsSection"):
                temp_list_after_results_section.append(study_container)
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
disease_input_ui = st.sidebar.text_input("Disease/Condition (for CT.gov: query.cond)", placeholder="e.g., Type 2 Diabetes")
outcome_input_ui = st.sidebar.text_input("Outcome of Interest (for CT.gov: query.outc)", placeholder="e.g., blood glucose control")
population_input_ui = st.sidebar.text_input("Target Population / Free Text (for CT.gov: query.term)", placeholder="e.g., elderly patients")

study_type_ui = st.sidebar.selectbox(
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 50, 10)

st.sidebar.markdown("---")
with st.sidebar.expander("Advanced ClinicalTrials.gov Filters", expanded=False):
    ct_std_age_options=["Any", "CHILD","ADULT","OLDER_ADULT"]
    ct_std_age_ui =st.selectbox("Standard Age Group", options=ct_std_age_options, index=0)
    
    country_options = ["Any", "United States", "Canada", "United Kingdom", "Germany", "France", "China", "India", "Japan", "Australia"]
    ct_location_country_ui = st.selectbox("Location Country", options=country_options, index=0)

    ct_gender_options = ["Any", "All", "Female", "Male"]
    ct_gender_ui = st.selectbox("Gender", options=ct_gender_options, index=0)
    
    ct_masking_options = ["Any", "None", "Single", "Double", "Triple", "Quadruple"] 
    ct_masking_ui = st.selectbox("Masking (post-filtered)", options=ct_masking_options, index=0)
    
    ct_intervention_model_options = [
        "Any", "Single Group Assignment", "Parallel Assignment", 
        "Crossover Assignment", "Factorial Assignment", "Sequential Assignment"
    ]
    ct_intervention_model_ui = st.selectbox("Intervention Model (post-filtered)", options=ct_intervention_model_options, index=0)

if NCBI_API_KEY: st.sidebar.success("NCBI API Key loaded.")
else: st.sidebar.warning("NCBI API Key not loaded. Consider adding to secrets.")
if EMAIL_FOR_NCBI == "your_default_email@example.com" or not EMAIL_FOR_NCBI:
     st.sidebar.error("NCBI Email not set in secrets. Update .streamlit/secrets.toml")

if st.sidebar.button("Search"):
    if not (disease_input_ui or outcome_input_ui or population_input_ui):
        st.error("Please fill in at least one of: Disease, Outcome, or Target Population.")
    else:
        st.header("PubMed / PubMed Central Results")
        pubmed_status_message = st.empty()
        with st.spinner(f"Performing PubMed search..."):
            pubmed_status_message.info("Initializing PubMed search...")
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
                if res.get("mesh_terms"):
                    st.caption(f"**MeSH Terms:** {' | '.join(res['mesh_terms'])}")
                st.divider()
        else:
            st.write("No results from PubMed based on the criteria or an error occurred during search.")
        st.markdown("---")

        st.header("ClinicalTrials.gov Results")
        ct_status_message = st.empty()
        
        location_country_to_pass = ct_location_country_ui if ct_location_country_ui != "Any" else None
        std_age_to_pass = ct_std_age_ui if ct_std_age_ui != "Any" else None
        gender_to_pass = ct_gender_ui if ct_gender_ui != "Any" else None
        masking_to_pass = ct_masking_ui if ct_masking_ui != "Any" else None
        intervention_model_to_pass = ct_intervention_model_ui if ct_intervention_model_ui != "Any" else None

        ct_status_message.info(f"Searching ClinicalTrials.gov with specified parameters...")
        
        with st.spinner(f"Searching ClinicalTrials.gov..."):
            ct_results = fetch_clinicaltrials_results(
                disease_input=disease_input_ui,
                outcome_input=outcome_input_ui,
                population_input=population_input_ui,
                std_age_adv=std_age_to_pass,
                location_country_adv=location_country_to_pass,
                gender_adv=gender_to_pass,
                study_type_from_sidebar=study_type_ui,
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
