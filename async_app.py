import streamlit as st
import os
import re
import tempfile
import time
import io
import json
from datetime import datetime
from googleapiclient.discovery import build
from yt_dlp import YoutubeDL
from pydub import AudioSegment
import math
import groq
from groq import Groq
import pandas as pd
from docx import Document
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import queue

# Try to import the financial extractor (if available)
try:
    from financial_data_extractor import FinancialDataExtractor
    FINANCIAL_EXTRACTOR_AVAILABLE = True
except ImportError:
    FINANCIAL_EXTRACTOR_AVAILABLE = False
    st.warning("Financial Data Extractor module not found. Financial analysis features will be disabled.")

# === CONFIGURATION ===
SAVE_DIR = "calls_mp3s"
FFMPEG_PATH = "/usr/local/bin"
YOUTUBE_API_KEY = "AIzaSyDS9r0TtpLZ3hg4rJzRbqWrc_-Bvht_3l4"

# Get API key from environment
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("ChatGroq_API_KEY")
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    groq_client = None

groq_MODEL = "whisper-large-v3"
llm_model = "llama-3.3-70b-versatile"

CHUNK_SIZE_CHARS = 8000
CHUNK_OVERLAP_CHARS = 500
MAX_FILE_SIZE_MB = 25
CHUNK_DURATION_MINUTES = 10

KEYWORDS_FOR_SUMMARY_DEFAULT = """
Core Business & Financial Health
"[Company Name] financial performance"
"[Company Name] quarterly results" / "Q4 earnings [Company Name]"
"[Company Name] annual report"
"revenue growth [Company Name]"
"profit margin [Company Name]"
"balance sheet [Company Name]"

Management & Governance
"[Company Name] CEO/CFO interview"
"[Company Name] CEO/CFO join/leave/resign"
"[Company Name] leadership changes"
"corporate governance [Company Name]"
"board of directors [Company Name]"
"resignation or appointment [Company Name] executive"

Market & Competitive Position
"[Company Name] market share"
"[Company Name] vs competitors"
"industry analysis [Company Name] sector"
"customer acquisition [Company Name]"
"expansion plans [Company Name]"

Strategic Moves
"merger or acquisition [Company Name]"
"joint venture [Company Name]"
"strategic investment [Company Name]"
"product launch [Company Name]"
"R&D or innovation [Company Name]"

External Factors / Macro Trends
"regulatory impact on [Company Name]"
"government policy [industry] [Company Name]"
"economic slowdown effect [Company Name]"
"interest rate impact [Company Name]"

Risks & Red Flags
"[Company Name] fraud"
"[Company Name] litigation" or "lawsuit"
"credit rating [Company Name]"
"debt level [Company Name]"
"customer loss [Company Name]"
"plant closure [Company Name]"
"data breach [Company Name]"
"revenue loss [Company Name]"
"profit decline [Company Name]"

Investor Sentiment & Analyst Views
"analyst rating [Company Name]"
"buy/sell recommendation [Company Name]"
"[Company Name] stock target price"
"institutional holding [Company Name]"
"insider trading [Company Name]"

ESG (Environmental, Social, Governance)
"[Company Name] ESG report"
"[Company Name] carbon footprint"
"[Company Name] CSR activity"
"[Company Name] employee satisfaction"
"[Company Name] sustainability goals"

Financial Performance Keywords
Earnings report
Revenue
Profit/loss
EBITDA
Free cash flow
Debt-to-equity ratio
Price-to-earnings ratio
Price-to-book ratio
PEG ratio
"""

# Configure Streamlit page
st.set_page_config(
    page_title="Financial Analysis Suite",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
.main {
    padding-top: 2rem;
}
.stProgress .st-bo {
    background-color: #f0f2f6;
}
.upload-section {
    border: 2px dashed #cccccc;
    border-radius: 10px;
    padding: 2rem;
    text-align: center;
    margin: 1rem 0;
}
.success-message {
    background-color: #d4edda;
    border: 1px solid #c3e6cb;
    color: #155724;
    padding: 1rem;
    border-radius: 5px;
    margin: 1rem 0;
}
.error-message {
    background-color: #f8d7da;
    border: 1px solid #f5c6cb;
    color: #721c24;
    padding: 1rem;
    border-radius: 5px;
    margin: 1rem 0;
}
</style>
""", unsafe_allow_html=True)

# ==================== EARNINGS CALL FUNCTIONS ====================

def clean_text(text):
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'[^\w\s.,!?;:()-]', '', text)
    return text.strip()

def smart_chunk_text(text, chunk_size, overlap_size):
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        break_point = end
        for i in range(end - 200, end + 200):
            if i < len(text) and text[i] in '.!?':
                break_point = i + 1
                break
        chunk = text[start:break_point].strip()
        if len(chunk) > 100:
            chunks.append(chunk)
        start = break_point - overlap_size
    return [chunk for chunk in chunks if len(chunk.strip()) > 100]

def summarize_chunk(text_chunk, company_name, chunk_number, total_chunks, keywords):
    prompt = f"""You are analyzing an earnings call transcript for {company_name}.\nThis is chunk {chunk_number} of {total_chunks}...\n{text_chunk}\n..."""
    if groq_client is None:
        raise RuntimeError("GROQ API key is not configured.")
    response = groq_client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()

def create_final_summary(chunk_summaries, company_name, video_title, upload_date, keywords):
    combined_text = "\n\n".join(chunk_summaries)
    prompt = f"""Create comprehensive final summary from chunk summaries with keyword focus...\n{combined_text}"""
    response = groq_client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000
    )
    return response.choices[0].message.content.strip()

def download_youtube_audio_and_metadata(company_name):
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    search_queries = [f"{company_name} earnings call Q4 FY2025 trendlyne"]
    video = None
    for query in search_queries:
        search_response = youtube.search().list(q=query, part='snippet', maxResults=1, type='video').execute()
        if search_response['items']:
            video = search_response['items'][0]
            break
    if not video:
        raise ValueError("No earnings call found")
    video_id = video['id']['videoId']
    title = video['snippet']['title']
    upload_date = video['snippet']['publishedAt'][:10]
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    os.makedirs(SAVE_DIR, exist_ok=True)
    safe_filename = re.sub(r'[^\w\s-]', '', title)[:50]
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(SAVE_DIR, f'{safe_filename}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }],
        'ffmpeg_location': FFMPEG_PATH
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        audio_path = os.path.join(SAVE_DIR, f"{safe_filename}.mp3")
    return audio_path, title, upload_date

def split_audio_file(audio_path, chunk_duration_minutes=10):
    try:
        print(f"Loading audio file for splitting...")
        audio = AudioSegment.from_mp3(audio_path)
        chunk_duration_ms = chunk_duration_minutes * 60 * 1000
        total_duration_ms = len(audio)
        num_chunks = math.ceil(total_duration_ms / chunk_duration_ms)
        print(f"Audio duration: {total_duration_ms / 1000 / 60:.1f} minutes")
        print(f"Splitting into {num_chunks} chunks of {chunk_duration_minutes} minutes each")
        chunks_dir = os.path.join(os.path.dirname(audio_path), "audio_chunks")
        os.makedirs(chunks_dir, exist_ok=True)
        chunk_files = []
        for i in range(num_chunks):
            start_time = i * chunk_duration_ms
            end_time = min((i + 1) * chunk_duration_ms, total_duration_ms)
            chunk = audio[start_time:end_time]
            chunk_filename = f"chunk_{i+1:03d}.mp3"
            chunk_path = os.path.join(chunks_dir, chunk_filename)
            chunk.export(chunk_path, format="mp3", bitrate="64k")
            chunk_files.append(chunk_path)
            chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
            print(f"Created chunk {i+1}/{num_chunks}: {chunk_size_mb:.1f}MB")
        return chunk_files
    except Exception as e:
        print(f"Error splitting audio: {e}")
        return None

def transcribe_audio_chunks(chunk_files):
    all_transcripts = []
    for i, chunk_path in enumerate(chunk_files, 1):
        print(f"Transcribing chunk {i}/{len(chunk_files)}...")
        try:
            with open(chunk_path, "rb") as audio_file:
                transcript = groq_client.audio.transcriptions.create(
                    model=groq_MODEL,
                    file=audio_file,
                    language="en",
                    response_format="text"
                )
            if transcript:
                all_transcripts.append(transcript)
                print(f"✅ Chunk {i} transcribed: {len(transcript)} characters")
            else:
                print(f"⚠️ Chunk {i} returned empty transcript")
        except Exception as e:
            print(f"❌ Error transcribing chunk {i}: {e}")
            continue
    combined_transcript = " ".join(all_transcripts)
    print(f"✅ All chunks transcribed. Total length: {len(combined_transcript)} characters")
    for chunk_path in chunk_files:
        try:
            os.remove(chunk_path)
        except:
            pass
    try:
        chunks_dir = os.path.dirname(chunk_files[0])
        if not os.listdir(chunks_dir):
            os.rmdir(chunks_dir)
    except:
        pass
    return combined_transcript

def transcribe_with_groq(audio_path):
    try:
        print(f"Transcribing audio file: {audio_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        print(f"Audio file size: {file_size_mb:.2f} MB")
        if file_size_mb > MAX_FILE_SIZE_MB:
            print(f"File size exceeds {MAX_FILE_SIZE_MB}MB limit. Splitting into chunks...")
            chunk_files = split_audio_file(audio_path, CHUNK_DURATION_MINUTES)
            if not chunk_files:
                raise Exception("Failed to split audio file")
            transcript = transcribe_audio_chunks(chunk_files)
        else:
            with open(audio_path, "rb") as audio_file:
                transcript = groq_client.audio.transcriptions.create(
                    model=groq_MODEL,
                    file=audio_file,
                    language="en",
                    response_format="text"
                )
        if transcript:
            print(f"✅ Transcription completed. Length: {len(transcript)} characters")
            return transcript
        else:
            print("❌ Transcription returned empty result")
            return None
    except Exception as e:
        print(f"❌ Error during transcription: {e}")
        return None

# ==================== FINANCIAL EXTRACTOR FUNCTIONS ====================

def save_uploaded_file(uploaded_file, directory):
    file_path = os.path.join(directory, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_path

def display_table_preview(df, title):
    if not df.empty:
        st.subheader(title)
        formatted_df = df.copy()
        for col in formatted_df.columns:
            if col != 'Metric':
                try:
                    formatted_df[col] = pd.to_numeric(formatted_df[col], errors='ignore')
                    if formatted_df[col].dtype in ['float64', 'int64']:
                        formatted_df[col] = formatted_df[col].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "N/A")
                except:
                    pass
        st.dataframe(formatted_df, use_container_width=True)
    else:
        st.warning(f"No data available for {title}")

# ==================== PARALLEL EXECUTION WITH QUEUE-BASED UPDATES ====================

def run_earnings_call_analysis(company_name, status_queue):
    """
    Wrapper function to run earnings call analysis in a separate thread.
    Uses queue for thread-safe status updates.
    Returns a dict with success status and results.
    """
    try:
        status_queue.put(('progress', 0.1, "📥 Fetching audio from YouTube..."))
        
        audio_path, video_title, upload_date = download_youtube_audio_and_metadata(company_name)
        
        status_queue.put(('progress', 0.2, f"✅ Found: {video_title}"))
        status_queue.put(('progress', 0.3, "🎙️ Transcribing audio..."))
        
        raw_transcript = transcribe_with_groq(audio_path)
        
        if not raw_transcript:
            status_queue.put(('error', None, 'Transcription failed or returned empty'))
            return {
                'success': False,
                'error': 'Transcription failed or returned empty'
            }
        
        status_queue.put(('progress', 0.5, f"✅ Transcription complete ({len(raw_transcript)} chars)"))
        status_queue.put(('progress', 0.6, "🤖 Generating summary..."))
        
        cleaned = clean_text(raw_transcript)
        keywords = KEYWORDS_FOR_SUMMARY_DEFAULT.replace("[Company Name]", company_name)
        chunks = smart_chunk_text(cleaned, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
        
        summaries = []
        total_chunks = len(chunks)
        
        for i, chunk in enumerate(chunks, 1):
            progress = 0.6 + (0.25 * (i / total_chunks))
            status_queue.put(('progress', progress, f"📝 Summarizing chunk {i}/{total_chunks}..."))
            summary = summarize_chunk(chunk, company_name, i, total_chunks, keywords)
            summaries.append(summary)
        
        status_queue.put(('progress', 0.9, "📊 Creating final summary..."))
        
        final_summary = create_final_summary(summaries, company_name, video_title, upload_date, keywords)
        
        status_queue.put(('progress', 1.0, "✅ Earnings Call Analysis Complete!"))
        
        return {
            'success': True,
            'summary': final_summary,
            'video_title': video_title,
            'upload_date': upload_date,
            'transcript_length': len(raw_transcript)
        }
        
    except Exception as e:
        status_queue.put(('error', None, f"❌ Error: {str(e)}"))
        return {
            'success': False,
            'error': str(e)
        }


def run_financial_reports_analysis(company_name, default_year, report_files, audit_files, 
                                   filename_mapping, status_queue):
    """
    Wrapper function to run financial reports analysis in a separate thread.
    Uses queue for thread-safe status updates.
    Returns a dict with success status and results.
    """
    temp_dir = tempfile.mkdtemp()
    
    try:
        status_queue.put(('progress', 0.1, "📁 Saving uploaded files..."))
        
        # Save files to temp directory
        report_paths = [save_uploaded_file(file, temp_dir) for file in report_files]
        audit_paths = [save_uploaded_file(file, temp_dir) for file in audit_files]
        
        status_queue.put(('progress', 0.2, "🔧 Initializing extractor..."))
        
        # Initialize extractor
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        extractor = FinancialDataExtractor(company_name, default_year)
        
        if filename_mapping:
            extractor.set_filename_mapping(filename_mapping)
        
        extractor.set_report_files(report_paths)
        extractor.set_audit_files(audit_paths)
        
        status_queue.put(('progress', 0.3, "📊 Extracting financial data..."))
        
        extractor._extract_financial_data()
        
        status_queue.put(('progress', 0.5, "🔍 Extracting audit info..."))
        
        audit_summary = extractor._extract_audit_info()
        
        status_queue.put(('progress', 0.7, "📋 Creating comparison tables..."))
        
        comparison_tables = extractor._create_comparison_tables()
        
        status_queue.put(('progress', 0.8, "💡 Generating insights..."))
        
        insights = extractor._generate_insights()
        
        status_queue.put(('progress', 0.9, "📄 Creating final report..."))
        
        extractor._create_final_report(comparison_tables, audit_summary, insights)
        
        os.chdir(original_dir)
        
        word_file = f"{extractor.slug}_financial_analysis.docx"
        word_path = os.path.join(temp_dir, word_file)
        
        status_queue.put(('progress', 1.0, "✅ Financial Reports Analysis Complete!"))
        
        return {
            'success': True,
            'comparison_tables': comparison_tables,
            'insights': insights,
            'audit_summary': audit_summary,
            'stats': extractor.processing_stats,
            'tokens_used': extractor.tokens_used,
            'reports_data': extractor.reports_data,
            'word_path': word_path,
            'temp_dir': temp_dir
        }
        
    except Exception as e:
        status_queue.put(('error', None, f"❌ Error: {str(e)}"))
        
        # Cleanup on error
        try:
            os.chdir(original_dir)
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        
        return {
            'success': False,
            'error': str(e)
        }

# ==================== MAIN APP ====================

def main():
    st.title("📊 Financial Analysis Suite")
    st.markdown("**Comprehensive financial analysis: Earnings Call Analysis & Financial Report Extraction - Run Together!**")
    
    # Sidebar for API configuration
    with st.sidebar:
        st.header("🔑 API Configuration")
        
        env_api_key = os.getenv("GROQ_API_KEY") or os.getenv("ChatGroq_API_KEY")
        if env_api_key:
            st.success("✅ Using API key from environment")
            api_key_input = None
        else:
            api_key_input = st.text_input(
                "Groq API Key",
                type="password",
                help="Enter your Groq API key for AI processing"
            )
            if api_key_input:
                os.environ['ChatGroq_API_KEY'] = api_key_input
                os.environ['GROQ_API_KEY'] = api_key_input
                global groq_client
                groq_client = Groq(api_key=api_key_input)
                st.success("✅ API key configured")
        
        st.markdown("---")
        st.header("📋 Analysis Options")
        run_earnings_call = st.checkbox("Run Earnings Call Analysis", value=True)
        run_financial_reports = st.checkbox("Run Financial Reports Analysis", value=True)
        
        if not run_earnings_call and not run_financial_reports:
            st.warning("⚠️ Select at least one analysis type")
    
    # Main input section - Single company name for both analyses
    st.header("🏢 Company Information")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        company_name = st.text_input(
            "Company Name *",
            placeholder="e.g., Infosys",
            help="Enter the company name for analysis"
        )
    
    with col2:
        default_year = st.selectbox(
            "Default Year *",
            options=[str(year) for year in range(2020, 2030)],
            index=5,
            help="Used for financial report analysis"
        )
    
    # Split into two columns for different inputs
    col_left, col_right = st.columns(2)
    
    # Left column - Earnings Call (if enabled)
    with col_left:
        if run_earnings_call:
            st.subheader("📈 Earnings Call Analysis")
            st.info("Will fetch and analyze earnings call from YouTube")
        else:
            st.subheader("📈 Earnings Call Analysis")
            st.warning("Disabled - Enable in sidebar to run")
    
    # Right column - Financial Reports (if enabled)
    with col_right:
        if run_financial_reports:
            st.subheader("📊 Financial Reports Analysis")
            if FINANCIAL_EXTRACTOR_AVAILABLE:
                st.info("Will analyze uploaded PDF reports")
            else:
                st.error("Module not available")
        else:
            st.subheader("📊 Financial Reports Analysis")
            st.warning("Disabled - Enable in sidebar to run")
    
    # File uploads for financial reports (only if enabled)
    if run_financial_reports and FINANCIAL_EXTRACTOR_AVAILABLE:
        st.markdown("---")
        st.header("📁 Upload Financial Documents")
        
        col_reports, col_audits = st.columns(2)
        
        with col_reports:
            st.subheader("📈 Financial Report Files")
            uploaded_reports = st.file_uploader(
                "Upload PDF reports (Annual/Quarterly)",
                type=['pdf'],
                accept_multiple_files=True,
                key="reports_fd"
            )
        
        with col_audits:
            st.subheader("🔍 Audit Files")
            uploaded_audits = st.file_uploader(
                "Upload PDF audit reports",
                type=['pdf'],
                accept_multiple_files=True,
                key="audits_fd"
            )
        
        report_files = uploaded_reports or []
        audit_files = uploaded_audits or []
        
        # Display upload status
        if report_files:
            st.success(f"✅ {len(report_files)} report files uploaded")
        if audit_files:
            st.success(f"✅ {len(audit_files)} audit files uploaded")
        
        # Optional filename mapping
        if report_files:
            with st.expander("📝 Optional: Configure Filename to Period Mapping"):
                filename_mapping = {}
                for file in report_files:
                    period = st.text_input(
                        f"Period for {file.name}",
                        placeholder="e.g., 2025 Annual, 2025 Q2",
                        key=f"mapping_{file.name}"
                    )
                    if period:
                        filename_mapping[file.name] = period
        else:
            filename_mapping = {}
    else:
        report_files = []
        audit_files = []
        filename_mapping = {}
    
    # Validation
    can_process_ec = run_earnings_call and company_name and groq_client
    can_process_fr = run_financial_reports and company_name and default_year and groq_client and FINANCIAL_EXTRACTOR_AVAILABLE and (report_files or audit_files)
    can_process = can_process_ec or can_process_fr
    
    if not can_process:
        st.warning("⚠️ Please provide all required inputs before processing")
        missing = []
        if not company_name:
            missing.append("Company Name")
        if not groq_client:
            missing.append("Groq API Key")
        if run_financial_reports and not (report_files or audit_files):
            missing.append("Report or Audit Files")
        if missing:
            st.error(f"Missing: {', '.join(missing)}")
    
    st.markdown("---")
    
    # Main analysis button
    if st.button("🚀 Start Comprehensive Analysis", disabled=not can_process, type="primary", key="analyze_all"):
        
        # Initialize session state for results
        if 'ec_results' not in st.session_state:
            st.session_state.ec_results = None
        if 'fr_results' not in st.session_state:
            st.session_state.fr_results = None
        
        # Show parallel execution info
        if can_process_ec and can_process_fr:
            st.info("🚀 Running BOTH analyses in PARALLEL using separate threads for faster results!")
            col_ec, col_fr = st.columns(2)
        elif can_process_ec:
            st.info("📈 Running Earnings Call Analysis...")
            col_ec = st.container()
            col_fr = None
        else:
            st.info("📊 Running Financial Reports Analysis...")
            col_ec = None
            col_fr = st.container()
        
        # Create status displays and progress bars
        ec_progress_bar = None
        fr_progress_bar = None
        ec_status_text = None
        fr_status_text = None
        
        if can_process_ec:
            with col_ec if col_ec else st.container():
                st.subheader("📈 Earnings Call Analysis")
                ec_progress_bar = st.progress(0)
                ec_status_text = st.empty()
        
        if can_process_fr:
            with col_fr if col_fr else st.container():
                st.subheader("📊 Financial Reports Analysis")
                fr_progress_bar = st.progress(0)
                fr_status_text = st.empty()
        
        # Create queues for thread-safe communication
        ec_queue = queue.Queue() if can_process_ec else None
        fr_queue = queue.Queue() if can_process_fr else None
        
        # Execute analyses in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            
            # Submit earnings call analysis to thread pool
            if can_process_ec:
                ec_future = executor.submit(
                    run_earnings_call_analysis,
                    company_name,
                    ec_queue
                )
                futures['earnings_call'] = ec_future
            
            # Submit financial reports analysis to thread pool
            if can_process_fr:
                fr_future = executor.submit(
                    run_financial_reports_analysis,
                    company_name,
                    default_year,
                    report_files,
                    audit_files,
                    filename_mapping,
                    fr_queue
                )
                futures['financial_reports'] = fr_future
            
            # Poll queues and update UI in main thread
            all_done = False
            while not all_done:
                # Check earnings call queue
                if ec_queue:
                    try:
                        while True:
                            msg_type, progress, message = ec_queue.get_nowait()
                            if msg_type == 'progress' and ec_progress_bar and ec_status_text:
                                ec_progress_bar.progress(progress)
                                ec_status_text.info(f"🔄 {message}")
                            elif msg_type == 'error' and ec_status_text:
                                ec_status_text.error(f"❌ {message}")
                    except queue.Empty:
                        pass
                
                # Check financial reports queue
                if fr_queue:
                    try:
                        while True:
                            msg_type, progress, message = fr_queue.get_nowait()
                            if msg_type == 'progress' and fr_progress_bar and fr_status_text:
                                fr_progress_bar.progress(progress)
                                fr_status_text.info(f"🔄 {message}")
                            elif msg_type == 'error' and fr_status_text:
                                fr_status_text.error(f"❌ {message}")
                    except queue.Empty:
                        pass
                
                # Check if all futures are done
                all_done = all(future.done() for future in futures.values())
                
                if not all_done:
                    time.sleep(0.1)  # Small sleep to avoid busy waiting
            
            # Collect results from completed futures
            for name, future in futures.items():
                try:
                    result = future.result()
                    
                    if name == 'earnings_call':
                        if result.get('success'):
                            st.session_state.ec_results = result
                            if ec_progress_bar:
                                ec_progress_bar.progress(1.0)
                            if ec_status_text:
                                ec_status_text.success("✅ Earnings Call Analysis Complete!")
                        else:
                            st.session_state.ec_results = None
                            if ec_status_text:
                                ec_status_text.error(f"❌ Error: {result.get('error', 'Unknown error')}")
                    
                    elif name == 'financial_reports':
                        if result.get('success'):
                            st.session_state.fr_results = result
                            if fr_progress_bar:
                                fr_progress_bar.progress(1.0)
                            if fr_status_text:
                                fr_status_text.success("✅ Financial Reports Analysis Complete!")
                        else:
                            st.session_state.fr_results = None
                            if fr_status_text:
                                fr_status_text.error(f"❌ Error: {result.get('error', 'Unknown error')}")
                
                except Exception as e:
                    st.error(f"❌ Error in {name}: {str(e)}")
                    if name == 'earnings_call':
                        st.session_state.ec_results = None
                    elif name == 'financial_reports':
                        st.session_state.fr_results = None
        
        st.success("🎉 Analysis execution complete!")
        
        # Display combined results
        st.markdown("---")
        
        # Create tabs for results
        result_tabs = []
        if st.session_state.ec_results:
            result_tabs.append("📈 Earnings Call Summary")
        if st.session_state.fr_results:
            result_tabs.extend(["📊 Financial Tables", "💡 Insights", "🔍 Audit Info", "📈 Statistics"])
        
        if result_tabs:
            tabs = st.tabs(result_tabs)
            tab_idx = 0
            
            # Earnings Call Results
            if st.session_state.ec_results:
                with tabs[tab_idx]:
                    st.subheader("📋 Earnings Call Summary")
                    ec_data = st.session_state.ec_results
                    st.info(f"**Video:** {ec_data['video_title']}\n\n**Date:** {ec_data['upload_date']}")
                    st.markdown(ec_data['summary'])
                    
                    st.download_button(
                        label="📥 Download Earnings Call Summary",
                        data=ec_data['summary'],
                        file_name=f"{company_name}_earnings_summary.txt",
                        mime="text/plain",
                        key="download_ec"
                    )
                tab_idx += 1
            
            # Financial Reports Results
            if st.session_state.fr_results:
                fr_data = st.session_state.fr_results
                
                # Financial Tables
                with tabs[tab_idx]:
                    st.subheader("📊 Financial Comparison Tables")
                    if fr_data['comparison_tables']:
                        for table_name, df in fr_data['comparison_tables'].items():
                            display_table_preview(df, table_name)
                    else:
                        st.warning("No comparison tables generated")
                tab_idx += 1
                
                # Insights
                with tabs[tab_idx]:
                    st.subheader("💡 AI-Generated Insights")
                    if fr_data['insights']:
                        st.markdown(fr_data['insights'])
                    else:
                        st.warning("No insights generated")
                tab_idx += 1
                
                # Audit Info
                with tabs[tab_idx]:
                    st.subheader("🔍 Audit Information")
                    if fr_data['audit_summary']:
                        st.markdown(fr_data['audit_summary'])
                    else:
                        st.warning("No audit information available")
                tab_idx += 1
                
                # Statistics
                with tabs[tab_idx]:
                    st.subheader("📈 Processing Statistics")
                    stats = fr_data['stats']
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Reports Processed", stats['reports_processed'])
                        st.metric("Metrics Extracted", stats['metrics_extracted'])
                    with col2:
                        st.metric("API Calls Made", stats['api_calls'])
                        st.metric("Chunks Processed", stats['chunks_processed'])
                    with col3:
                        st.metric("Tokens Used", f"{fr_data['tokens_used']:,}")
                        st.metric("Data Points", len(fr_data['reports_data']))
                
                # Download section for financial reports
                st.markdown("---")
                st.subheader("📥 Download Reports")
                
                if os.path.exists(fr_data['word_path']):
                    with open(fr_data['word_path'], "rb") as file:
                        st.download_button(
                            label="📄 Download Complete Financial Report (Word)",
                            data=file.read(),
                            file_name=f"{company_name}_financial_analysis_{default_year}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="download_word"
                        )
                    
                    raw_data = {
                        "company_name": company_name,
                        "default_year": default_year,
                        "reports_data": fr_data['reports_data'],
                        "processing_stats": fr_data['stats'],
                        "insights": fr_data['insights'],
                        "audit_summary": fr_data['audit_summary']
                    }
                    
                    st.download_button(
                        label="📊 Download Raw Data (JSON)",
                        data=json.dumps(raw_data, indent=2, default=str),
                        file_name=f"{company_name}_raw_data_{default_year}.json",
                        mime="application/json",
                        key="download_json"
                    )
        else:
            st.warning("No results to display. Please check the error messages above.")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    **Financial Analysis Suite** - Run both earnings call analysis and financial report extraction in parallel!
    
    """)

if __name__ == "__main__":
    main()