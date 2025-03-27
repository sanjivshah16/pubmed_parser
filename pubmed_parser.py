import streamlit as st
import re
import requests
import time
from urllib.parse import quote_plus

def search_pubmed_api(reference, retmax=3):
    """Search PubMed API for a reference, using DOI first if available and validating title word match."""
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    # Extract DOI
    doi_match = re.search(r'10\.\d{4,9}/[\S]+', reference)
    doi = doi_match.group(0) if doi_match else None

    # Extract metadata
    title_match = re.search(r'(?:\.\s+|\:\s+)([^\.]+?)(?:\.|\s+[A-Z]|$)', reference)
    raw_title = title_match.group(1).strip() if title_match else ""
    title_words = re.findall(r'\w+', re.sub(r'[-]', ' ', raw_title.lower()))

    year_match = re.search(r'(\d{4})', reference)
    year = year_match.group(1) if year_match else ""

    author_match = re.search(r'^([A-Za-z\-]+)', reference)
    first_author = author_match.group(1).lower() if author_match else ""

    journal_match = re.search(r'([A-Z][A-Za-z\s]+)(?:\s+\d{4}|\s+[0-9;():]+)', reference)
    journal = journal_match.group(1).strip().lower() if journal_match else ""

    pmids = []

    # Try DOI first
    if doi:
        query = doi
        search_url = f"{base_url}esearch.fcgi?db=pubmed&term={quote_plus(query)}&retmax=1&retmode=json"
        try:
            response = requests.get(search_url)
            response.raise_for_status()
            search_results = response.json()
            pmids = search_results.get('esearchresult', {}).get('idlist', [])
            if not pmids:
                st.write(f"❌ DOI search failed for DOI: {doi}")
                st.write(f"Search URL: {search_url}")
                st.write(f"Response text: {response.text}")
        except Exception as e:
            st.write(f"❌ Error searching DOI: {doi}")
            st.write(f"Exception: {e}")
            st.write(f"Search URL: {search_url}")
            pmids = []

    # Try fallback strategies
    if not pmids:
        search_strategies = [
            f"{raw_title} AND {first_author}[Author] AND {year}[Year] AND {journal}[Journal]" if raw_title and first_author and year and journal else None,
            f"{raw_title} AND {journal}[Journal]" if raw_title and journal else None,
            f"{first_author}[Author] AND {journal}[Journal] AND {year}[Year]" if first_author and journal and year else None,
            raw_title if raw_title else None,
            f"{first_author}[Author] AND {year}[Year]" if first_author and year else None
        ]

        for query in search_strategies:
            if not query:
                continue
            search_url = f"{base_url}esearch.fcgi?db=pubmed&term={quote_plus(query)}&retmax={retmax}&retmode=json"
            try:
                response = requests.get(search_url)
                response.raise_for_status()
                search_results = response.json()
                pmids = search_results.get('esearchresult', {}).get('idlist', [])
                if pmids:
                    break
            except:
                continue

    if not pmids:
        return []

    try:
        fetch_url = f"{base_url}esummary.fcgi?db=pubmed&id={pmids[0]}&retmode=json"
        summary_response = requests.get(fetch_url)
        summary_response.raise_for_status()
        summary_data = summary_response.json()
        result = summary_data.get('result', {}).get(pmids[0], {})
        if not result:
            return []

        # Validate title word match
        pub_title = result.get('title', '')
        pub_title_words = re.findall(r'\w+', pub_title.lower())

        word_overlap = len(set(title_words).intersection(pub_title_words))
        required_match = min(3, len(title_words))

        if word_overlap < required_match:
            return []

        # Format reference
        authors = result.get('authors', [])
        all_authors_str = ", ".join([a['name'] for a in authors])
        journal = result.get('source', '')
        pub_date = result.get('pubdate', '')
        volume = result.get('volume', '')
        pages = result.get('pages', '')
        year = pub_date.split(" ")[0]
        pmid = result.get('uid', '')
        pmcid = next((aid.get('value') for aid in result.get('articleids', []) if aid.get('idtype') == 'pmc'), "")

        formatted_citation = f"{all_authors_str}. {pub_title}. {journal}. {year};{volume}:{pages}. PMID: {pmid}"
        if pmcid:
            formatted_citation += f". PMCID: {pmcid}"

        return [{
            'pmid': pmid,
            'pmcid': pmcid,
            'formatted': formatted_citation,
            'title': pub_title,
            'authors': all_authors_str,
            'source': journal,
            'date': pub_date,
            'strategy': "DOI" if doi else query[:50] + "..." if len(query) > 50 else query
        }]
    except:
        return []

    return []


def batch_search_pubmed_api(reference_group):
    results = []
    for ref in reference_group:
        result = search_pubmed_api(ref)
        results.append(result[0] if result else None)
        time.sleep(0.34)
    return results

def extract_references(text):
    lines = text.strip().splitlines()
    if lines and lines[0].strip().lower() in {"references", "citations", "literature cited", "bibliography"}:
        text = "\n".join(lines[1:])

    text = re.sub(r'-\n', '-', text)
    text = re.sub(r'([a-z])\n([a-z])', r'\1 \2', text)
    pattern = r'(?:^|\n)(\d+)\.?\s+(.*?)(?=(?:\n\d+\.?\s+)|$)'
    matches = re.findall(pattern, text, re.DOTALL)

    if matches:
        refs = []
        for number, content in matches:
            content = re.sub(r'\n', ' ', content).strip()
            refs.append((number, content))
        return refs
    else:
        refs = [ref.strip() for ref in text.split('\n') if ref.strip()]
        return [(str(i+1), ref) for i, ref in enumerate(refs)]

def fetch_nbib(pmids):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "nbib",
        "retmode": "text"
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.text
    except Exception as e:
        st.error(f"Failed to fetch NBIB: {e}")
        return None

def main():
    st.set_page_config(page_title="PubMed Reference Matcher", layout="wide")
    st.title("PubMed Reference Matcher")
    st.write("Paste a reference list from a biomedical paper to find matching PubMed IDs.")

    reference_text = st.text_area("Paste references here:", height=300)

    if 'matched_refs' not in st.session_state:
        st.session_state.matched_refs = []
        st.session_state.unmatched_refs = []

    if st.button("Match References"):
        if not reference_text:
            st.warning("Please paste reference text first.")
            return

        references = extract_references(reference_text)

        if len(references) == 0:
            st.error("No references found in the text. Please check your input.")
            return

        st.write(f"Found {len(references)} references.")
        matched_refs = []
        unmatched_refs = []

        progress_bar = st.progress(0)

        for i in range(0, len(references), 3):
            group = references[i:i+3]
            group_refs = [ref for _, ref in group]
            group_results = batch_search_pubmed_api(group_refs)

            for j, result in enumerate(group_results):
                number, ref = group[j]
                if result:
                    result['original_ref'] = ref
                    result['number'] = number
                    matched_refs.append(result)
                else:
                    unmatched_refs.append((number, ref))

            progress_bar.progress(min((i + len(group)) / len(references), 1.0))

        st.session_state.matched_refs = matched_refs
        st.session_state.unmatched_refs = unmatched_refs

    matched_refs = st.session_state.get('matched_refs', [])
    unmatched_refs = st.session_state.get('unmatched_refs', [])

    if matched_refs or unmatched_refs:
        st.subheader("Review Matches")
        selected_matches = {}

        for i, match in enumerate(matched_refs):
            st.write("---")
            st.write(f"**#{match['number']}**: {match['original_ref']}")
            st.write(f"✅ **Matched Reference:** {match['formatted']}")
            keep_match = st.checkbox(f"Keep this match (PMID: {match['pmid']})", value=True, key=f"match_{i}")
            if keep_match:
                selected_matches[match['number']] = match

        if unmatched_refs:
            st.subheader("Unmatched References")
            for number, ref in unmatched_refs:
                st.write(f"❌ **#{number}**: {ref}")
                st.write("---")

        if selected_matches:
            st.subheader("Download Matched Results")

            pmids = [m['pmid'] for m in selected_matches.values()]
            pmid_list = "\n".join(pmids)
            mapping_list = "\n".join([f"{num}: {m['pmid']}" for num, m in selected_matches.items()])
            formatted_citations = "\n\n".join([f"{num}. {m['formatted']}" for num, m in selected_matches.items()])

            st.download_button("📄 Download PMIDs", pmid_list, "matched_pmids.txt", "text/plain", use_container_width=True)
            st.download_button("📄 Download Reference Number -> PMID Mapping", mapping_list, "reference_pmid_mapping.txt", "text/plain", use_container_width=True)
            st.download_button("📄 Download Formatted References", formatted_citations, "formatted_references.txt", "text/plain", use_container_width=True)

            # NBIB download
            nbib_text = fetch_nbib(pmids)
            if nbib_text:
                st.download_button("📥 Download NBIB for EndNote", nbib_text, "references.nbib", "text/plain", use_container_width=True)

if __name__ == "__main__":
    main()
