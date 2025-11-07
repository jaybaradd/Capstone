# Financial Analysis Suite

A comprehensive Streamlit application combining two powerful financial analysis tools:

1. **Earnings Call Analyzer** - Analyzes earnings call transcripts from YouTube videos
2. **Financial Data Extractor** - Extracts and analyzes financial metrics from company reports

## Features

### 📈 Earnings Call Analyzer
- Automatically finds and downloads earnings call videos from YouTube
- Transcribes audio using Groq's Whisper API
- Handles large audio files by splitting them into chunks
- Generates AI-powered summaries focused on key financial metrics
- Keyword-based analysis for comprehensive insights

### 📊 Financial Data Extractor
- Extracts financial data from PDF reports (annual/quarterly reports)
- Processes audit files for compliance information
- Creates comparison tables across multiple periods
- Generates AI-powered insights and trend analysis
- Produces comprehensive Word documents with findings

## Installation

1. Clone or download this repository

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Install FFmpeg (required for audio processing):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
   - **Windows**: Download from https://ffmpeg.org/download.html

## Configuration

### API Keys

Set your Groq API key as an environment variable:

```bash
export GROQ_API_KEY="your-api-key-here"
```

Or create a `.env` file in the project directory:
```
GROQ_API_KEY=your-api-key-here
```

Alternatively, you can enter the API key directly in the app's sidebar.

### YouTube API Key

The app includes a YouTube API key for finding earnings call videos. If you need to use your own:

1. Get a YouTube Data API v3 key from Google Cloud Console
2. Replace the `YOUTUBE_API_KEY` value in `combined_app.py`

## Usage

### Running the App

```bash
streamlit run combined_app.py
```

### Using the Earnings Call Analyzer

1. Open the app and navigate to the "Earnings Call Analyzer" tab
2. Enter the company name (e.g., "Infosys")
3. Click "Analyze Earnings Call"
4. Wait for the analysis to complete (may take several minutes)
5. Review the summary and download if needed

### Using the Financial Data Extractor

1. Navigate to the "Financial Data Extractor" tab
2. Enter company name and default year
3. Upload PDF files:
   - Financial reports (annual/quarterly reports)
   - Audit files (optional)
4. Optionally configure filename mapping for better accuracy
5. Click "Start Financial Analysis"
6. Review results in the tabs:
   - Financial Tables
   - AI Insights
   - Audit Information
   - Processing Statistics
7. Download the complete Word report or raw JSON data

## File Structure

```
deployment codes/
├── combined_app.py              # Main Streamlit application
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── my vertical/
│   └── financial_data_extractor.py  # Financial extractor module (required)
└── calls_mp3s/                  # Generated audio files (auto-created)
```

## Important Notes

### For Financial Data Extractor to Work:

1. The `financial_data_extractor.py` file must be in one of these locations:
   - Same directory as `combined_app.py`
   - In the `my vertical` folder (copy it from there to the main directory)

2. Copy the financial_data_extractor.py file:
```bash
cp "my vertical/financial_data_extractor.py" ./
```

### System Requirements

- Python 3.8 or higher
- FFmpeg installed on your system
- At least 4GB RAM for processing large files
- Internet connection for YouTube downloads and API calls

### Audio File Limitations

- Maximum file size: 25MB (files are automatically split if larger)
- Supported format: MP3 (automatically converted from YouTube)
- Audio chunks: 10 minutes each for large files

### PDF Processing

- Supports standard PDF format
- Best results with text-based PDFs (not scanned images)
- Multiple files can be processed simultaneously

## Troubleshooting

### "Financial Data Extractor module not available"
- Copy `financial_data_extractor.py` to the same directory as `combined_app.py`

### "GROQ API key is not configured"
- Set the GROQ_API_KEY environment variable
- Or enter it in the sidebar of the app

### FFmpeg errors
- Ensure FFmpeg is installed and accessible in your PATH
- Update `FFMPEG_PATH` in the code if using a custom installation location

### YouTube download fails
- Check your internet connection
- Verify the company name is correct
- The app searches for "earnings call Q4 FY2025 trendlyne"

## API Usage & Costs

This app uses the Groq API for:
- Audio transcription (Whisper model)
- Text summarization (Llama 3.3 70B model)
- Financial data extraction and analysis

Monitor your API usage on the Groq dashboard to manage costs.

## Dependencies

- streamlit: Web application framework
- groq: AI API client
- google-api-python-client: YouTube API
- yt-dlp: YouTube video/audio downloader
- pydub: Audio processing
- pandas: Data manipulation
- python-docx: Word document generation
- PyPDF2: PDF reading

## Support

For issues or questions:
1. Check the troubleshooting section
2. Verify all dependencies are installed
3. Ensure API keys are configured correctly
4. Check that FFmpeg is properly installed

## License

This is a proprietary application. All rights reserved.
