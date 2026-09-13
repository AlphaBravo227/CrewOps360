# modules/enhanced_landing.py
"""
Enhanced landing page styling and components
Minimal integration with existing Streamlit app
"""

import streamlit as st

def inject_custom_css():
    """Inject custom CSS for enhanced styling - FIXED block-container padding"""
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
    
    /* Top padding on the main block container has to clear Streamlit's app
       header. That header is positioned over the top of the page (3.75rem
       tall, painted in the theme background colour whenever the toolbar is
       shown, at a z-index above page content), and the framework's default
       6rem of top padding is what keeps content out from under it. Setting
       this to 0.5rem tucked the first element of every page - the "Back to
       ..." buttons, the Summer Leave heading, the CrewOps360 banner -
       underneath that bar, where it read as cut off at the top.

       So trim the default rather than remove it: header height plus a small
       gap, which is still noticeably tighter than stock without hiding
       anything. Both selectors are the same element - Streamlit renamed it
       to stMainBlockContainer and kept .block-container as an alias. */
    .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: calc(3.75rem + 0.5rem) !important;
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