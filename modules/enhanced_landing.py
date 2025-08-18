# modules/enhanced_landing.py
"""
Enhanced landing page styling and components
Minimal integration with existing Streamlit app
"""

import streamlit as st

def inject_custom_css():
    """Inject custom CSS for enhanced styling"""
    st.markdown("""
    <style>
    /* Enhanced button styling */
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* Success message styling */
    .stAlert > div {
        border-radius: 8px;
        border-left: 4px solid #28a745;
    }
    
    /* Selectbox styling */
    .stSelectbox > div > div {
        border-radius: 6px;
    }
    
    /* Column spacing */
    .block-container {
        padding-top: 1rem;
    }
    
    /* Info box styling */
    .stAlert[data-baseweb="notification"] {
        border-radius: 8px;
    }
    
    /* Metric styling */
    [data-testid="metric-container"] {
        background: white;
        border: 1px solid #e0e0e0;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    
    /* Table styling */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
    }
    
    /* Header styling */
    .stMarkdown h3 {
        color: #2c3e50;
        border-bottom: 2px solid #3498db;
        padding-bottom: 0.5rem;
    }
    </style>
    """, unsafe_allow_html=True)
