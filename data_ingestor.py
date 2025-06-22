# data_ingestor.py

import requests
from bs4 import BeautifulSoup
import re
# We will use a simple text splitter for now. LangChain is a great next step, but this avoids extra dependencies.

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
        response.raise_for_status()  # Will raise an HTTPError for bad responses (4XX or 5XX)
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

def parse_pmc_article(html_content):
    """
    Parses the HTML from a PubMed Central article to extract relevant text.
    Focuses on title, abstract, and main body content.
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title
    title_tag = soup.find('h1', class_='content-title')
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"
    
    # Extract abstract
    abstract_div = soup.find('div', class_='abstract')
    abstract = abstract_div.get_text(separator='\n', strip=True) if abstract_div else ""
    
    # Extract main body content
    body_div = soup.find('div', class_='jig-ncbiinpagenav') # Main content container on PMC
    body_text = ""
    if body_div:
        # Find all section divs within the body
        sections = body_div.find_all('div', class_='sec')
        for sec in sections:
            # Add section title if it exists
            sec_title = sec.find(['h2', 'h3'])
            if sec_title:
                body_text += f"\n\n## {sec_title.get_text(strip=True)}\n\n"
            # Add all paragraph text
            paragraphs = sec.find_all('p')
            for p in paragraphs:
                body_text += p.get_text(strip=True) + "\n"
    
    full_text = f"# {title}\n\n## Abstract\n{abstract}\n{body_text}"
    return full_text

def parse_clinical_trial_record(html_content):
    """
    Parses the HTML from a ClinicalTrials.gov record to extract key information.
    """
    if not html_content:
        return ""
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title
    title_tag = soup.find('h1', {'data-testid': 'official-title-h1'})
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"
    
    full_text = f"# {title}\n\n"
    
    # Find all sections which are identified by `data-testid` attributes on h2 tags
    section_headers = soup.find_all('h2', {'data-testid': re.compile(r'h2-.*')})
    
    for header in section_headers:
        section_title = header.get_text(strip=True)
        # The content is usually in the next sibling div
        content_div = header.find_next_sibling('div')
        if content_div:
            section_text = content_div.get_text(separator='\n', strip=True)
            full_text += f"## {section_title}\n\n{section_text}\n\n"
            
    return full_text

def chunk_text(text, chunk_size=1500, chunk_overlap=200):
    """
    Splits a long text into smaller, overlapping chunks.
    A simple implementation without external libraries.
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
    html_content = fetch_content_from_url(url)
    if not html_content:
        return None, "Failed to fetch content."

    clean_text = ""
    if "ncbi.nlm.nih.gov/pmc/articles" in url:
        clean_text = parse_pmc_article(html_content)
    elif "clinicaltrials.gov/study" in url:
        # Note: The CT.gov parser is a new addition and might need refinement
        # based on the actual HTML structure.
        clean_text = parse_clinical_trial_record(html_content)
    else:
        return None, "URL is not a recognized PMC or ClinicalTrials.gov link."

    if not clean_text:
        return None, "Failed to parse text from HTML."

    text_chunks = chunk_text(clean_text)
    
    # For verification, we return the clean text and the chunks
    return clean_text, text_chunks
