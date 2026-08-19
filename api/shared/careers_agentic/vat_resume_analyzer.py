import os
import io
import json
import fitz  # PyMuPDF
import docx2txt
from openai import AzureOpenAI


def get_openai_client() -> AzureOpenAI:
    """Build the Azure OpenAI client for veteran resume analysis.

    Prefers API-key auth (AZURE_OPENAI_API_KEY) to match the rest of the
    codebase (see shared/core/llm_factory.py) and to work in local dev
    without an Azure sign-in. Falls back to managed identity / DefaultAzureCredential
    when no API key is configured (e.g. production Function App with a
    managed identity granted access to the Cognitive Services resource).
    """
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()

    if api_key:
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )

def extract_text(file_content: bytes, filename: str) -> str:
    ext = filename.lower().split('.')[-1]
    if ext == 'pdf':
        doc = fitz.open(stream=file_content, filetype="pdf")
        return "".join([page.get_text() for page in doc])
    elif ext == 'docx':
        return docx2txt.process(io.BytesIO(file_content))
    return ""

def analyze_resume(resume_text: str) -> dict:
    client = get_openai_client()
    prompt = """
    You are an expert HR recruitment agent. Analyze this veteran resume. Return a raw JSON object with:
    1. "summary": Short text profiling their military background.
    2. "recommendation": Concrete civilian roles/industries.
    3. "has_corporate_experience": Boolean (true if they have corporate/civilian employment post-retirement, false if transitioning directly).
    """
    
    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": resume_text}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)