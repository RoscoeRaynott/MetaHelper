# data_ingestor.py (API Version)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

# --- 1. PMC API Fetching Logic ---

def fetch_pmc_xml(pmc_id):
    """
    Fetches the full text XML of a paper from PubMed Central using the NCBI API.
    """
    api_key = st.secrets.get("NCBI_API_KEY")
    email = st.secrets.get("EMAIL_FOR_NCBI", "your_email@example.com")
    
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pmc",
        "id": pmc_id,
        "retmode": "xml",
        "tool": "streamlit_app_rag",
        "email": email
    }
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(base_url, params=params, timeout=25)
        response.raise_for_status()
        return response.content # Return bytes for XML parsing
    except requests.exceptions.RequestException as e:
        print(f"PMC API Error for {pmc_id}: {e}")
        return None

def _xml_table_to_markdown(table_wrap_tag):
    """
    Converts a PMC XML table wrapper into a Markdown-formatted string.
    """
    output = []
    
    # Get Caption/Label
    label = table_wrap_tag.find('label')
    caption = table_wrap_tag.find('caption')
    
    title_text = ""
    if label: title_text += label.get_text(strip=True) + " "
    if caption: title_text += caption.get_text(strip=True)
    
    if title_text:
        output.append(f"\n**Table: {title_text}**\n")

    # Parse Table Body
    table = table_wrap_tag.find('table')
    if not table: return ""

    # Handle headers
    thead = table.find('thead')
    if thead:
        rows = thead.find_all('tr')
        for row in rows:
            cells = row.find_all(['th', 'td'])
            row_text = " | ".join(cell.get_text(strip=True) for cell in cells)
            output.append(f"| {row_text} |")
        # Add separator
        if rows:
            output.append("|---" * len(rows[0].find_all(['th', 'td'])) + "|")

    # Handle body
    tbody = table.find('tbody')
    rows = tbody.find_all('tr') if tbody else table.find_all('tr')

    for row in rows:
        cells = row.find_all(['th', 'td'])
        row_text = " | ".join(cell.get_text(strip=True) for cell in cells)
        output.append(f"| {row_text} |")
    
    return "\n".join(output) + "\n\n"

def parse_pmc_xml(xml_content):
    """
    Parses the PMC XML to extract sections and tables.
    Returns a list of (section_title, section_text) tuples.
    """
    if not xml_content: return [], "No content."
    
    # Use 'xml' parser (requires lxml in requirements.txt)
    soup = BeautifulSoup(xml_content, 'xml')
    sections_data = []

    # --- Title ---
    article_title = soup.find('article-title')
    title_text = article_title.get_text(strip=True) if article_title else "No Title Found"
    sections_data.append(("Title", title_text))

    # --- Abstract ---
    abstract = soup.find('abstract')
    if abstract:
        sections_data.append(("Abstract", abstract.get_text(separator='\n\n', strip=True)))

    # --- Body Sections ---
    body = soup.find('body')
    if body:
        # PMC XML organizes content into <sec> tags
        for sec in body.find_all('sec', recursive=False):
            title_tag = sec.find('title')
            sec_title = title_tag.get_text(strip=True) if title_tag else "Untitled Section"
            
            # Normalize titles
            lower_title = sec_title.lower()
            if "method" in lower_title: sec_title = "Methods"
            elif "result" in lower_title: sec_title = "Results"
            elif "discussion" in lower_title or "conclusion" in lower_title: sec_title = "Conclusion"
            elif "intro" in lower_title: sec_title = "Introduction"

            sec_content = ""
            
            # Iterate over children to preserve order of text and tables
            for child in sec.children:
                if child.name == 'p':
                    sec_content += child.get_text(strip=True) + "\n\n"
                elif child.name == 'table-wrap':
                    sec_content += _xml_table_to_markdown(child)
                elif child.name == 'sec':
                    # Handle subsections (flatten them)
                    sub_title = child.find('title')
                    if sub_title:
                        sec_content += f"\n### {sub_title.get_text(strip=True)}\n"
                    for sub_child in child.find_all(['p', 'table-wrap']):
                        if sub_child.name == 'p':
                            sec_content += sub_child.get_text(strip=True) + "\n\n"
                        elif sub_child.name == 'table-wrap':
                            sec_content += _xml_table_to_markdown(sub_child)

            if sec_content.strip():
                sections_data.append((sec_title, sec_content.strip()))

    return sections_data, "Success" if len(sections_data) > 1 else "Warning: Only title/abstract parsed (Full text might not be Open Access)."


# --- 2. ClinicalTrials.gov Logic (UNCHANGED - KEEP YOUR EXISTING CODE HERE) ---

def parse_clinical_trial_record(nct_id):
    """
    Fetches and parses a ClinicalTrials.gov study and returns a list of (section, text) tuples.
    """
    if not nct_id: return [], "No NCT ID provided."
    api_url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        sections_data = []
        protocol = data.get('protocolSection', {})
        title = protocol.get('identificationModule', {}).get('officialTitle') or protocol.get('identificationModule', {}).get('briefTitle', 'No Title Found')
        sections_data.append(("Title", f"{title} (NCT ID: {nct_id})"))
        if protocol.get('statusModule', {}).get('overallStatus'): sections_data.append(("Status", protocol['statusModule']['overallStatus']))
        if protocol.get('descriptionModule', {}).get('briefSummary'): sections_data.append(("Summary", protocol['descriptionModule']['briefSummary']))
        if protocol.get('descriptionModule', {}).get('detailedDescription'): sections_data.append(("Detailed Description", protocol['descriptionModule']['detailedDescription']))
        if protocol.get('conditionsModule', {}).get('conditions'): sections_data.append(("Conditions", '\n'.join(protocol['conditionsModule']['conditions'])))
        if protocol.get('eligibilityModule', {}).get('eligibilityCriteria'): sections_data.append(("Eligibility Criteria", protocol['eligibilityModule']['eligibilityCriteria']))
        outcomes_module = protocol.get('outcomesModule', {})
        if outcomes_module:
            outcomes_text = ""
            primary = outcomes_module.get('primaryOutcomes', [])
            secondary = outcomes_module.get('secondaryOutcomes', [])
            if primary: outcomes_text += "Primary Outcomes:\n" + "\n".join([f"- {o.get('measure', 'N/A')}" for o in primary])
            if secondary: outcomes_text += "\nSecondary Outcomes:\n" + "\n".join([f"- {o.get('measure', 'N/A')}" for o in secondary])
            if outcomes_text: sections_data.append(("Outcomes", outcomes_text))
        if data.get('resultsSection'): sections_data.append(("Results", "Detailed results are available in the record's structured data."))
        return sections_data, "Success" if sections_data else "No content parsed."
    except Exception as e:
        print(f"API request failed for NCT ID {nct_id}: {e}")
        return [], f"API request failed: {str(e)}"

def get_ct_gov_table_titles_from_api(nct_id):
    """
    Fetches a full study record from the CT.gov API and returns a list of all
    table titles from the Baseline, Outcome, and Adverse Event sections.
    """
    api_url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()

        results_section = data.get('resultsSection', {})
        if not results_section:
            return None, "No Results Section found in the API data for this trial."

        all_titles = []

        # # 1. Baseline Characteristics
        # baseline_module = results_section.get('baselineCharacteristicsModule', {})
        # for measure in baseline_module.get('measures', []):
        #     if measure.get('title'):
        #         all_titles.append(f"[Baseline] {measure['title']}")

        # 2. Outcome Measures
        outcome_module = results_section.get('outcomeMeasuresModule', {})
        for measure in outcome_module.get('outcomeMeasures', []):
            if measure.get('title'):
                all_titles.append(f"[Outcome] {measure['title']}")
            
        # 3. Adverse Events
        adverse_module = results_section.get('adverseEventsModule', {})
        if adverse_module:
            if adverse_module.get('eventGroups'):
                all_titles.append(f"[Adverse] All-Cause Mortality")

            for event in adverse_module.get('seriousEvents', []):
                if event.get('term'):
                    all_titles.append(f"[Adverse-Serious] {event['term']}")

            for event in adverse_module.get('otherEvents', []):
                if event.get('term'):
                    all_titles.append(f"[Adverse-Other] {event['term']}")
                    
        if not all_titles:
            return [], "Results section was found, but it contains no data tables."

        return all_titles, "Successfully retrieved all table titles."

    except requests.exceptions.RequestException as e:
        return None, f"API request failed: {str(e)}"
    except (ValueError, KeyError) as e:
        return None, f"Failed to parse JSON or find a key: {str(e)}"

def extract_data_for_selected_titles(nct_id, selected_titles):
    """
    Fetches API data and extracts values for the specific titles identified by the LLM.
    """
    api_url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('resultsSection', {})
        if not results: return None, "No results section."

        extracted_results = {}

        for full_title in selected_titles:
            if "] " not in full_title: continue
            tag, clean_title = full_title.split("] ", 1)
            tag = tag + "]"
            
            findings = []

            # --- CASE 1: BASELINE CHARACTERISTICS ---
            if tag == "[Baseline]":
                module = results.get('baselineCharacteristicsModule', {})
                groups = module.get('groups', [])
                group_map = {g.get('id'): g.get('title', g.get('id')) for g in groups}
                
                measure = next((m for m in module.get('measures', []) if m.get('title') == clean_title), None)
                
                if measure:
                    for cls in measure.get('classes', []):
                        for cat in cls.get('categories', []):
                            for meas in cat.get('measurements', []):
                                gid = meas.get('groupId')
                                val = meas.get('value', 'N/A')
                                if meas.get('spread'): val += f" ({meas['spread']})"
                                
                                group_name = group_map.get(gid, gid)
                                findings.append(f"{group_name}: {val}")

            # --- CASE 2: OUTCOME MEASURES ---
            elif tag == "[Outcome]":
                module = results.get('outcomeMeasuresModule', {})
                measure = next((m for m in module.get('outcomeMeasures', []) if m.get('title') == clean_title), None)
                
                if measure:
                    groups = measure.get('groups', [])
                    group_map = {g.get('id'): g.get('title', g.get('id')) for g in groups}

                    for cls in measure.get('classes', []):
                        for cat in cls.get('categories', []):
                            for meas in cat.get('measurements', []):
                                gid = meas.get('groupId')
                                val = meas.get('value', 'N/A')
                                if meas.get('spread'): 
                                    val += f" ({meas['spread']})"
                                elif meas.get('lowerLimit') and meas.get('upperLimit'):
                                    val += f" ({meas['lowerLimit']} to {meas['upperLimit']})"
                                
                                group_name = group_map.get(gid, gid)
                                findings.append(f"{group_name}: {val}")

            # --- CASE 3: ADVERSE EVENTS ---
            elif tag.startswith("[Adverse"):
                module = results.get('adverseEventsModule', {})
                groups = module.get('eventGroups', [])
                group_map = {g.get('id'): g.get('title', g.get('id')) for g in groups}

                if "All-Cause Mortality" in clean_title:
                    for g in groups:
                        gid = g.get('id')
                        count = g.get('deathsNumAffected')
                        at_risk = g.get('deathsNumAtRisk')
                        if count is not None:
                            val = f"{count}/{at_risk}" if at_risk else f"{count}"
                            findings.append(f"{group_map.get(gid, gid)}: {val}")
                
                else:
                    event_list = module.get('seriousEvents', []) + module.get('otherEvents', [])
                    target_event = next((e for e in event_list if e.get('term') == clean_title), None)
                    
                    if target_event:
                        for stat in target_event.get('stats', []):
                            gid = stat.get('groupId')
                            count = stat.get('numAffected')
                            at_risk = stat.get('numAtRisk')
                            if count is not None:
                                val = f"{count}/{at_risk}" if at_risk else f"{count}"
                                group_name = group_map.get(gid, gid)
                                findings.append(f"{group_name}: {val}")

            if findings:
                extracted_results[full_title] = " | ".join(findings)
            else:
                extracted_results[full_title] = "Data not found"

        return extracted_results, "Extraction complete."

    except Exception as e:
        return None, f"API Error: {e}"

# --- 3. Main Controller (Updated) ---

def chunk_text(sections_data, chunk_size=1500, chunk_overlap=200):
    """Splits text from sections into chunks, each with metadata."""
    if not sections_data: return []
    all_chunks = []
    for section_title, section_text in sections_data:
        if not section_text.strip(): continue
        current_chunk = ""
        paragraphs = section_text.split('\n\n')
        for para in paragraphs:
            if not para.strip(): continue
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk: all_chunks.append({"text": current_chunk.strip(), "section": section_title})
                current_chunk = para + "\n\n"
        if current_chunk.strip(): all_chunks.append({"text": current_chunk.strip(), "section": section_title})
    return all_chunks

def process_single_link(url):
    """
    Main controller. Uses API for both PMC and CT.gov.
    """
    print(f"Processing link: {url}")
    sections_data = []
    status = ""
    
    # --- PMC Logic (Updated to use API) ---
    if "ncbi.nlm.nih.gov/pmc/articles" in url or "pmc.ncbi.nlm.nih.gov" in url:
        # Extract PMC ID (e.g., PMC12345678)
        pmc_match = re.search(r'(PMC\d+)', url)
        if pmc_match:
            pmc_id = pmc_match.group(1)
            xml_content = fetch_pmc_xml(pmc_id)
            if not xml_content:
                return None, f"Failed to fetch XML from API for {pmc_id}"
            sections_data, status = parse_pmc_xml(xml_content)
        else:
            return None, "Could not extract PMC ID from URL."

    # --- ClinicalTrials.gov Logic (Unchanged) ---
    elif "clinicaltrials.gov/study" in url:
        nct_match = re.search(r'NCT\d+', url)
        if not nct_match: return None, "Could not extract NCT ID."
        sections_data, status = parse_clinical_trial_record(nct_match.group(0))
        
    else:
        return None, "Unrecognized URL."

    if not sections_data:
        return None, status

    text_chunks_with_metadata = chunk_text(sections_data)
    
    # Reconstruct full text for display
    full_text_for_display = "\n\n".join([f"## {title}\n\n{text}" for title, text in sections_data])
    
    return full_text_for_display, text_chunks_with_metadata
