"""
RepoSensei MVP: paste a GitHub repo URL -> beginner-friendly explanation.

Setup:
    pip install -r requirements.txt
Env vars:
    AZURE_OPENAI_KEY        (required)  - API key for Azure OpenAI
    AZURE_OPENAI_BASE       (required)  - Endpoint, e.g. https://your-resource-name.openai.azure.com
    AZURE_OPENAI_MODEL      (required)  - Deployment name you created in Azure (e.g. "gpt-4o-deploy")
    GITHUB_TOKEN            (optional)  - GitHub token for higher rate limits / private repos

Run:
    streamlit run app.py
"""
import os
import re
import requests
import streamlit as st
import openai  # OpenAI Python package (used to call Azure OpenAI)

GH = "https://api.github.com"
TOKEN = os.getenv("GITHUB_TOKEN")
AUTH = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
JSON = {"Accept": "application/vnd.github+json", **AUTH}
RAW = {"Accept": "application/vnd.github.raw+json", **AUTH}

SKIP = ("node_modules/", "vendor/", "dist/", "build/", ".git/", "package-lock.json", "yarn.lock")
KEY_NAMES = ("main.", "app.", "index.", "server.", "manage.py", "package.json",
             "requirements.txt", "dockerfile", "pyproject.toml", "pom.xml", "go.mod")


def parse_url(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", url.strip())
    if not m:
        raise ValueError("Paste a link like https://github.com/owner/repo")
    return m.group(1), m.group(2).removesuffix(".git")


def get_tree(owner, repo):
    info = requests.get(f"{GH}/repos/{owner}/{repo}", headers=JSON, timeout=20)
    if info.status_code == 404:
        raise ValueError(f"Repository '{owner}/{repo}' not found. Make sure the link is public.")
    info.raise_for_status()
    info = info.json()
    branch = info["default_branch"]
    tree = requests.get(f"{GH}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
                        headers=JSON, timeout=20)
    tree.raise_for_status()
    paths = [t["path"] for t in tree.json()["tree"]
             if t["type"] == "blob" and not any(s in t["path"] for s in SKIP)]
    return info, branch, paths


def pick_key_files(paths, limit=8):
    hits = [p for p in paths
            if p.split("/")[-1].lower().startswith(KEY_NAMES) and p.count("/") <= 2]
    hits.sort(key=lambda p: p.count("/"))  # shallow files first
    return hits[:limit]


def read_file(owner, repo, path, branch, max_chars=3000):
    r = requests.get(f"{GH}/repos/{owner}/{repo}/contents/{path}",
                     params={"ref": branch}, headers=RAW, timeout=20)
    return r.text[:max_chars] if r.ok else ""


def explain(owner, repo, info, paths, level):
    branch = info["default_branch"]
    readme = requests.get(f"{GH}/repos/{owner}/{repo}/readme", headers=RAW, timeout=20)
    readme = readme.text[:4000] if readme.ok else "(no README)"
    files = "\n\n".join(f"--- {p} ---\n{read_file(owner, repo, p, branch)}"
                        for p in pick_key_files(paths))
    prompt = (
        f"Repository: {owner}/{repo}\nDescription: {info.get('description')}\n\n"
        f"README:\n{readme}\n\nFile list (first 150):\n" + "\n".join(paths[:150]) +
        f"\n\nKey files:\n{files}"
    )
    system_instruction = (
        f"You are a friendly mentor helping a {level} understand an open-source project. "
        "Use ONLY the information provided. Answer in Markdown with these sections: "
        "1) What it does, 2) Tech stack, 3) Folder map (what each main folder is for), "
        "4) Reading order (5 files to read first, with paths and why), "
        "5) How to run it, 6) Ideas for a first contribution. "
        "Mention file paths so the reader can verify. If unsure, say so."
    )

    # Azure OpenAI config from env
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    azure_base = os.getenv("AZURE_OPENAI_BASE")  # e.g. https://<resource-name>.openai.azure.com
    azure_model = os.getenv("AZURE_OPENAI_MODEL")  # deployment name in Azure

    if not (azure_key and azure_base and azure_model):
        raise ValueError("Please set AZURE_OPENAI_KEY, AZURE_OPENAI_BASE, and AZURE_OPENAI_MODEL env vars.")

    # Configure openai python client for Azure
    openai.api_type = "azure"
    openai.api_key = azure_key
    openai.api_base = azure_base.rstrip("/")  # no trailing slash
    # api_version may be required depending on your resource; many examples use "2023-05-15" or newer.
    # If your Azure resource expects a specific api-version, set it via AZURE_OPENAI_API_VERSION env var.
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    if api_version:
        openai.api_version = api_version

    # Construct messages for chat
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    # Call Azure OpenAI Chat Completions via the OpenAI library
    try:
        # For Azure, model param should be the deployment name you created in portal
        resp = openai.ChatCompletion.create(
            engine=azure_model,  # 'engine' or 'deployment' name (older alias). OpenAI python lib uses 'engine' for Azure.
            messages=messages,
            max_tokens=1200,
            temperature=0.2,
            top_p=1.0,
        )
    except Exception as e:
        # show helpful error
        raise RuntimeError(f"Azure OpenAI request failed: {e}")

    # Extract text from response
    # Different versions may return resp.choices[0].message.content
    try:
        text = resp.choices[0].message["content"] if hasattr(resp, "choices") else resp["choices"][0]["message"]["content"]
    except Exception:
        # fallback to string conversion
        text = str(resp)

    return text


st.set_page_config(page_title="RepoSensei", page_icon="🧭")
st.title("🧭 RepoSensei")
st.caption("Understand any GitHub project in minutes - built for students.")

url = st.text_input("GitHub repo URL", placeholder="https://github.com/pallets/flask")
level = st.radio("Explain it like I'm a...", ["complete beginner", "college student", "experienced developer"],
                 horizontal=True)

if st.button("Explain it") and url:
    try:
        with st.spinner("Reading the repo and thinking..."):
            owner, repo = parse_url(url)
            info, branch, paths = get_tree(owner, repo)
            answer = explain(owner, repo, info, paths, level)
        st.markdown(answer)
        st.caption(f"Analyzed {len(paths)} files. AI-generated: verify against the code.")
    except Exception as e:
        st.error(f"Something went wrong: {e}")