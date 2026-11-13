import os
import requests
import streamlit as st

API_URL = os.getenv("FINSIGHT_API_URL", "http://api:8000").rstrip("/")
API_KEY = os.environ["FINSIGHT_API_KEY"]
HEADERS = {"X-API-Key": API_KEY}

st.set_page_config(page_title="FinSight RAG", page_icon="📊", layout="wide")


def api_get(path):
    response = requests.get(f"{API_URL}{path}", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def ask(question):
    response = requests.post(
        f"{API_URL}/ask",
        headers=HEADERS,
        json={"question": question},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30, show_spinner=False)
def get_companies():
    return api_get("/companies")


st.title("📊 FinSight RAG")
st.caption("Ask questions about annual filings · Powered by LangChain, Qdrant and OpenRouter")

with st.sidebar:
    st.header("Document catalog")
    if st.button("Refresh catalog", use_container_width=True):
        get_companies.clear()
        st.rerun()

    try:
        companies = get_companies()["companies"]
        count = sum(row["document_count"] for row in companies)
        left, right = st.columns(2)
        left.metric("Companies", len(companies))
        right.metric("Documents", count)
        if companies:
            st.dataframe(
                [
                    {"Company": row["company"], "Documents": row["document_count"]}
                    for row in companies
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No indexed filings found.")
    except (requests.RequestException, KeyError, ValueError) as exc:
        st.error("Could not load the Snowflake document catalog.")
        st.caption(str(exc))

    st.caption("Counts include successfully indexed filings only.")

if "messages" not in st.session_state:
    st.session_state.messages = []

if st.button("Clear chat"):
    st.session_state.messages = []
    st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("Retrieved sources"):
                for src in msg["sources"]:
                    st.write(
                        f"{src.get('source', 'Unknown')} · "
                        f"chunk {src.get('id', '?')}"
                    )

question = st.chat_input("Ask a question about the annual reports...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Loading your response..."):
            try:
                result = ask(question)
                answer = result.get("answer", "No answer returned.")
                sources = result.get("sources", [])
            except requests.RequestException as exc:
                answer = "The request failed. Please check the FastAPI logs."
                sources = []
                st.error(f"Request error: {exc}")
        st.markdown(answer)
        if sources:
            with st.expander("Retrieved sources"):
                for src in sources:
                    st.write(
                        f"{src.get('source', 'Unknown')} · "
                        f"chunk {src.get('id', '?')}"
                    )
    st.session_state.messages.append({
        "role": "assistant", "content": answer, "sources": sources
    })
