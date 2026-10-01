"""Reviewed original-publisher PDF links; never infer a filename or upload path."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PUBLISHER_URL = 'https://bereanvoice.com/'
DEFAULT_MAPPING = Path(__file__).resolve().parents[1] / 'data/issue-pdfs.json'


def issue_pdf_links(issues, mapping=DEFAULT_MAPPING):
    data = json.loads(Path(mapping).read_text(encoding='utf-8'))
    if data.get('schemaVersion') != 1 or not isinstance(data.get('issues'), list):
        raise ValueError('Unsupported publisher PDF mapping')
    reviewed = {}
    for record in data['issues']:
        issue_id = record['issueId']
        url = urlsplit(record['pdfUrl'])
        checks = record.get('verification', {})
        if (issue_id in reviewed or url.scheme != 'https' or url.netloc != 'bereanvoice.com'
                or not url.path.startswith('/wp-content/uploads/') or not url.path.lower().endswith('.pdf')
                or url.query or url.fragment or not re.fullmatch(r'[a-f0-9]{64}', record['sourceSha256'])
                or not all(checks.get(key) is True for key in ('publisherLinkObserved', 'downloadSucceeded', 'pdfHeaderVerified', 'sha256MatchesSource'))):
            raise ValueError(f'Invalid reviewed publisher PDF: {issue_id}')
        reviewed[issue_id] = record
    links = {}
    for issue in issues:
        record = reviewed.get(issue['id'])
        if not record:
            # A future converted issue is still readable. Do not invent a download.
            continue
        if (issue.get('source') or {}).get('sha256') != record['sourceSha256']:
            raise ValueError(f'Publisher PDF no longer matches source issue: {issue["id"]}')
        links[issue['id']] = record['pdfUrl']
    return links
