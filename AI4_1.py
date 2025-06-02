import streamlit as st
import requests
import xmltodict # For parsing NCBI XML
import json # For parsing ClinicalTrials.gov JSON

# --- Configuration ---
NCBI_API_KEY = None # Replace with your NCBI API key if you have one, otherwise None
EMAIL_FOR_NCBI = "your_email@example.com" # NCBI recommends providing an email

# --- Helper Functions for Query Construction (Revised for API specifics) ---
def construct_pubmed_query(disease, outcome, population, study_type_selection):
    query_parts = []
    if disease:
        # Using [MeSH Terms] for more specific disease search, falling back to [All Fields]
        query_parts.append(f'("{disease}"[MeSH Terms] OR "{disease}"[All Fields])')
    if outcome:
        query_parts.append(f'"{outcome}"[All Fields]')
    if population:
        query_parts.append(f'"{population}"[All Fields]')

    if study_type_selection == "Clinical Trials":
        query_parts.append('("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type])')
    elif study_type_selection == "Observational Studies":
        query_parts.append('("observational study"[Publication Type] OR "cohort study"[All Fields] OR "case-control study"[All Fields])')
    
    # Adding terms that often correlate with open access, though PMCID is the main check later
    # query_parts.append('("open access"[All Fields] OR "free full text"[All Fields] OR "PMC free full text"[All Fields])')
    # The above line can make queries too restrictive if PMCID is the primary goal.
    # We will filter by PMCID presence later.

    return " AND ".join(filter(None, query_parts))


def construct_clinicaltrials_api_query(disease, outcome, population, study_type_selection):
    # ClinicalTrials.gov API v2 uses a more structured query or a general search expression.
    # We'll use a general search expression for simplicity here.
    terms = []
    if disease:
        terms.append(disease)
    if outcome:
        terms.append(outcome)
    if population:
        terms.append(population)

    study_type_term = ""
    if study_type_selection == "Clinical Trials":
        study_type_term = "Interventional" # API uses "Interventional" for clinical trials
    elif study_type_selection == "Observational Studies":
        study_type_term = "Observational"
    
    if study_type_term:
        terms.append(study_type_term)
        
    # Constructing a search expression. Example: "diabetes AND blood glucose AND elderly AND Interventional"
    return " ".join(filter(None, terms))


# --- Functions for Fetching Results from APIs ---

def fetch_pubmed_results(query, max_results=10):
    st.info(f"Searching PubMed with query: {query}")
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    # 1. ESearch: Get PMIDs
    esearch_params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "usehistory": "y",
        "retmode": "json",
        "tool": "streamlit_app", # Good practice
        "email": EMAIL_FOR_NCBI   # Good practice
    }
    if NCBI_API_KEY:
        esearch_params["api_key"] = NCBI_API_KEY

    pubmed_results = []
    try:
        response = requests.get(f"{base_url}esearch.fcgi", params=esearch_params, timeout=10)
        response.raise_for_status()
        esearch_data = response.json()
        
        id_list = esearch_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            st.write("No PMIDs found for the query.")
            return []

        webenv = esearch_data.get("esearchresult", {}).get("webenv")
        query_key = esearch_data.get("esearchresult", {}).get("querykey")

        # 2. ESummary or EFetch: Get details for PMIDs
        # ESummary is lighter if we only need title, authors, journal, and PMCID link
        efetch_params = {
            "db": "pubmed",
            "retmode": "xml", # XML is often more detailed for article IDs like PMCID
            "rettype": "abstract", # Or 'medline' for more structured data
            "id": ",".join(id_list),
            "tool": "streamlit_app",
            "email": EMAIL_FOR_NCBI
        }
        # If using history from esearch:
        # efetch_params = {
        #     "db": "pubmed", "query_key": query_key, "WebEnv": webenv,
        #     "retmode": "xml", "rettype": "abstract", "retstart": "0", "retmax": str(len(id_list)),
        #     "tool": "streamlit_app", "email": EMAIL_FOR_NCBI
        # }
        if NCBI_API_KEY:
            efetch_params["api_key"] = NCBI_API_KEY

        summary_response = requests.get(f"{base_url}efetch.fcgi", params=efetch_params, timeout=15)
        summary_response.raise_for_status()
        
        # Parse XML
        articles_dict = xmltodict.parse(summary_response.content)
        
        for article_data in articles_dict.get("PubmedArticleSet", {}).get("PubmedArticle", []):
            # Ensure article_data is a dict, as xmltodict might return a list of one item
            if not isinstance(article_data, dict): 
                continue

            medline_citation = article_data.get("MedlineCitation", {})
            article_info = medline_citation.get("Article", {})
            pmid = medline_citation.get("PMID", {}).get("#text", "N/A")
            
            title = article_info.get("ArticleTitle", "No title available")
            if isinstance(title, dict): # Handle cases where title might have tags
                title = title.get("#text", "No title available")

            abstract_text_parts = []
            abstract = article_info.get("Abstract", {}).get("AbstractText")
            if abstract:
                if isinstance(abstract, list): # Handle structured abstracts
                    for part in abstract:
                        if isinstance(part, dict) and '#text' in part:
                            abstract_text_parts.append(part['#text'])
                        elif isinstance(part, str):
                            abstract_text_parts.append(part)
                elif isinstance(abstract, dict) and '#text' in abstract:
                     abstract_text_parts.append(abstract['#text'])
                elif isinstance(abstract, str):
                    abstract_text_parts.append(abstract)
            
            snippet = " ".join(abstract_text_parts)[:300] + "..." if abstract_text_parts else "No abstract available."

            pubmed_link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            pmc_link = None
            
            # Check for PMCID for PubMed Central link
            pubmed_data = article_data.get("PubmedData", {})
            if pubmed_data:
                article_id_list = pubmed_data.get("ArticleIdList", {}).get("ArticleId", [])
                if not isinstance(article_id_list, list): # If only one ID, it's not a list
                    article_id_list = [article_id_list]
                
                for aid in article_id_list:
                    if isinstance(aid, dict) and aid.get("@IdType") == "pmc":
                        pmcid = aid.get("#text")
                        if pmcid:
                            pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
                            break
            
            access_type = "Open Access (via PMC)" if pmc_link else "Check PubMed Link for Access"
            if pmc_link: # Prioritize PMC links for RAG
                 pubmed_results.append({
                    "title": title,
                    "link": pmc_link, # Use PMC link if available
                    "pubmed_url": pubmed_link,
                    "snippet": snippet,
                    "access": access_type,
                    "source": "PubMed Central"
                })
            else:
                pubmed_results.append({
                    "title": title,
                    "link": pubmed_link,
                    "snippet": snippet,
                    "access": access_type,
                    "source": "PubMed"
                })

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching from PubMed: {e}")
    except json.JSONDecodeError as e:
        st.error(f"Error decoding PubMed JSON response: {e}")
    except Exception as e:
        st.error(f"An unexpected error occurred with PubMed: {e}")
        st.error(f"Problematic XML content: {summary_response.text[:500] if 'summary_response' in locals() else 'N/A'}")


    return pubmed_results


def fetch_clinicaltrials_results(query, max_results=10):
    st.info(f"Searching ClinicalTrials.gov with query: {query}")
    # Using API v2
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": query,
        "pageSize": str(max_results),
        "format": "json"
        # You can add more filters like "filter.overallStatus": "RECRUITING"
    }
    ct_results = []
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        studies = data.get("studies", [])
        if not studies:
            st.write("No clinical trials found for the query.")
            return []

        for study in studies:
            protocol = study.get("protocolSection", {})
            identification_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            description_module = protocol.get("descriptionModule", {})
            
            nct_id = identification_module.get("nctId", "N/A")
            title = identification_module.get("officialTitle")
            if not title: # Fallback to brief title
                title = identification_module.get("briefTitle", "No title available")

            status = status_module.get("overallStatus", "N/A")
            summary = description_module.get("briefSummary", "No summary available.")
            if not summary and description_module.get("detailedDescription"): # Fallback
                summary = description_module.get("detailedDescription")[:300] + "..."

            link = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id != "N/A" else "#"
            
            ct_results.append({
                "title": title,
                "link": link,
                "nct_id": nct_id,
                "status": status,
                "summary": summary,
                "source": "ClinicalTrials.gov"
            })
            
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching from ClinicalTrials.gov: {e}")
    except json.JSONDecodeError as e: # Changed from ValueError to json.JSONDecodeError
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

# --- Streamlit App UI ---
st.set_page_config(layout="wide")
st.title("Medical Research Paper & Trial Finder")
st.markdown("""
This app searches PubMed and ClinicalTrials.gov to find research papers and clinical trials.
It prioritizes links to PubMed Central (PMC) for articles, as these are generally open access.
**Note:** This tool *finds potential sources*. The next step for a RAG pipeline would be to download and process the content from these links.
""")

st.sidebar.header("Search Parameters")
target_population = st.sidebar.text_input("Target Population", "e.g., elderly patients with diabetes")
disease = st.sidebar.text_input("Disease/Condition", "e.g., Type 2 Diabetes")
outcome_of_interest = st.sidebar.text_input("Outcome of Interest", "e.g., blood glucose control")
study_type = st.sidebar.selectbox(
    "Study Type",
    ["Clinical Trials", "Observational Studies", "All Study Types (PubMed only)"], # CT.gov needs specific study type
    index=0
)
max_results_per_source = st.sidebar.slider("Max results per source", 5, 25, 10)


if st.sidebar.button("Search"):
    if not disease: # Disease is a primary search term for both
        st.error("Please fill in at least the Disease/Condition.")
    else:
        # --- PubMed Search ---
        st.header("PubMed / PubMed Central Results")
        pubmed_query_string = construct_pubmed_query(disease, outcome_of_interest, target_population, study_type)
        st.write("**PubMed Query:**")
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
                    if res['source'] == "PubMed Central" and 'pubmed_url' in res:
                        st.caption(f"Original PubMed Abstract: [{res['pubmed_url']}]({res['pubmed_url']})")
                    st.write(f"_{res.get('snippet', 'No snippet available.')}_")
                with col2:
                    st.markdown(f"**Access:**\n[{res['access']}]({res['link']})")
                st.divider()
        else:
            st.write("No results found from PubMed/PMC for this query.")
        st.markdown("---")

        # --- ClinicalTrials.gov Search ---
        st.header("ClinicalTrials.gov Results")
        # For ClinicalTrials.gov, "All Study Types" is not a direct API filter,
        # so we might need to adjust or run separate queries if that's a hard requirement.
        # For now, if "All Study Types" is selected, we might default to "Interventional" or skip.
        # Or, the user should select a specific type for CT.gov.
        
        ct_study_type_for_query = study_type
        if study_type == "All Study Types (PubMed only)":
            st.info("For ClinicalTrials.gov, please select 'Clinical Trials' or 'Observational Studies' for more targeted results. Defaulting to searching broadly.")
            # A broad search without study type filter, or you could default to 'Interventional'
            ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, "")
        else:
            ct_api_query_string = construct_clinicaltrials_api_query(disease, outcome_of_interest, target_population, study_type)

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
            st.write("No results found from ClinicalTrials.gov for this query.")
        
        st.markdown("---")
        st.success("Search complete. Review the links above. Prioritize PubMed Central (PMC) links for open access articles suitable for a RAG pipeline.")

else:
    st.info("Enter search parameters in the sidebar and click 'Search'.")

st.sidebar.markdown("---")
st.sidebar.header("Other Free Medical Research Databases")
for db in OTHER_DATABASES:
    st.sidebar.markdown(f"[{db['name']}]({db['url']})")

st.sidebar.markdown("---")
st.sidebar.caption("Remember to respect API terms of service and rate limits.")
