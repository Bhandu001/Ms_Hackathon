"""RepoSensei MVP: paste a GitHub repo URL -> beginner-friendly explanation.

Setup:   pip install streamlit requests google-genai
Env vars: GEMINI_API_KEY, (optional) GITHUB_TOKEN
Run:     streamlit run app.py
"""
import os
import re

import requests
import streamlit as st
from google import genai
from google.genai import types

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
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")

    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
        )
    )
    return response.text


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
