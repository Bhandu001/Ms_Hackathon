@echo off
REM Azure Web App will set PORT. If not set, default to 8501.
IF "%PORT%"=="" (
    set PORT=8501
)

echo Starting Streamlit on port %PORT%
REM optionally disable CORS in case you embed, and set headless
python -m streamlit run app.py --server.port %PORT% --server.headless true --server.enableCORS false