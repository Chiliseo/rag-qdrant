import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import yaml
import re
import uuid
import os
import json

url = "http://localhost:6333"
client = QdrantClient(url=url)


# check first not created the collection on qdrant if not create a collection
if not client.collection_exists(collection_name="articles"):
    client.create_collection(
        collection_name="articles",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )


def extract_metadata_from_md(file_path: str):
    with open(file_path, "r") as file:
        content = file.read()

    parts = content.split("---")
    MIN_PART = 3
    if len(parts) < MIN_PART:
        return {}, content

    raw_metadata = parts[1]
    article_content = "---".join(parts[2:]).strip()

    try:
        metadata = yaml.safe_load(raw_metadata)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML metadata:{e}")
        return {}, article_content

    return metadata, article_content


def create_chunks(article_content: str):
    chunks = []
    current_chunk = ""

    for line in article_content.split("\n\n"):

        chunks.append(current_chunk)
        current_chunk += line + "\n"

    return chunks


def clean_article_content(article_content: str):
    cleaned_content = re.sub(r"^import .*\n?", "",
                             article_content, flags=re.MULTILINE)

    cleaned_content = re.sub(r"<[^>]+>", "", cleaned_content)

    return cleaned_content.strip()


def generate_response(prompt: str):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "gemma3:1b",
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_ctx": 10000
            }
        },
        stream=True
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return ""

    full_response = ""
    print("Streaming response:")
    print("-" * 50)

    for line in response.iter_lines():
        if line:
            try:
                # Decode the line and parse JSON
                line_str = line.decode('utf-8')
                if line_str.strip():
                    json_data = line_str
                    # Parse the JSON to extract the response text
                    data = json.loads(json_data)
                    if 'response' in data:
                        chunk = data['response']
                        print(chunk, end='', flush=True)
                        full_response += chunk
                    # Check if this is the final response
                    if data.get('done', False):
                        break
            except json.JSONDecodeError:
                # Skip invalid JSON lines
                continue
            except Exception as e:
                print(f"Error processing line: {e}")
                continue

    print("\n" + "-" * 50)
    return full_response


def generate_embeddings(text: str):
    response = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": "mxbai-embed-large", "input": text},
    )
    print(response, "POST call")
    print(response.text, "TEXT")
    print(response.content, "CONTENT")

    if len(response.json()["embeddings"]) > 0:
        return response.json()["embeddings"][0]
    else:
        return None


def store_article(metadata: dict, chunks: list[str]):
    for chunk in chunks:
        # Generate a unique ID for each chunk
        chunk_id = str(uuid.uuid4())
        adjusted_metadata = {
            **metadata,
            "content": chunk
        }
        embeddings = generate_embeddings(chunk)

        if embeddings is not None:
            client.upsert(
                collection_name="articles",
                wait=True,
                points=[PointStruct(
                    id=chunk_id, vector=embeddings,
                    payload=adjusted_metadata
                )],
            )


def main():
    article_files = [f for f in os.listdir("./../articles") if f.endswith(".md")]
    print(article_files)
    for article_file in article_files:
        file_path = os.path.join("./../articles", article_file)
        metadata, article_content = extract_metadata_from_md(file_path)
        # cleaned_article_content = clean_article_content(article_content)
        chunks = create_chunks(article_content)
        metadata["slug"] = article_file.replace(".md", "")
        # print(metadata, article_file, chunks, article_content)
        # store_article(metadata=metadata, chunks=chunks)

# Add fallback title if not present in metadata
        if "title" not in metadata or not metadata["title"]:
            # Extract title from filename or first line of content
            title = article_file.replace(".md", "").replace(
                "_", " ").replace("-", " ")
            # Try to get title from first meaningful line of content
            lines = article_content.split('\n')
            for line in lines:
                line = line.strip()
                if line and len(line) > 10 and not line.startswith('[') and not line.startswith('Home'):
                    title = line[:100]  # Limit title length
                    break
            metadata["title"] = title
    prompt = input("Enter a prompt: ")
    adjusted_prompt = f"Represent this sentence for searching relevant passages: {prompt}"

    response = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": "mxbai-embed-large",
              "input": adjusted_prompt, },
    )

    # print(response, "POST call")
    # print(response.text, "TEXT")
    # print(response.content, "CONTENT")
    data = response.json()
    embeddings = data["embeddings"][0]

    results = client.query_points(
        collection_name="articles",
        query=embeddings,
        with_payload=True,
        limit=10
    )

    # relevant_passages = "\n".join(
    #     [f"- Article Title: {point.payload['title']} -- Article Slug: {point.payload['slug']} -- Article Content: {point.payload['content']}" for point in results.points])

    relevant_passages = "\n".join([
        f"- Article Title: {point.payload.get('title', 'Unknown')} -- Article Slug: {point.payload.get('slug', 'unknown')} -- Article Content: {point.payload.get('content', 'No content available')}"
        for point in results.points
    ])

    # print(relevant_passages)

    augmented_prompt = f"""
      The following are relevant passages:
      <retrieved-data>
      {relevant_passages}
      </retrieved-data>

      Here's the original user prompt, answer with help of the retrieved passages:
      <user-prompt>
      {prompt}
      </user-prompt>
    """

    response = generate_response(augmented_prompt)


if __name__ == "__main__":
    main()
