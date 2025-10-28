# RAG

requirements

- ollama
- ollama run mxbai-embed-large
- ollama run gemma3:1b

setup docker qdrant local
```bash
docker run -p 6333:6333 -p 6334:6334 \
-v "$(pwd)/qdrant_storage:/qdrant/storage:z" \
qdrant/qdrant
```

setup python environment
```bash
python -m venv rag-qdrant-env
source rag-qdrant-env/bin/activate
pip install -e .
```

run the script
```bash
python main.py
```

setup ts environment
```bash
pnpm install
```

run the script
```bash
pnpm run dev
```
