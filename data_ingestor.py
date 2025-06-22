# data_ingestor.py

import requests
from bs4 import BeautifulSoup
import PyPDF2
import io
from langchain.text_splitter import RecursiveCharacterTextSplitter

def fetch_content_from_url(url):
    """
    Fetches content from a URL. Returns content and content_type ('html' or 'pdf').
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()  # Raise an exception for bad status codes

        content_type = response.headers.get('Content-Type', '')
        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            return response.content, 'pdf'
        else:
            return response.text, 'html'
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None, None

def parse_pdf(pdf_content):
    """
    Parses text from PDF content.
    """
    try:
        pdf_file = io.BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error parsing PDF content: {e}")
        return ""

def parse_pmc_article(html_content):
    """
    Parses the main text from a PubMed Central article's HTML.
    Focuses on title, abstract, and main body content.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title
    title_tag = soup.find('h1', class_='content-title')
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"
    
    # Extract abstract
    abstract_div = soup.find('div', class_='abstract')
    abstract = abstract_div.get_text(strip=True) if abstract_div else ""
    
    # Extract main body, focusing on divs that typically contain article content
    body_div = soup.find('div', class_='j-body')
    body_text = body_div.get_text(strip=True) if body_div else ""
    
    full_text = f"Title: {title}\n\nAbstract: {abstract}\n\nBody: {body_text}"
    return full_text, title

def parse_clinical_trial_record(html_content):
    """
    Parses key sections from a ClinicalTrials.gov record's HTML.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title
    title_tag = soup.find(attrs={'data-testid': 'official-title'})
    title = title_tag.get_text(strip=True) if title_tag else "No Title Found"
    if title == "No Title Found": # Fallback to brief title
        title_tag = soup.find(attrs={'data-testid': 'brief-title'})
        title = title_tag.get_text(strip=True) if title_tag else "No Title Found"

    # Extract key sections using their data-testid attributes
    sections_to_extract = {
        "Condition": "condition",
        "Brief Summary": "brief-summary",
        "Detailed Description": "detailed-description",
        "Primary Outcome Measures": "primary-outcome",
        "Secondary Outcome Measures": "secondary-outcome"
    }
    
    full_text = f"Title: {title}\n\n"
    for section_name, test_id in sections_to_extract.items():
        section_tag = soup.find(attrs={'data-testid': test_id})
        if section_tag:
            full_text += f"{section_name}:\n{section_tag.get_text(strip=True)}\n\n"
            
    return full_text, title

def chunk_text(text, source_url, paper_title):
    """
    Splits a long text into smaller chunks using LangChain's text splitter.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    # Create documents with metadata before splitting
    # The splitter works best with a list of 'Document' objects or simple texts
    chunks = text_splitter.split_text(text)
    
    # Return a list of dictionaries, each with the chunk and its metadata
    return [
        {
            'text': chunk,
            'metadata': {
                'source_url': source_url,
                'title': paper_title
            }
        } 
        for chunk in chunks
    ]

def process_links(list_of_links):
    """
    Main controller function. Takes a list of URLs, processes them,
    and returns a list of all text chunks with metadata.
    """
    all_chunks_with_metadata = []
    for url in list_of_links:
        print(f"Processing: {url}")
        content, content_type = fetch_content_from_url(url)
        
        if not content:
            print(f"--> Failed to fetch content for {url}")
            continue

        clean_text = ""
        paper_title = "Unknown Title"

        if content_type == 'pdf':
            clean_text = parse_pdf(content)
            paper_title = url.split('/')[-1] # Use filename as title for PDFs
        
        elif content_type == 'html':
            if 'ncbi.nlm.nih.gov/pmc/articles' in url:
                clean_text, paper_title = parse_pmc_article(content)
            elif 'clinicaltrials.gov/study' in url:
                clean_text, paper_title = parse_clinical_trial_record(content)
            else:
                print(f"--> Don't know how to parse this HTML URL: {url}")
                continue
        
        if clean_text:
            chunks = chunk_text(clean_text, url, paper_title)
            all_chunks_with_metadata.extend(chunks)
            print(f"--> Success! Extracted and chunked. Found {len(chunks)} chunks.")
        else:
            print(f"--> Failed to extract text from {url}")
            
    return all_chunks_with_metadata
