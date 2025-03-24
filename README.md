# SiteSpy  
**AI-powered website change monitoring and reporting tool**

SiteSpy is a web monitoring application that tracks content changes on specified websites. Using AI (OpenAI GPT-4o), it intelligently detects **meaningful changes**, filters out noise, and generates **clear, human-readable reports** with visual diffs.

👉 **[Live Demo](https://sitespy.streamlit.app/)** — Try it instantly in your browser.

## Features

- 🔄 Periodic monitoring of any list of websites  
- 🤖 AI-based change summarization (GPT-4o)  
- ⚠️ Smart filtering for meaningful vs. superficial changes  
- 📊 Side-by-side HTML diff reports  
- 🧠 User preference-based change interpretation  
- 📁 Simple, local storage – no database required  
- 🎛️ Web interface built with Streamlit  

## Getting Started

1. **Setup**
   - Clone the repository  
     ```bash
     git clone https://github.com/yourusername/sitespy.git
     cd sitespy
     ```
   - Install dependencies  
     ```bash
     pip install -r requirements.txt
     ```
   - Create a `.env` file with your OpenAI API key:  
     ```env
     OPENAI_API_KEY=your-openai-key-here
     ```

2. **Usage Options**
   - **CLI mode**  
     ```bash
     python main.py
     ```
   - **Streamlit Web App**  
     ```bash
     streamlit run app.py
     ```
