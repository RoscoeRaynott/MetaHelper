import streamlit as st
import requests
import xmltodict
import json
import time
from typing import List, Dict, Set, Tuple

# --- Configuration (keep your existing config) ---
try:
    NCBI_API_KEY = st.secrets.get("NCBI_API_KEY")
    if not NCBI_API_KEY: NCBI_API_KEY = None
except Exception: NCBI_API_KEY = None

try:
    EMAIL_FOR_NCBI = st.secrets.get("EMAIL_FOR_NCBI", "your_default_email@example.com")
except Exception: EMAIL_FOR_NCBI = "your_default_email@example.com"

# --- NEW: MeSH Term Expansion Functions ---

def search_mesh_terms(query_term: str, max_terms: int = 10) -> List[Dict]:
    """
    Search for MeSH terms using NCBI's E-utilities
    Returns list of MeSH terms with their MeSH IDs and descriptions
    """
    if not query_term or not query_term.strip():
        return []
    
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "mesh",
        "term": query_term.strip(),
        "retmax": str(max_terms),
        "retmode": "json",
        "tool": "streamlit_mesh_expander",
        "email": EMAIL_FOR_NCBI
    }
    
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        mesh_ids = data.get("esearchresult", {}).get("idlist", [])
        if not mesh_ids:
            return []
        
        # Fetch detailed information for these MeSH terms
        return fetch_mesh_details(mesh_ids[:max_terms])
        
    except Exception as e:
        st.warning(f"MeSH search error for '{query_term}': {str(e)}")
        return []

def fetch_mesh_details(mesh_ids: List[str]) -> List[Dict]:
    """
    Fetch detailed MeSH term information including synonyms and related terms
    """
    if not mesh_ids:
        return []
    
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "mesh",
        "id": ",".join(mesh_ids),
        "retmode": "xml",
        "tool": "streamlit_mesh_expander",
        "email": EMAIL_FOR_NCBI
    }
    
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    
    try:
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        
        # Parse XML response
        mesh_data = xmltodict.parse(response.content)
        descriptor_records = mesh_data.get("DescriptorRecordSet", {}).get("DescriptorRecord", [])
        
        if not isinstance(descriptor_records, list):
            descriptor_records = [descriptor_records] if descriptor_records else []
        
        mesh_terms = []
        for record in descriptor_records:
            if not isinstance(record, dict):
                continue
                
            # Extract main heading
            descriptor_name = record.get("DescriptorName", {})
            main_heading = descriptor_name.get("String", "") if isinstance(descriptor_name, dict) else ""
            
            # Extract MeSH ID
            descriptor_ui = record.get("DescriptorUI", "")
            
            # Extract synonyms/entry terms
            synonyms = []
            concept_list = record.get("ConceptList", {}).get("Concept", [])
            if not isinstance(concept_list, list):
                concept_list = [concept_list] if concept_list else []
            
            for concept in concept_list:
                if isinstance(concept, dict):
                    term_list = concept.get("TermList", {}).get("Term", [])
                    if not isinstance(term_list, list):
                        term_list = [term_list] if term_list else []
                    
                    for term in term_list:
                        if isinstance(term, dict):
                            term_string = term.get("String", "")
                            if term_string and term_string.lower() != main_heading.lower():
                                synonyms.append(term_string)
            
            if main_heading:
                mesh_terms.append({
                    "main_heading": main_heading,
                    "mesh_id": descriptor_ui,
                    "synonyms": list(set(synonyms))  # Remove duplicates
                })
        
        return mesh_terms
        
    except Exception as e:
        st.warning(f"MeSH details fetch error: {str(e)}")
        return []

def expand_search_terms_with_mesh(original_term: str, max_mesh_terms: int = 5, max_synonyms_per_term: int = 3) -> Tuple[List[str], str]:
    """
    Expand a search term using MeSH vocabulary
    Returns: (expanded_terms_list, expansion_summary)
    """
    if not original_term or not original_term.strip():
        return [original_term], "No expansion (empty term)"
    
    # Start with original term
    expanded_terms = [original_term.strip()]
    expansion_details = []
    
    # Search MeSH
    mesh_terms = search_mesh_terms(original_term, max_mesh_terms)
    
    if mesh_terms:
        for mesh_term in mesh_terms:
            main_heading = mesh_term.get("main_heading", "")
            synonyms = mesh_term.get("synonyms", [])
            mesh_id = mesh_term.get("mesh_id", "")
            
            # Add main MeSH heading if different from original
            if main_heading and main_heading.lower() != original_term.lower().strip():
                expanded_terms.append(main_heading)
            
            # Add selected synonyms
            for synonym in synonyms[:max_synonyms_per_term]:
                if synonym.lower() not in [term.lower() for term in expanded_terms]:
                    expanded_terms.append(synonym)
            
            expansion_details.append(f"MeSH: {main_heading} ({mesh_id})")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_expanded_terms = []
    for term in expanded_terms:
        if term.lower() not in seen:
            seen.add(term.lower())
            unique_expanded_terms.append(term)
    
    expansion_summary = f"Original: '{original_term}' → {len(unique_expanded_terms)} terms"
    if expansion_details:
        expansion_summary += f" (Found: {', '.join(expansion_details[:2])}{'...' if len(expansion_details) > 2 else ''})"
    
    return unique_expanded_terms, expansion_summary

def build_expanded_query(terms_list: List[str], operator: str = "OR") -> str:
    """
    Build a query string from expanded terms using specified operator
    """
    if not terms_list:
        return ""
    
    # Clean and quote terms that contain spaces or special characters
    cleaned_terms = []
    for term in terms_list:
        term = term.strip()
        if not term:
            continue
        # Quote terms with spaces or special characters
        if " " in term or any(char in term for char in ['"', '(', ')', '[', ']']):
            cleaned_terms.append(f'"{term}"')
        else:
            cleaned_terms.append(term)
    
    if len(cleaned_terms) == 1:
        return cleaned_terms[0]
    
    return f"({f' {operator} '.join(cleaned_terms)})"

# --- UPDATED: Enhanced PubMed Function with MeSH Expansion ---

def fetch_pubmed_results_with_mesh(disease, outcome, population, study_type_selection, max_results=10, enable_mesh_expansion=True):
    """
    Enhanced PubMed search with MeSH term expansion
    """
    search_stages_keywords = []
    expansion_summaries = []
    
    # Process each input with optional MeSH expansion
    if disease and disease.strip():
        if enable_mesh_expansion:
            expanded_disease_terms, disease_summary = expand_search_terms_with_mesh(disease.strip())
            disease_query = build_expanded_query(expanded_disease_terms)
            expansion_summaries.append(f"Disease: {disease_summary}")
        else:
            disease_query = disease.strip()
        search_stages_keywords.append(disease_query)
    
    if outcome and outcome.strip():
        if enable_mesh_expansion:
            expanded_outcome_terms, outcome_summary = expand_search_terms_with_mesh(outcome.strip())
            outcome_query = build_expanded_query(expanded_outcome_terms)
            expansion_summaries.append(f"Outcome: {outcome_summary}")
        else:
            outcome_query = outcome.strip()
        search_stages_keywords.append(outcome_query)
    
    if population and population.strip():
        if enable_mesh_expansion:
            expanded_population_terms, population_summary = expand_search_terms_with_mesh(population.strip())
            population_query = build_expanded_query(expanded_population_terms)
            expansion_summaries.append(f"Population: {population_summary}")
        else:
            population_query = population.strip()
        search_stages_keywords.append(population_query)

    if not search_stages_keywords:
        return [], "No search terms provided for PubMed.", []

    # Display expansion information
    if expansion_summaries:
        st.info("MeSH Expansion Applied:\n" + "\n".join(expansion_summaries))

    # Build study type filter
    study_type_query_segment = ""
    if study_type_selection == "Clinical Trials":
        study_type_query_segment = '("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type])'
    elif study_type_selection == "Observational Studies":
        study_type_query_segment = '("observational study"[Publication Type] OR "cohort study"[All Fields] OR "case-control study"[All Fields])'

    # Continue with existing PubMed search logic...
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
        
        description_keyword_display = keyword_stage_term[:100] + "..." if len(keyword_stage_term) > 100 else keyword_stage_term
        processed_query_description_parts.append(f"Term: '{description_keyword_display}'")
        if i == 0 and study_type_query_segment:
             processed_query_description_parts.append(f"Study Filter: {study_type_selection}")

        esearch_params = {
            "db": "pubmed",
            "retmax": str(max_results * 5 if i < len(search_stages_keywords) - 1 else max_results),
            "usehistory": "y", "retmode": "json",
            "tool": "streamlit_app_pubmed_finder_mesh", "email": EMAIL_FOR_NCBI
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
                return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (No results at this step)", expansion_summaries
            final_id_list = stage_id_list
            current_webenv = esearch_data.get("esearchresult", {}).get("webenv")
            current_query_key = esearch_data.get("esearchresult", {}).get("querykey")
            if not current_webenv or not current_query_key:
                return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (Error retrieving history)", expansion_summaries
            
            # Add small delay to respect API rate limits
            time.sleep(0.1)
            
        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP error ({http_err.response.status_code if http_err.response else 'N/A'}) at PubMed stage {i+1}"
            if hasattr(http_err, 'response') and http_err.response is not None and http_err.response.status_code == 429: 
                error_message += " (Too Many Requests)"
            return [], f"PubMed: {' -> '.join(processed_query_description_parts)} -> {error_message}", expansion_summaries
        except Exception as e:
            return [], f"PubMed: {' -> '.join(processed_query_description_parts)} -> Error at stage {i+1}: {str(e)}", expansion_summaries

    if not final_id_list:
        return [], f"PubMed: {' -> '.join(processed_query_description_parts)} (No results after all stages)", expansion_summaries

    final_id_list_for_efetch = final_id_list[:max_results]
    
    efetch_params = {
        "db": "pubmed", "retmode": "xml", "rettype": "abstract",
        "id": ",".join(final_id_list_for_efetch),
        "tool": "streamlit_app_pubmed_finder_mesh", "email": EMAIL_FOR_NCBI
    }
    if NCBI_API_KEY: efetch_params["api_key"] = NCBI_API_KEY

    pubmed_results_list = []
    try:
        summary_response = requests.get(f"{base_url}efetch.fcgi", params=efetch_params, timeout=25)
        summary_response.raise_for_status()
        articles_dict = xmltodict.parse(summary_response.content)
        pubmed_articles_container = articles_dict.get("PubmedArticleSet", {})
        if not pubmed_articles_container:
             return [], f"PubMed Fetch Details: {' -> '.join(processed_query_description_parts)} (No PubmedArticleSet)", expansion_summaries
        articles_list_xml = pubmed_articles_container.get("PubmedArticle", [])
        if not isinstance(articles_list_xml, list): articles_list_xml = [articles_list_xml] if articles_list_xml else []
        if not articles_list_xml:
            return [], f"PubMed Fetch Details: {' -> '.join(processed_query_description_parts)} (No article details)", expansion_summaries

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
        return pubmed_results_list, f"PubMed: {' -> '.join(processed_query_description_parts)} (Fetched {len(pubmed_results_list)} details)", expansion_summaries
    except Exception as e:
        return [], f"PubMed Fetch Details Error: {' -> '.join(processed_query_description_parts)} -> {str(e)}", expansion_summaries

# --- UPDATED: Enhanced ClinicalTrials Function with MeSH Expansion ---

def fetch_clinicaltrials_results_with_mesh(
    disease_input,    
    outcome_input,    
    population_input, 
    std_age_adv=None, 
    location_country_adv=None, 
    gender_adv=None,  
    study_type_from_sidebar=None, 
    masking_type_post_filter=None,
    intervention_model_post_filter=None,
    max_results=10,
    enable_mesh_expansion=True  # NEW parameter
):
    """
    Enhanced ClinicalTrials.gov search with optional MeSH term expansion
    """
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    params = {
        "format": "json",
        "pageSize": str(max_results * 2),
    }
    
    expansion_summaries = []
    
    # 1. Handle population input with optional MeSH expansion for query.term
    if population_input and population_input.strip():
        if enable_mesh_expansion:
            expanded_population_terms, population_summary = expand_search_terms_with_mesh(population_input.strip())
            # For ClinicalTrials.gov, we join terms with spaces (it handles OR logic internally)
            population_query = " ".join(expanded_population_terms)
            expansion_summaries.append(f"Population: {population_summary}")
        else:
            population_query = population_input.strip()
        params["query.term"] = population_query

    # 2. Handle disease input with optional MeSH expansion for query.cond
    if disease_input and disease_input.strip():
        if enable_mesh_expansion:
            expanded_disease_terms, disease_summary = expand_search_terms_with_mesh(disease_input.strip())
            # ClinicalTrials.gov condition field - join with spaces
            disease_query = " ".join(expanded_disease_terms)
            expansion_summaries.append(f"Disease: {disease_summary}")
        else:
            disease_query = disease_input.strip()
        params["query.cond"] = disease_query

    # 3. Handle outcome input with optional MeSH expansion for query.outc
    if outcome_input and outcome_input.strip():
        if enable_mesh_expansion:
            expanded_outcome_terms, outcome_summary = expand_search_terms_with_mesh(outcome_input.strip())
            # ClinicalTrials.gov outcome field - join with spaces
            outcome_query = " ".join(expanded_outcome_terms)
            expansion_summaries.append(f"Outcome: {outcome_summary}")
        else:
            outcome_query = outcome_input.strip()
        params["query.outc"] = outcome_query

    # Display expansion information for ClinicalTrials.gov
    if expansion_summaries:
        st.info("ClinicalTrials.gov MeSH Expansion Applied:\n" + "\n".join(expansion_summaries))

    # Study Type (Interventional or Observational based on sidebar)
    if study_type_from_sidebar == "Clinical Trials":
        params["filter.advanced"] = "AREA[StudyType]INTERVENTIONAL"
    elif study_type_from_sidebar == "Observational Studies":
        params["filter.advanced"] = "AREA[StudyType]OBSERVATIONAL"

    # Overall Status: "No longer looking for participants"
    no_longer_recruiting_statuses = [
        "COMPLETED", "TERMINATED", "WITHDRAWN", 
        "ACTIVE_NOT_RECRUITING", "SUSPENDED"
    ]
    params["filter.overallStatus"] = ",".join(no_longer_recruiting_statuses)
    
    # Advanced Filters from user input (unchanged)
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

    st.info(f"ClinicalTrials.gov API Request Params: {json.dumps(params, indent=2)}")

    # Continue with existing ClinicalTrials.gov logic...
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

        # --- Post-fetch filtering (unchanged from your original) ---
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

# --- UPDATED: Enhanced Streamlit UI ---

def main():
    st.set_page_config(layout="wide")
    st.title("RAG-Ready Medical Research Finder with MeSH Expansion")
    st.markdown("Finds **PubMed Central articles** and **Clinical Trial records** with optional **MeSH vocabulary expansion** for comprehensive search results.")

    st.sidebar.header("Search Parameters")
    
    # MeSH Expansion Toggle
    enable_mesh = st.sidebar.checkbox("Enable MeSH Term Expansion", value=True, help="Automatically expand search terms using Medical Subject Headings (MeSH) vocabulary")
    
    # Main inputs
    disease_input_ui = st.sidebar.text_input("Disease/Condition", placeholder="e.g., Type 2 Diabetes")
    outcome_input_ui = st.sidebar.text_input("Outcome of Interest", placeholder="e.g., blood glucose control")
    population_input_ui = st.sidebar.text_input("Target Population", placeholder="e.g., elderly patients")

    study_type_ui = st.sidebar.selectbox(
        "Study Type",
        ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"],
        index=0
    )
    max_results_per_source = st.sidebar.slider("Max results per source", 5, 50, 10)

    # MeSH Expansion Settings
    if enable_mesh:
        with st.sidebar.expander("MeSH Expansion Settings", expanded=False):
            max_mesh_terms = st.slider("Max MeSH terms per search term", 1, 10, 5)
            max_synonyms = st.slider("Max synonyms per MeSH term", 1, 5, 3)
    
    # [Keep your existing advanced filters and other UI elements...]
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
    
    # API Key status
    if NCBI_API_KEY: 
        st.sidebar.success("NCBI API Key loaded.")
    else: 
        st.sidebar.warning("NCBI API Key not loaded. MeSH expansion may be rate-limited.")

    # Search button
    if st.sidebar.button("Search"):
        if not (disease_input_ui or outcome_input_ui or population_input_ui):
            st.error("Please fill in at least one search field.")
        else:
            # --- PubMed Search with MeSH ---
            st.header("PubMed / PubMed Central Results")
            pubmed_status_message = st.empty()
            
            with st.spinner("Performing PubMed search with MeSH expansion..."):
                pubmed_status_message.info("Expanding search terms using MeSH vocabulary..." if enable_mesh else "Searching PubMed...")
                
                pubmed_results, pubmed_query_description, expansion_info = fetch_pubmed_results_with_mesh(
                    disease_input_ui, outcome_input_ui, population_input_ui, 
                    study_type_ui, max_results_per_source, enable_mesh
                )
            
            pubmed_status_message.info(f"PubMed Strategy: {pubmed_query_description}")
                
            if pubmed_results:
                st.write(f"Found {len(pubmed_results)} PubMed/PMC items:")
                for res in pubmed_results:
                    if res.get("is_rag_candidate"):
                        st.markdown(f"✅ **[{res['title']}]({res['link']})** - *{res['source_type']}* (RAG-ready)")
                    else:
                        st.markdown(f"⚠️ **[{res['title']}]({res['link']})** - *{res['source_type']}* (Abstract only)")
                    st.divider()
            else:
                st.write("No results found from PubMed.")
            
            # [Add your existing ClinicalTrials search here...]
            
            st.success("Search complete.")
    else:
        st.info("Enter search parameters in the sidebar and click 'Search'.")
        
        # MeSH Preview Feature
        if enable_mesh:
            st.subheader("MeSH Term Preview")
            preview_term = st.text_input("Preview MeSH expansion for a term:", placeholder="Enter a medical term to see MeSH expansion")
            if preview_term:
                with st.spinner("Fetching MeSH terms..."):
                    expanded_terms, summary = expand_search_terms_with_mesh(preview_term)
                st.write(f"**Expansion for '{preview_term}':**")
                st.write(f"**Summary:** {summary}")
                st.write(f"**Expanded terms:** {', '.join(expanded_terms)}")

if __name__ == "__main__":
    main()
