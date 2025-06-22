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

    # Extract title with fallbacks
    title_tag = (soup.find('h1', class_='content-title') or
                 soup.find('h1') or
                 soup.find('title'))
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"

    # Extract abstract with fallbacks
    abstract_div = (soup.find('div', class_='abstract') or
                    soup.find('div', id=re.compile('abstract.*', re.I)))
    abstract = abstract_div.get_text(separator='\n', strip=True) if abstract_div else ""

    # Extract body with fallbacks
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

def parse_clinical_trial_record(html_content):
    """
    Parses HTML from a ClinicalTrials.gov record to extract title and sections.
    Uses fallback selectors to handle website changes.
    """
    if not html_content:
        return "", "No HTML content provided."

    soup = BeautifulSoup(html_content, 'html.parser')

    # Extract title with fallbacks
    title_tag = (soup.find('h1', {'data-testid': 'official-title-h1'}) or
                 soup.find('h1') or
                 soup.find('title'))
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"

    full_text = f"# {title}\n\n"

    # Extract sections with fallbacks
    section_headers = (soup.find_all('h2', {'data-testid': re.compile(r'h2-.*')}) or
                       soup.find_all('h2'))
    section_found = False
    for header in section_headers:
        section_title = header.get_text(strip=True)
        content_div = header.find_next_sibling('div') or header.find_parent('div').find_next('div')
        if content_div:
            section_text = content_div.get_text(separator='\n', strip=True)
            full_text += f"## {section_title}\n\n{section_text}\n\n"
            section_found = True

    return full_text, "Success" if section_found else "No sections parsed from ClinicalTrials.gov record."

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
    html_content = fetch_content_from_url(url)
    if not html_content:
        return None, "Failed to fetch content."

    clean_text = ""
    status = ""
    if "ncbi.nlm.nih.gov/pmc/articles" in url:
        clean_text, status = parse_pmc_article(html_content)
    elif "clinicaltrials.gov/study" in url:
        clean_text, status = parse_clinical_trial_record(html_content)
    else:
        return None, "URL is not a recognized PMC or ClinicalTrials.gov link."

    if not clean_text:
        return None, status

    text_chunks = chunk_text(clean_text)
    return clean_text, text_chunks
