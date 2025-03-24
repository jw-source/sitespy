import os
import re
import time
import logging
import hashlib
import difflib
import requests
import html
from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import urlparse
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class DiffCode:
    SIMILAR = 0
    RIGHTONLY = 1
    LEFTONLY = 2
    CHANGED = 3

class DifflibParser:
    def __init__(self, text1: list[str], text2: list[str]):
        self._diff = list(difflib.unified_diff(
            text1, text2,
            fromfile='original', tofile='modified',
            lineterm=''
        ))
        self._current_line = 0

    def __iter__(self):
        return self

    def __next__(self) -> dict:
        while self._current_line < len(self._diff):
            line = self._diff[self._current_line]
            self._current_line += 1
            if line.startswith(('---', '+++', '@@')):
                continue
            code = line[0] if line else ' '
            content = line[1:] if len(line) > 1 else ''
            result = {'code': DiffCode.SIMILAR, 'line': content}
            if code == '-':
                result['code'] = DiffCode.LEFTONLY
            elif code == '+':
                result['code'] = DiffCode.RIGHTONLY
            return result
        raise StopIteration

class Scraper:
    @staticmethod
    def remove_tags(html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup.find_all(['br', 'p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            tag.insert_after('\n')
        text = soup.get_text('\n', strip=True)
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
            elif lines and lines[-1] != '':
                lines.append('')
        return '\n'.join(lines)

    def fetch(self, url: str) -> tuple[str, str]:
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            response.encoding = response.apparent_encoding
            text_content = self.remove_tags(response.text)
            content_hash = hashlib.sha224(text_content.encode('utf-8')).hexdigest()
            return content_hash, text_content
        except Exception as e:
            logging.error(f"Error fetching {url}: {e}")
            return "", ""

class ChangeDetector:
    @staticmethod
    def get_diff(old_content: str, new_content: str) -> list[str]:
        old_lines = old_content.split('\n') if old_content else []
        new_lines = new_content.split('\n') if new_content else []
        return list(difflib.unified_diff(old_lines, new_lines))

    @staticmethod
    def generate_side_by_side_diff(old_content: str, new_content: str) -> str:
        old_lines = old_content.split('\n') if old_content else []
        new_lines = new_content.split('\n') if new_content else []
        parser = DifflibParser(old_lines, new_lines)
        html_parts = [
            '<div class="diff-container">',
            '<table class="diff-table">',
            '<tr><th>Before</th><th>After</th></tr>'
        ]
        for entry in parser:
            row_class = []
            left_content = '&nbsp;'
            right_content = '&nbsp;'
            escaped_line = html.escape(entry["line"])
            if entry['code'] == DiffCode.LEFTONLY:
                left_content = f'<span class="diff-remove">{escaped_line}</span>'
                row_class.append('removed')
            elif entry['code'] == DiffCode.RIGHTONLY:
                right_content = f'<span class="diff-add">{escaped_line}</span>'
                row_class.append('added')
            else:
                left_content = escaped_line
                right_content = escaped_line
                row_class.append('unchanged')
            html_parts.append(
                f'<tr class="{" ".join(row_class)}">'
                f'<td class="left">{left_content}</td>'
                f'<td class="right">{right_content}</td>'
                '</tr>'
            )
        html_parts.extend(['</table>', '</div>'])
        return '\n'.join(html_parts)

class ChangeSummarizer:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def summarize(self, url: str, old_content: str, new_content: str, user_preferences: str) -> str:
        diff = ChangeDetector.get_diff(old_content, new_content)
        changes = {
            'additions': [line[1:] for line in diff if line.startswith('+')],
            'deletions': [line[1:] for line in diff if line.startswith('-')]
        }
        completion = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    f"Analyze content changes for {url}. User profile: {user_preferences}. "
                    "Focus on factual changes, ignore formatting. Use concise bullet points."
                )},
                {"role": "user", "content": (
                    f"Removed content:\n{chr(10).join(changes['deletions'])}\n\n"
                    f"Added content:\n{chr(10).join(changes['additions'])}"
                )}
            ]
        )
        return completion.choices[0].message.content

    def is_change_important(self, url: str, old_content: str, new_content: str, user_preferences: str) -> bool:
        diff = ChangeDetector.get_diff(old_content, new_content)
        changes = {
            'additions': [line[1:] for line in diff if line.startswith('+')],
            'deletions': [line[1:] for line in diff if line.startswith('-')]
        }
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    f"Determine if the following changes on {url} are important enough to warrant a report. "
                    f"User profile: {user_preferences}. Respond with a single word: 'Yes' or 'No'."
                )},
                {"role": "user", "content": (
                    f"Removed content:\n{chr(10).join(changes['deletions'])}\n\n"
                    f"Added content:\n{chr(10).join(changes['additions'])}"
                )}
            ]
        )
        answer = response.choices[0].message.content.strip().lower()
        logging.info(f"False positive check answer: {answer}")
        return 'yes' in answer

class Storage:
    def __init__(self):
        self.data: dict[str, dict] = defaultdict(dict)

    def add_url(self, url: str, content_hash: str, content: str) -> None:
        self.data[url].update({
            'hash': content_hash,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })

    def get_url_data(self, url: str) -> dict:
        return self.data.get(url, {})

    def update_url(self, url: str, content_hash: str, content: str) -> None:
        self.add_url(url, content_hash, content)

class WebsiteMonitor:
    def __init__(self, urls: list[str], user_preferences: str, check_interval: int, meaningful_change: bool = True):
        self.urls = urls
        self.user_preferences = user_preferences
        self.check_interval = check_interval
        self.meaningful_change = meaningful_change
        self.scraper = Scraper()
        self.storage = Storage()
        self.summarizer = ChangeSummarizer()
        self._initialize_storage()

    def _initialize_storage(self) -> None:
        for url in self.urls:
            content_hash, content = self.scraper.fetch(url)
            if content_hash:
                self.storage.add_url(url, content_hash, content)
            else:
                logging.warning(f"Initial fetch failed for {url}")

    def run(self) -> None:
        try:
            while True:
                for url in self.urls:
                    logging.info(f"Checking {url}")
                    current_hash, current_content = self.scraper.fetch(url)
                    stored_data = self.storage.get_url_data(url)
                    if not stored_data.get('hash'):
                        self.storage.add_url(url, current_hash, current_content)
                        continue
                    if current_hash and current_hash != stored_data['hash']:
                        if self.meaningful_change:
                            if self.summarizer.is_change_important(url, stored_data['content'], current_content, self.user_preferences):
                                logging.info(f"Significant changes detected at {datetime.now()} for {url}")
                                self._generate_report(url, stored_data['content'], current_content)
                            else:
                                logging.info(f"Change at {url} deemed insignificant; skipping report.")
                        else:
                            logging.info(f"Change detected at {datetime.now()} for {url} (false positive check disabled)")
                            self._generate_report(url, stored_data['content'], current_content)
                        self.storage.update_url(url, current_hash, current_content)
                time.sleep(self.check_interval * 60)
        except KeyboardInterrupt:
            logging.info("Website monitoring stopped by user.")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")

    def _generate_report(self, url: str, old_content: str, new_content: str) -> None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace('www.', '')
        safe_domain = re.sub(r'[\/:]', '_', domain)
        report_filename = f"{safe_domain}_changes_{timestamp}.html"
        report_html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Change Report - {url}</title>
    <style>
        body {{
            margin: 20px 40px;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            line-height: 1.6;
        }}
        .diff-container {{
            border: 1px solid #e1e4e8;
            border-radius: 8px;
            margin: 20px 0;
            overflow-x: auto;
        }}
        .diff-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }}
        .diff-table td {{
            width: 50%;
            vertical-align: top;
            padding: 12px;
            border: 1px solid #e1e4e8;
            font-family: SFMono-Regular, Consolas, Liberation Mono, Menlo, monospace;
            font-size: 14px;
        }}
        .removed td {{
            background-color: #ffebe9;
        }}
        .added td {{
            background-color: #e6ffec;
        }}
        .diff-remove {{
            background-color: #ffd7d5;
            text-decoration: line-through;
            color: #86181d;
        }}
        .diff-add {{
            background-color: #ccffd8;
            color: #176f2c;
        }}
        h1, h2 {{
            color: #1a1a1a;
        }}
        .timestamp {{
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <h1>Website Change Report</h1>
    <h2>{url} <span class="timestamp">({datetime.now().strftime('%Y-%m-%d %H:%M')})</span></h2>
    <h3>Summary of Changes</h3>
    <div class="summary">{self.summarizer.summarize(url, old_content, new_content, self.user_preferences)}</div>
    <h3>Detailed Comparison</h3>
    {ChangeDetector.generate_side_by_side_diff(old_content, new_content)}
</body>
</html>'''
        try:
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write(report_html)
            logging.info(f"Generated report: {report_filename}")
        except Exception as e:
            logging.error(f"Error writing report {report_filename}: {e}")

if __name__ == "__main__":
    monitor = WebsiteMonitor(
        urls=[
            'https://hackernews.com',
            'https://www.nytimes.com'
        ],
        user_preferences="Technical analyst focusing on substantive content changes",  # User profile to get customized summaries
        check_interval=1,  # Check every X minutes
        meaningful_change=True  # Uses AI to filter out false positives
    )
    monitor.run()
