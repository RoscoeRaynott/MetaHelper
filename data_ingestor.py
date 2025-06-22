import requests
from bs4 import BeautifulSoup
import re

def fetch_content_from_url(url):
    """
    Fetches the raw HTML content from a given URL.
    Returns the HTML content as a string, or None if fetching fails.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

def parse_pmc_article(html_content):
    """
    Parses HTML from a PubMed Central article to extract title, abstract, and body.
    Uses fallback selectors to handle website changes.
    """
    if not html_content:
        return "", "No HTML content provided."

    soup = BeautifulSoup(html_content, 'html.parser')

    title_tag = (soup.find('h1', class_='content-title') or
                 soup.find('h1') or
                 soup.find('title'))
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"

    abstract_div = (soup.find('div', class_='abstract') or
                    soup.find('div', id=re.compile('abstract.*', re.I)))
    abstract = abstract_div.get_text(separator='\n', strip=True) if abstract_div else ""

    body_div = (soup.find('div', class_='jig-ncbiinpagenav') or
                soup.find('div', class_=re.compile('article.*', re.I)) or
                soup.find('article'))
    body_text = ""
    if body_div:
        sections = body_div.find_all('div', class_='sec') or body_div.find_all('section')
        for sec in sections:
            sec_title = sec.find(['h2', 'h3'])
            if sec_title:
                body_text += f"\n\n## {sec_title.get_text(strip=True)}\n\n"
            paragraphs = sec.find_all('p')
            for p in paragraphs:
                body_text += p.get_text(strip=True) + "\n"

    full_text = f"# {title}\n\n## Abstract\n{abstract}\n{body_text}"
    return full_text, "Success" if (abstract or body_text) else "No content parsed from PMC article."

def parse_clinical_trial_record(nct_id):
    """
    Fetches and parses a ClinicalTrials.gov study using the API v2 endpoint.
    Returns structured text with title, summary, description, conditions, interventions, outcomes, results, and eligibility.
    """
    if not nct_id:
        return "", "No NCT ID provided."

    api_url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Extract relevant fields
        protocol = data.get('protocolSection', {})
        title = protocol.get('identificationModule', {}).get('officialTitle') or protocol.get('identificationModule', {}).get('briefTitle', 'No Title Found')
        summary = protocol.get('descriptionModule', {}).get('briefSummary', '')
        detailed_description = protocol.get('descriptionModule', {}).get('detailedDescription', '')
        conditions = protocol.get('conditionsModule', {}).get('conditions', [])
        eligibility = protocol.get('eligibilityModule', {}).get('eligibilityCriteria', '')
        status = protocol.get('statusModule', {}).get('overallStatus', 'N/A')
        interventions = protocol.get('armsInterventionsModule', {}).get('interventions', [])
        primary_outcomes = protocol.get('outcomesModule', {}).get('primaryOutcomes', [])
        secondary_outcomes = protocol.get('outcomesModule', {}).get('secondaryOutcomes', [])
        results = data.get('resultsSection', {})

        # Format interventions
        interventions_text = ''
        for idx, interv in enumerate(interventions, 1):
            interv_name = interv.get('name', 'Unknown')
            interv_type = interv.get('type', 'Unknown')
            interv_desc = interv.get('description', '')
            interventions_text += f"Intervention {idx}: {interv_name} ({interv_type})\n{interv_desc}\n\n"

        # Format outcomes
        outcomes_text = ''
        if primary_outcomes:
            outcomes_text += "Primary Outcomes:\n"
            for idx, outcome in enumerate(primary_outcomes, 1):
                measure = outcome.get('measure', 'N/A')
                time_frame = outcome.get('timeFrame', 'N/A')
                description = outcome.get('description', '')
                outcomes_text += f"{idx}. {measure}\n  Time Frame: {time_frame}\n  Description: {description}\n\n"
        if secondary_outcomes:
            outcomes_text += "Secondary Outcomes:\n"
            for idx, outcome in enumerate(secondary_outcomes, 1):
                measure = outcome.get('measure', 'N/A')
                time_frame = outcome.get('timeFrame', 'N/A')
                description = outcome.get('description', '')
                outcomes_text += f"{idx}. {measure}\n  Time Frame: {time_frame}\n  Description: {description}\n\n"

        # Format results
        results_text = ''
        if results:
            adverse_events = results.get('adverseEventsModule', {})
            if adverse_events:
                results_text += "Adverse Events:\n"
                serious_events = adverse_events.get('seriousAdverseEvents', [])
                other_events = adverse_events.get('otherAdverseEvents', [])
                for event in serious_events + other_events:
                    term = event.get('term', 'Unknown')
                    count = event.get('eventCount', 'N/A')
                    results_text += f"{term}: {count} events\n"
            outcome_results = results.get('outcomeMeasuresModule', {})
            if outcome_results:
                results_text += "\nOutcome Results:\n"
                for measure in outcome_results.get('outcomeMeasures', []):
                    title = measure.get('title', 'Unknown')
                    result_desc = measure.get('description', '')
                    results_text += f"{title}\n{result_desc}\n"

        # Build full text
        full_text = f"# {title}\n(NCT ID: {nct_id})\n\n"
        if status:
            full_text += f"## Status\n{status}\n\n"
        if summary:
            full_text += f"## Summary\n{summary}\n\n"
        if detailed_description:
            full_text += f"## Detailed Description\n{detailed_description}\n\n"
        if conditions:
            full_text += f"## Conditions\n{'\n'.join(conditions)}\n\n"
        if eligibility:
            full_text += f"## Eligibility Criteria\n{eligibility}\n\n"
        if interventions_text:
            full_text += f"## Interventions\n{interventions_text}\n"
        if outcomes_text:
            full_text += f"## Outcomes\n{outcomes_text}\n"
        if results_text:
            full_text += f"## Results\n{results_text}\n"

        content_found = any([summary, detailed_description, conditions, eligibility, interventions_text, outcomes_text, results_text])
        status = "Success" if content_found else f"No content parsed from ClinicalTrials.gov API for NCT ID: {nct_id}"
        print(f"Parse status for ClinicalTrials.gov (NCT ID: {nct_id}): {status}")

        return full_text, status

    except requests.exceptions.RequestException as e:
        print(f"API request failed for NCT ID {nct_id}: {e}")
        return "", f"API request failed: {str(e)}"
    except ValueError as e:  # Covers JSON decode errors
        print(f"JSON decode error for NCT ID {nct_id}: {e}")
        return "", f"JSON decode error: {str(e)}"

def chunk_text(text, chunk_size=1500, chunk_overlap=200):
    """
    Splits a long text into smaller, overlapping chunks.
    """
    if not text:
        return []
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - chunk_overlap
    return chunks

def process_single_link(url):
    """
    Main controller function for this module.
    Takes a single URL, fetches, parses, and chunks it.
    """
    print(f"Processing link: {url}")
    if "ncbi.nlm.nih.gov/pmc/articles" in url:
        html_content = fetch_content_from_url(url)
        if not html_content:
            return None, "Failed to fetch content."
        clean_text, status = parse_pmc_article(html_content)
    elif "clinicaltrials.gov/study" in url:
        nct_match = re.search(r'NCT\d+', url)
        if not nct_match:
            return None, "Could not extract NCT ID from URL."
        nct_id = nct_match.group(0)
        clean_text, status = parse_clinical_trial_record(nct_id)
    else:
        return None, "URL is not a recognized PMC or ClinicalTrials.gov link."

    if not clean_text:
        return None, status

    text_chunks = chunk_text(clean_text)
    return clean_text, text_chunks
