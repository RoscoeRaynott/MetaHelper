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
def fetch_pubmed_results(disease, outcome, population, study_type_selection, max_results=10):
    search_stages_keywords = []
    if disease and disease.strip(): search_stages_keywords.append(disease.strip())
    if outcome and outcome.strip(): search_stages_keywords.append(outcome.strip())
    if population and population.strip(): search_stages_keywords.append(population.strip())

    if not search_stages_keywords:
        st.warning("No primary search terms (disease, outcome, population) provided for PubMed.")
        return [], "No search terms provided."

    study_type_query_segment = ""
    if study_type_selection == "Clinical Trials":
        study_type_query_segment = '("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type])'
    elif study_type_selection == "Observational Studies":
        study_type_query_segment = '("observational study"[Publication Type] OR "cohort study"[All Fields] OR "case-control study"[All Fields])'

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    current_webenv = None
    current_query_key = None
    final_id_list = []
    processed_query_description = []

    for i, keyword_stage_term in enumerate(search_stages_keywords):
        current_stage_search_query = ""
        if study_type_query_segment:
            current_stage_search_query = f"{keyword_stage_term} AND ({study_type_query_segment})"
        else:
            current_stage_search_query = keyword_stage_term
        
        description_keyword_display = keyword_stage_term
        processed_query_description.append(f"Step {i+1} Term: '{description_keyword_display}'")
        if i == 0 and study_type_query_segment:
             processed_query_description.append(f"Applied Study Filter: {study_type_selection}")

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
        
        st.info(f"PubMed Search - Stage {i+1}: Processing with '{description_keyword_display}'")
        try:
            response = requests.get(f"{base_url}esearch.fcgi", params=esearch_params, timeout=20)
            response.raise_for_status()
            esearch_data = response.json()
            stage_id_list = esearch_data.get("esearchresult", {}).get("idlist", [])
            if not stage_id_list:
                st.warning(f"No PubMed results found after applying term: '{description_keyword_display}'. Sequential search stopped.")
                return [], " -> ".join(processed_query_description) + " (No results at this step)"
            final_id_list = stage_id_list
            current_webenv = esearch_data.get("esearchresult", {}).get("webenv")
            current_query_key = esearch_data.get("esearchresult", {}).get("querykey")
            if not current_webenv or not current_query_key:
                st.error("Error in PubMed search: Could not retrieve WebEnv/QueryKey for sequential search.")
                return [], " -> ".join(processed_query_description) + " (Error in history)"
        except requests.exceptions.HTTPError as http_err:
            st.error(f"HTTP error occurred while fetching from PubMed: {http_err} - URL: {http_err.request.url}")
            if http_err.response.status_code == 429: st.error("This is a 'Too Many Requests' error. Please wait a few minutes and try again, or use an NCBI API key.")
            return [], " -> ".join(processed_query_description) + f" (HTTP Error)"
        except requests.exceptions.Timeout:
            st.error("PubMed request timed out.")
            return [], " -> ".join(processed_query_description) + " (Timeout)"
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching from PubMed: {e}")
            return [], " -> ".join(processed_query_description) + " (Request Error)"
        except json.JSONDecodeError as e:
            st.error(f"Error decoding PubMed JSON response: {e}")
            return [], " -> ".join(processed_query_description) + " (JSON Error)"
        except Exception as e:
            st.error(f"An unexpected error occurred with PubMed stage search: {e}")
            return [], " -> ".join(processed_query_description) + f" (Unexpected Error)"

    if not final_id_list:
        st.warning("No PMIDs remained after all sequential PubMed search stages.")
        return [], " -> ".join(processed_query_description) + " (No results after all stages)"

    final_id_list_for_efetch = final_id_list[:max_results]
    st.info(f"Fetching details for {len(final_id_list_for_efetch)} refined PubMed results...")
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
             st.warning("PubMed efetch response structure unexpected (No PubmedArticleSet).")
             return [], " -> ".join(processed_query_description)
        articles_list_xml = pubmed_articles_container.get("PubmedArticle", [])
        if not isinstance(articles_list_xml, list): articles_list_xml = [articles_list_xml] if articles_list_xml else []
        if not articles_list_xml:
            st.warning("No article details found in PubMed efetch response.")
            return [], " -> ".join(processed_query_description)
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
            abstract_text_parts = []
            abstract_section = article_info.get("Abstract", {})
            if abstract_section:
                abstract_texts = abstract_section.get("AbstractText")
                if abstract_texts:
                    if isinstance(abstract_texts, list):
                        for part in abstract_texts:
                            if isinstance(part, dict) and '#text' in part: abstract_text_parts.append(part['#text'])
                            elif isinstance(part, str): abstract_text_parts.append(part)
                    elif isinstance(abstract_texts, dict) and '#text' in abstract_texts: abstract_text_parts.append(abstract_texts['#text'])
                    elif isinstance(abstract_texts, str): abstract_text_parts.append(abstract_texts)
            snippet = (" ".join(abstract_text_parts)[:300] + "...") if abstract_text_parts else "No abstract available."
            pubmed_link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid != "N/A" else "#"
            pmc_link = None
            pubmed_data = article_data.get("PubmedData", {})
            if pubmed_data:
                article_id_list_xml = pubmed_data.get("ArticleIdList", {}).get("ArticleId", [])
                if not isinstance(article_id_list_xml, list): article_id_list_xml = [article_id_list_xml]
                for aid in article_id_list_xml:
                    if isinstance(aid, dict) and aid.get("@IdType") == "pmc":
                        pmcid = aid.get("#text")
                        if pmcid: pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"; break
            access_type = "Open Access (via PMC)" if pmc_link else "Check PubMed Link for Access"
            result_item = {"title": title, "link": pmc_link if pmc_link else pubmed_link, "pubmed_url": pubmed_link, "snippet": snippet, "access": access_type, "source": "PubMed Central" if pmc_link else "PubMed"}
            if pmc_link: result_item["pmc_link"] = pmc_link
            pubmed_results_list.append(result_item)
        return pubmed_results_list, " -> ".join(processed_query_description)
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error during PubMed efetch: {http_err}")
        return [], " -> ".join(processed_query_description) + " (HTTP Error in efetch)"
    except requests.exceptions.Timeout:
        st.error("PubMed efetch request timed out.")
        return [], " -> ".join(processed_query_description) + " (Timeout in efetch)"
    except requests.exceptions.RequestException as e:
        st.error(f"Error during PubMed efetch: {e}")
        return [], " -> ".join(processed_query_description) + " (Request Error in efetch)"
    except json.JSONDecodeError as e: # Though efetch uses XML, if something weird happens
        st.error(f"Error decoding PubMed efetch (unexpected JSON error): {e}")
        return [], " -> ".join(processed_query_description) + " (JSON Error in efetch)"
    except Exception as e:
        st.error(f"Unexpected error during PubMed efetch processing: {e}")
        return [], " -> ".join(processed_query_description) + " (Efetch processing error)"

# THIS IS THE FUNCTION THAT WAS LIKELY MISSING/INCOMPLETE
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
        response.raise_for_status() # Raises HTTPError for bad requests (4XX or 5XX)
        data = response.json()
        studies = data.get("studies", [])
        if not studies:
            st.warning("No clinical trials found for the query. Try broadening your search terms.")
            return []
        for study_container in studies:
            study = study_container.get("protocolSection", {})
            if not study: continue # Should not happen with valid API response
            identification_module = study.get("identificationModule", {})
            status_module = study.get("statusModule", {})
            description_module = study.get("descriptionModule", {})
            
            nct_id = identification_module.get("nctId", "N/A")
            title = identification_module.get("officialTitle") or identification_module.get("briefTitle", "No title available")

            status = status_module.get("overallStatus", "N/A")
            summary = description_module.get("briefSummary", "")
            if not summary and description_module.get("detailedDescription"): # Fallback to detailed description
                summary = description_module.get("detailedDescription")[:300] + "..."
            if not summary: summary = "No summary available." # Ensure summary is not None

            link = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            ct_results.append({
                "title": title, "link": link, "nct_id": nct_id,
                "status": status, "summary": summary, "source": "ClinicalTrials.gov"
            })
    # Corrected 'except' block that was mentioned in the traceback
    except requests.exceptions.HTTPError as http_err:                   
        st.error(f"HTTP error occurred while fetching from ClinicalTrials.gov: {http_err}")
    except requests.exceptions.Timeout:                                 
        st.error("ClinicalTrials.gov request timed out.")               
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching from ClinicalTrials.gov: {e}")
    except json.JSONDecodeError as e:
        st.error(f"Error decoding ClinicalTrials.gov JSON response: {e}")
    except Exception as e: # Catch other unexpected errors
        st.error(f"An unexpected error occurred with ClinicalTrials.gov: {e}")
    return ct_results


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
st.title("Medical Research Paper & Trial Finder")
st.markdown("Sequential PubMed search: Terms (Disease, Outcome, Population) are applied one by one, **without added quotes around them**. Study type filter applied at each step.")

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

if NCBI_API_KEY: st.sidebar.success("NCBI API Key loaded.")
else: st.sidebar.warning("NCBI API Key not loaded. Using lower rate limits.")
if EMAIL_FOR_NCBI == "your_default_email@example.com" or not EMAIL_FOR_NCBI:
     st.sidebar.error("NCBI Email not set in secrets. Please update .streamlit/secrets.toml")
else: st.sidebar.info(f"Email for NCBI: {EMAIL_FOR_NCBI}")

if st.sidebar.button("Search"):
    if not (disease or outcome_of_interest or target_population):
        st.error("Please fill in at least one of: Disease, Outcome, or Population.")
    else:
        st.header("PubMed / PubMed Central Results (Sequential Search)")
        with st.spinner(f"Performing sequential PubMed search..."):
            pubmed_results, pubmed_query_description = fetch_pubmed_results(
                disease, outcome_of_interest, target_population, study_type, max_results_per_source
            )
        
        st.write("**PubMed Search Strategy Performed:**")
        st.info(pubmed_query_description if pubmed_query_description else "No PubMed search performed or terms provided.")
            
        if pubmed_results:
            st.write(f"Found {len(pubmed_results)} results from PubMed/PMC after sequential filtering:")
            for res in pubmed_results:
                col1, col2 = st.columns([3,1])
                with col1:
                    st.markdown(f"**[{res['title']}]({res['link']})**")
                    st.caption(f"Source: {res['source']}")
                    if res['source'] == "PubMed Central" and 'pubmed_url' in res and res['link'] != res['pubmed_url']:
                        st.caption(f"Original PubMed Abstract: [{res['pubmed_url']}]({res['pubmed_url']})")
                    st.write(f"_{res.get('snippet', 'No snippet available.')}_")
                with col2:
                    st.markdown(f"**Access:**"); st.markdown(f"[{res['access']}]({res['link']})")
                st.divider()
        st.markdown("---")

        st.header("ClinicalTrials.gov Results")
        ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, study_type)
        if ct_api_query_string:
            st.write("**ClinicalTrials.gov API Query (Keywords):**")
            st.code(ct_api_query_string, language="text")
            with st.spinner(f"Searching ClinicalTrials.gov..."):
                # This is the call to fetch_clinicaltrials_results
                ct_results = fetch_clinicaltrials_results(ct_api_query_string, max_results_per_source)
            if ct_results:
                st.write(f"Found {len(ct_results)} results from ClinicalTrials.gov:")
                for res in ct_results:
                    st.markdown(f"**[{res['title']}]({res['link']})**")
                    st.caption(f"NCT ID: {res['nct_id']} | Status: {res['status']}")
                    st.write(f"_{res.get('summary', 'No summary available.')}_")
                    st.divider()
        else: st.warning("Could not construct a valid ClinicalTrials.gov query.")
        st.markdown("---")
        st.success("Search complete.")
else:
    st.info("Enter search parameters in the sidebar and click 'Search'.")

st.sidebar.markdown("---")
st.sidebar.header("Other Free Medical Research Databases")
for db in OTHER_DATABASES: st.sidebar.markdown(f"[{db['name']}]({db['url']})")
st.sidebar.markdown("---")
st.sidebar.caption(f"Remember to respect API terms of service.")
