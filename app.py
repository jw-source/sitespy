import streamlit as st
import os
import time
import threading
import pandas as pd
import glob
import re
import logging
from datetime import datetime

from main import Scraper, Storage, WebsiteMonitor, ChangeDetector, ChangeSummarizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

st.set_page_config(
    page_title="Website Change Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

if 'monitor_running' not in st.session_state:
    st.session_state.monitor_running = False
if 'monitor_thread' not in st.session_state:
    st.session_state.monitor_thread = None
if 'storage' not in st.session_state:
    st.session_state.storage = Storage()
if 'error_message' not in st.session_state:
    st.session_state.error_message = None
if 'urls' not in st.session_state:
    st.session_state.urls = ""
if 'openai_api_key' not in st.session_state:
    st.session_state.openai_api_key = ""
if 'user_preferences' not in st.session_state:
    st.session_state.user_preferences = "Technical analyst focusing on substantive content changes"
if 'check_interval' not in st.session_state:
    st.session_state.check_interval = 1
if 'meaningful_change' not in st.session_state:
    st.session_state.meaningful_change = True

monitor_thread_stop_event = None
monitor = None

def load_reports():
    reports = []
    for file in glob.glob("*_changes_*.html"):
        match = re.match(r'(.+)_changes_(\d{8}_\d{6})\.html', file)
        if match:
            domain = match.group(1).replace('_', '.')
            timestamp_str = match.group(2)
            timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
            reports.append({
                'domain': domain,
                'timestamp': timestamp,
                'filename': file
            })
    return sorted(reports, key=lambda x: x['timestamp'], reverse=True)

def monitor_websites(urls, user_preferences, check_interval, meaningful_change, stop_event):
    monitor = WebsiteMonitor(
        urls=urls,
        user_preferences=user_preferences,
        check_interval=check_interval,
        meaningful_change=meaningful_change
    )
    
    try:
        while not stop_event.is_set():
            for url in urls:
                if stop_event.is_set():
                    break

                logging.info(f"Checking {url}")
                current_hash, current_content = monitor.scraper.fetch(url)
                stored_data = monitor.storage.get_url_data(url)
                
                if not stored_data.get('hash'):
                    monitor.storage.add_url(url, current_hash, current_content)
                    continue
                
                if current_hash and current_hash != stored_data['hash']:
                    if meaningful_change:
                        if monitor.summarizer.is_change_important(url, stored_data['content'], current_content, user_preferences):
                            logging.info(f"Significant changes detected at {datetime.now()} for {url}")
                            monitor._generate_report(url, stored_data['content'], current_content)
                        else:
                            logging.info(f"Change at {url} deemed insignificant; skipping report.")
                    else:
                        logging.info(f"Change detected at {datetime.now()} for {url}")
                        monitor._generate_report(url, stored_data['content'], current_content)
                    
                    monitor.storage.update_url(url, current_hash, current_content)
            
            for _ in range(check_interval * 60):
                if stop_event.is_set():
                    break
                time.sleep(1)
                
    except Exception as e:
        logging.error(f"Error in monitoring thread: {e}")
        st.session_state.error_message = str(e)
        st.session_state.monitor_running = False

def start_monitoring():
    global monitor_thread_stop_event

    urls = st.session_state.urls.split('\n')
    urls = [url.strip() for url in urls if url.strip()]
    
    if not urls:
        st.error("Please add at least one URL to monitor")
        return
    
    if not st.session_state.openai_api_key:
        st.error("Please enter your OpenAI API key")
        return
    
    os.environ["OPENAI_API_KEY"] = st.session_state.openai_api_key
    
    user_preferences = st.session_state.user_preferences
    check_interval = st.session_state.check_interval
    meaningful_change = st.session_state.meaningful_change

    monitor_thread_stop_event = threading.Event()

    st.session_state.monitor_thread = threading.Thread(
        target=monitor_websites,
        args=(urls, user_preferences, check_interval, meaningful_change, monitor_thread_stop_event)
    )
    st.session_state.monitor_thread.daemon = True
    st.session_state.monitor_thread.start()
    st.session_state.monitor_running = True

def stop_monitoring():
    global monitor_thread_stop_event
    if monitor_thread_stop_event is not None:
        monitor_thread_stop_event.set()
    st.session_state.monitor_running = False

with st.sidebar:
    st.title("Website Monitor")
    st.subheader("Configuration")
    
    st.text_input(
        "OpenAI API Key",
        type="password",
        key="openai_api_key",
        disabled=st.session_state.monitor_running,
        help="Required for AI-powered change detection"
    )
    
    st.text_area(
        "URLs to Monitor (one per line)",
        key="urls",
        height=150,
        placeholder="https://example.com\nhttps://another-site.com",
        disabled=st.session_state.monitor_running
    )
    
    st.text_area(
        "User Preferences",
        key="user_preferences",
        height=100,
        placeholder="Technical analyst focusing on content changes",
        value="Technical analyst focusing on substantive content changes",
        disabled=st.session_state.monitor_running
    )
    
    st.number_input(
        "Check Interval (minutes)",
        min_value=1,
        max_value=1440,
        value=1,
        step=1,
        key="check_interval",
        disabled=st.session_state.monitor_running
    )
    
    st.checkbox(
        "Filter for Meaningful Changes Only",
        value=True,
        key="meaningful_change",
        disabled=st.session_state.monitor_running,
        help="Use AI to determine if changes are significant before generating reports"
    )
    
    if st.session_state.monitor_running:
        if st.button("Stop Monitoring", type="primary"):
            stop_monitoring()
            st.rerun()
    else:
        if st.button("Start Monitoring", type="primary"):
            start_monitoring()
            st.rerun()
    
    status = "Running" if st.session_state.monitor_running else "Stopped"
    st.info(f"Monitor Status: {status}")
    
    if st.session_state.error_message:
        st.error(f"Error: {st.session_state.error_message}")
        if st.button("Clear Error"):
            st.session_state.error_message = None
            st.rerun()

st.title("Website Change Monitor")

tab1, tab2, tab3 = st.tabs(["Reports", "Current Status", "Help"])

with tab1:
    st.header("Generated Reports")
    
    if st.button("Refresh Reports"):
        st.rerun()
    
    reports = load_reports()
    
    if not reports:
        st.info("No reports have been generated yet. Start monitoring to detect changes.")
    else:
        report_df = pd.DataFrame([
            {
                "Domain": r['domain'],
                "Timestamp": r['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "Report": r['filename']
            } for r in reports
        ])
        
        st.dataframe(
            report_df,
            column_config={
                "Report": st.column_config.LinkColumn(
                    "Report",
                    display_text="View Report"
                )
            },
            hide_index=True
        )
        
        st.subheader("Report Viewer")
        selected_report = st.selectbox(
            "Select a report to view:",
            options=[r['filename'] for r in reports],
            format_func=lambda x: f"{[r for r in reports if r['filename'] == x][0]['domain']} - {[r for r in reports if r['filename'] == x][0]['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if selected_report:
            try:
                with open(selected_report, 'r', encoding='utf-8') as f:
                    report_html = f.read()
                st.components.v1.html(report_html, height=600, scrolling=True)
            except Exception as e:
                st.error(f"Error loading report: {e}")

with tab2:
    st.header("Current Monitoring Status")
    
    if st.session_state.monitor_running:
        st.success("Monitoring is active")
        
        st.subheader("Monitored URLs")
        urls = st.session_state.urls.split('\n')
        urls = [url.strip() for url in urls if url.strip()]
        for i, url in enumerate(urls):
            st.write(f"{i+1}. {url}")
        
        st.subheader("Current Configuration")
        st.write(f"Check Interval: Every {st.session_state.check_interval} minutes")
        st.write(f"Meaningful Change Filter: {'Enabled' if st.session_state.meaningful_change else 'Disabled'}")
        st.write(f"User Preferences: {st.session_state.user_preferences}")
    else:
        st.warning("Monitoring is not active. Configure and start monitoring using the sidebar.")

with tab3:
    st.header("How to Use This Tool")
    st.markdown("""
    ### Getting Started
    
    1. **Add OpenAI API Key**: Enter your API key in the sidebar (required for AI features)
    2. **Add URLs**: Enter the URLs you want to monitor in the sidebar, one per line
    3. **Configure Settings**:
       - Set the check interval (how often to check for changes)
       - Choose whether to filter for meaningful changes
       - Define your user preferences to personalize detection
    4. **Start Monitoring**: Click the "Start Monitoring" button
    
    ### Understanding Reports
    
    When changes are detected, a report is generated with:
    - A summary of the changes (AI-generated)
    - A side-by-side comparison of the old and new content
    - Highlighted additions and deletions
    
    ### Tips for Best Results
    
    - Be specific in your user preferences to get relevant alerts
    - For frequently changing sites, consider longer check intervals
    - Use the meaningful change filter to reduce noise
    
    ### Technical Details
    
    This app uses:
    - Web scraping to fetch content
    - Difflib to detect changes
    - GPT-4o for intelligent change analysis
    - HTML reports for detailed visualization
    """)

st.markdown("---")
st.caption("Website Change Monitor v1.0 | Built with Streamlit")
