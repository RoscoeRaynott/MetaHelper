# data_ingestor.py (NEW VERSION)

import requests
from bs4 import BeautifulSoup
import re

def fetch_content_from_url(url):
    """Fetches the raw HTML content from a given URL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

def parse_pmc_article(html_content):
    """
    Parses HTML from a PubMed Central article using a robust, header-based approach.
    Returns a list of (section_title, section_text) tuples.
    """
    if not html_content:
        return [], "No HTML content provided."

    soup = BeautifulSoup(html_content, 'html.parser')
    sections_data = []

    # --- Title and Abstract (same as before, this part is reliable) ---
    title_tag = (soup.find('h1', class_='content-title') or soup.find('h1') or soup.find('title'))
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"
    sections_data.append(("Title", title))

    abstract_div = (soup.find('div', class_='abstract') or soup.find('div', id=re.compile('abstract.*', re.I)))
    if abstract_div:
        sections_data.append(("Abstract", abstract_div.get_text(separator='\n\n', strip=True)))

    # --- NEW, MORE ROBUST BODY PARSING ---
    body_div = (soup.find('div', class_='jig-ncbiinpagenav') or 
                soup.find('div', class_=re.compile('article.*', re.I)) or 
                soup.find('article'))
    
    if body_div:
        current_section_title = "Introduction" # Assume first section is intro if no header found
        current_section_text = ""
        
        # Find all header and paragraph tags in the order they appear
        for element in body_div.find_all(['h2', 'h3', 'p']):
            # If we find a new header, save the previous section and start a new one
            if element.name in ['h2', 'h3']:
                # Save the completed section if it has content
                if current_section_text.strip():
                    sections_data.append((current_section_title, current_section_text.strip()))
                
                # Start the new section
                current_section_title = element.get_text(strip=True)
                # Normalize common section titles
                if "method" in current_section_title.lower(): current_section_title = "Methods"
                elif "result" in current_section_title.lower(): current_section_title = "Results"
                elif "discussion" in current_section_title.lower() or "conclusion" in current_section_title.lower(): current_section_title = "Conclusion"
                
                current_section_text = "" # Reset the text buffer
            
            # If we find a paragraph, add its text to the current section
            elif element.name == 'p':
                current_section_text += element.get_text(strip=True) + "\n\n"
        
        # After the loop, save the last remaining section
        if current_section_text.strip():
            sections_data.append((current_section_title, current_section_text.strip()))

    return sections_data, "Success" if len(sections_data) > 2 else "Warning: Only title and abstract were parsed."
def parse_clinical_trial_record(nct_id):
    """
    Fetches and parses a ClinicalTrials.gov study and returns a list of (section, text) tuples.
    """
    if not nct_id:
        return [], "No NCT ID provided."

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

        if protocol.get('statusModule', {}).get('overallStatus'):
            sections_data.append(("Status", protocol['statusModule']['overallStatus']))
        if protocol.get('descriptionModule', {}).get('briefSummary'):
            sections_data.append(("Summary", protocol['descriptionModule']['briefSummary']))
        if protocol.get('descriptionModule', {}).get('detailedDescription'):
            sections_data.append(("Detailed Description", protocol['descriptionModule']['detailedDescription']))
        if protocol.get('conditionsModule', {}).get('conditions'):
            sections_data.append(("Conditions", '\n'.join(protocol['conditionsModule']['conditions'])))
        if protocol.get('eligibilityModule', {}).get('eligibilityCriteria'):
            sections_data.append(("Eligibility Criteria", protocol['eligibilityModule']['eligibilityCriteria']))
        
        outcomes_module = protocol.get('outcomesModule', {})
        if outcomes_module:
            outcomes_text = ""
            primary = outcomes_module.get('primaryOutcomes', [])
            secondary = outcomes_module.get('secondaryOutcomes', [])
            if primary:
                outcomes_text += "Primary Outcomes:\n" + "\n".join([f"- {o.get('measure', 'N/A')}" for o in primary])
            if secondary:
                outcomes_text += "\nSecondary Outcomes:\n" + "\n".join([f"- {o.get('measure', 'N/A')}" for o in secondary])
            if outcomes_text:
                sections_data.append(("Outcomes", outcomes_text))

        if data.get('resultsSection'):
            sections_data.append(("Results", "Detailed results are available in the record's structured data."))

        return sections_data, "Success" if sections_data else "No content parsed."

    except Exception as e:
        print(f"API request failed for NCT ID {nct_id}: {e}")
        return [], f"API request failed: {str(e)}"

def chunk_text(sections_data, chunk_size=1500, chunk_overlap=200):
    """
    Splits text from sections into chunks, each with metadata about its source section.
    """
    if not sections_data:
        return []
    
    all_chunks = []
    for section_title, section_text in sections_data:
        if not section_text.strip():
            continue
        
        # Use the robust semantic chunker on a per-section basis
        current_chunk = ""
        paragraphs = section_text.split('\n\n')
        for para in paragraphs:
            if not para.strip():
                continue
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    all_chunks.append({"text": current_chunk.strip(), "section": section_title})
                current_chunk = para + "\n\n"
        
        if current_chunk.strip():
            all_chunks.append({"text": current_chunk.strip(), "section": section_title})
            
    return all_chunks

def process_single_link(url):
    """
    Main controller function. Returns a displayable full text and a list of chunk dictionaries.
    """
    sections_data = []
    status = ""
    if "ncbi.nlm.nih.gov/pmc/articles" in url:
        html_content = fetch_content_from_url(url)
        if not html_content: return None, "Failed to fetch content."
        sections_data, status = parse_pmc_article(html_content)
    elif "clinicaltrials.gov/study" in url:
        nct_match = re.search(r'NCT\d+', url)
        if not nct_match: return None, "Could not extract NCT ID."
        sections_data, status = parse_clinical_trial_record(nct_match.group(0))
    else:
        return None, "Unrecognized URL."

    if not sections_data:
        return None, status

    text_chunks_with_metadata = chunk_text(sections_data)
    full_text_for_display = "\n\n".join([f"## {title}\n\n{text}" for title, text in sections_data])
    
    return full_text_for_display, text_chunks_with_metadata

def _parse_outcome_table(soup, table_title):
    """
    Finds a specific table by its preceding h2 title and parses it.
    Returns a list of formatted strings, e.g., ["Group A: 10 (5%)", "Group B: 12 (6%)"].
    """
    found_data = []
    try:
        # Find the <h2> tag that contains the exact table title
        header_tag = soup.find('h2', string=lambda t: t and table_title.strip().lower() in t.strip().lower())
        
        if not header_tag:
            return None # Table title not found on the page

        # Find the <table> element that immediately follows the header
        table = header_tag.find_next_sibling('table')
        if not table:
            return None # No table found after the header

        # --- Table Parsing Logic ---
        headers = [th.get_text(strip=True) for th in table.find('thead').find_all('th')]
        # We are interested in the Arm/Group titles, which start from the second column
        group_titles = headers[1:] 
        
        # Find the row that contains the data (e.g., "Count of Participants")
        data_row = None
        for tr in table.find('tbody').find_all('tr'):
            # The data we want is often in a row with a `th` scope="row" tag
            row_header = tr.find('th', {'scope': 'row'})
            if row_header and "Count of Participants" in row_header.get_text():
                data_row = tr
                break
        
        if not data_row:
            return None # Could not find the specific data row

        # Extract the numerical values from the data cells (td)
        values = [td.get_text(strip=True) for td in data_row.find_all('td')]

        # Combine the group titles with their corresponding values
        for i, title in enumerate(group_titles):
            if i < len(values):
                # Replace newline characters inside the value for cleaner output
                cleaned_value = values[i].replace('\n', ' ')
                found_data.append(f"{title}: {cleaned_value}")

        return found_data

    except Exception as e:
        # This will catch errors during parsing (e.g., if a table has an unexpected structure)
        print(f"Error parsing table '{table_title}': {e}")
        return None
