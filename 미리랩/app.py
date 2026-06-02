"""Streamlit demo.  Run: streamlit run app.py"""
import streamlit as st
from graph.build import build_graph

st.set_page_config(page_title='Policy Reaction Simulator', layout='wide')
st.title('Policy Reaction Simulator')

policy = st.text_area('Policy to simulate', '')

if st.button('Run') and policy.strip():
    app = build_graph()
    # TODO (Slice 1+): load personas, then app.invoke({...})
    st.info('Graph compiles. Next: wire personas + invoke. (Slice 1)')
